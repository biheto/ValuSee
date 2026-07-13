from __future__ import annotations

import json
import re
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.marketplace.catalog import get_builtin_manifest
from app.persistence.rag_store import rag_store
from app.persistence.sqlite_store import task_store
from app.providers.llm_provider import llm_provider


SUPPORTED_PACKAGE_TYPES = {
    "skill_pack",
    "rag_pack",
    "mcp_pack",
    "benchmark_pack",
    "workflow_pack",
    "prompt_pack",
}


def preview_marketplace_package(source_url: str) -> dict[str, Any]:
    manifest = _load_manifest(source_url)
    return {"manifest": _public_manifest(manifest), "summary": _summarize_manifest(manifest)}


def install_marketplace_package(source_url: str) -> dict[str, Any]:
    manifest = _load_manifest(source_url)
    _validate_manifest(manifest)
    package_type = str(manifest["package_type"])
    install_id = f"mpi_{uuid4().hex}"
    summary: dict[str, Any] = {}
    try:
        summary = _apply_manifest(manifest)
        status = "installed"
        error_message = None
    except Exception as exc:
        status = "failed"
        error_message = str(exc)
    record = task_store.save_marketplace_install(
        {
            "install_id": install_id,
            "package_id": str(manifest.get("package_id") or manifest.get("name")),
            "name": str(manifest.get("name") or manifest.get("package_id")),
            "package_type": package_type,
            "version": str(manifest.get("version") or ""),
            "source_url": source_url,
            "status": status,
            "summary": summary,
            "manifest": _public_manifest(manifest),
            "error_message": error_message,
        }
    )
    if error_message:
        raise RuntimeError(error_message)
    return record


def uninstall_marketplace_package(package_id: str) -> dict[str, Any]:
    package_id = package_id.strip()
    if not package_id:
        raise ValueError("package_id is required")
    latest = task_store.get_latest_marketplace_install(package_id)
    if not latest:
        raise FileNotFoundError(f"Marketplace package is not installed: {package_id}")
    if latest.get("status") == "uninstalled":
        return latest

    package_type = str(latest.get("package_type") or "")
    manifest = latest.get("manifest") if isinstance(latest.get("manifest"), dict) else {}
    summary: dict[str, Any]
    if package_type == "skill_pack":
        removed = task_store.uninstall_skill_plugin(package_id)
        if not removed:
            raise FileNotFoundError(f"Skill plugin not found: {package_id}")
        summary = {"removed": True, **removed}
    else:
        summary = {
            "removed": False,
            "package_type": package_type,
            "message": "Package inventory was marked uninstalled. Shared artifacts are kept to avoid deleting user data.",
        }

    return task_store.save_marketplace_install(
        {
            "install_id": f"mpi_{uuid4().hex}",
            "package_id": package_id,
            "name": str(latest.get("name") or manifest.get("name") or package_id),
            "package_type": package_type,
            "version": latest.get("version") or manifest.get("version"),
            "source_url": latest.get("source_url"),
            "status": "uninstalled",
            "summary": summary,
            "manifest": manifest,
            "error_message": None,
        }
    )


def _apply_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    package_type = str(manifest["package_type"])
    summary = _summarize_manifest(manifest)
    if package_type == "skill_pack":
        plugin = {
            "plugin_id": str(manifest.get("package_id") or manifest.get("name")),
            "name": str(manifest.get("name") or manifest.get("package_id")),
            "version": str(manifest.get("version") or "1.0.0"),
            "source_type": "marketplace",
            "source_url": str(manifest.get("source_url") or ""),
            "author": manifest.get("author"),
            "description": manifest.get("description"),
            "enabled": True,
        }
        skills = [_normalize_skill(plugin["plugin_id"], skill) for skill in manifest.get("skills") or []]
        task_store.seed_builtin_skills(plugin, skills)
        summary["installed_skills"] = [skill["code"] for skill in skills]
    elif package_type == "rag_pack":
        saved = []
        for note in manifest.get("rag_notes") or []:
            saved.append(
                rag_store.add_note(
                    str(note.get("collection") or "project-memory"),
                    str(note.get("path") or f"marketplace/{manifest.get('package_id')}"),
                    str(note.get("content") or ""),
                )
            )
        summary["saved_notes"] = saved
    elif package_type == "mcp_pack":
        servers = [task_store.save_mcp_server(server) for server in manifest.get("mcp_servers") or []]
        summary["registered_servers"] = [server["server_id"] for server in servers]
    elif package_type == "workflow_pack":
        workflows = []
        for workflow in manifest.get("workflows") or []:
            workflows.append(
                task_store.save_workflow(
                    str(workflow.get("workflow_id") or f"wf_{uuid4().hex}"),
                    str(workflow.get("name") or "Marketplace Workflow"),
                    workflow.get("description"),
                    list(workflow.get("nodes") or []),
                    list(workflow.get("edges") or []),
                )
            )
        summary["installed_workflows"] = [workflow["workflow_id"] for workflow in workflows]
    elif package_type == "prompt_pack":
        prompts = [llm_provider.save_prompt_version(prompt) for prompt in manifest.get("prompts") or []]
        summary["installed_prompts"] = [prompt["prompt_version"] for prompt in prompts]
    elif package_type == "benchmark_pack":
        summary["benchmark_cases"] = manifest.get("benchmark_cases") or []
    return summary


def _normalize_skill(plugin_id: str, skill: dict[str, Any]) -> dict[str, Any]:
    code = str(skill.get("code") or "").strip()
    if not code:
        raise ValueError("skill.code is required")
    default_input = skill.get("default_input") if isinstance(skill.get("default_input"), dict) else {}
    if skill.get("prompt_template"):
        default_input = {**default_input, "_prompt_template": skill.get("prompt_template")}
    return {
        "code": code,
        "source_plugin": plugin_id,
        "name": str(skill.get("name") or code),
        "description": str(skill.get("description") or ""),
        "category": str(skill.get("category") or "marketplace"),
        "execution_type": str(skill.get("execution_type") or "prompt"),
        "permissions": list(skill.get("permissions") or []),
        "input_schema": skill.get("input_schema") if isinstance(skill.get("input_schema"), dict) else {},
        "output_schema": skill.get("output_schema") if isinstance(skill.get("output_schema"), dict) else {},
        "default_input": default_input,
    }


def _summarize_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "package_type": manifest.get("package_type"),
        "source_format": manifest.get("source_format") or "plugin_json",
        "permissions": manifest.get("permissions") or [],
        "skills": len(manifest.get("skills") or []),
        "rag_notes": len(manifest.get("rag_notes") or []),
        "mcp_servers": len(manifest.get("mcp_servers") or []),
        "benchmark_cases": len(manifest.get("benchmark_cases") or []),
        "workflows": len(manifest.get("workflows") or []),
        "prompts": len(manifest.get("prompts") or []),
    }


def _public_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "package_id",
        "name",
        "version",
        "package_type",
        "author",
        "description",
        "source_format",
        "compatibility",
        "permissions",
        "skills",
        "rag_notes",
        "mcp_servers",
        "benchmark_cases",
        "workflows",
        "prompts",
    }
    return {key: value for key, value in manifest.items() if key in allowed}


def _validate_manifest(manifest: dict[str, Any]) -> None:
    if not manifest.get("package_id") and not manifest.get("name"):
        raise ValueError("plugin.json requires package_id or name")
    package_type = str(manifest.get("package_type") or "")
    if package_type not in SUPPORTED_PACKAGE_TYPES:
        raise ValueError(f"Unsupported package_type: {package_type}")


def _load_manifest(source_url: str) -> dict[str, Any]:
    source = source_url.strip()
    if not source:
        raise ValueError("source_url is required")
    if source.startswith("builtin://"):
        package_id = source.removeprefix("builtin://").strip()
        manifest = get_builtin_manifest(package_id)
        if not manifest:
            raise FileNotFoundError(f"Built-in package not found: {package_id}")
        manifest["source_url"] = source
        return manifest
    path = Path(source).expanduser()
    if path.exists():
        manifest = _load_local_manifest(path)
        manifest["source_url"] = path.as_posix()
        return manifest
    if source.startswith(("http://", "https://")):
        manifest = _load_remote_manifest(source)
        manifest["source_url"] = source
        return manifest
    raise FileNotFoundError(f"Unsupported marketplace source: {source}")


def _load_local_manifest(path: Path) -> dict[str, Any]:
    if path.is_dir():
        manifest_path = path / "plugin.json"
    else:
        manifest_path = path
    if manifest_path.suffix.lower() == ".zip":
        with tempfile.TemporaryDirectory() as temp_dir:
            with zipfile.ZipFile(manifest_path) as archive:
                archive.extractall(temp_dir)
            return _find_manifest(Path(temp_dir))
    if manifest_path.is_dir() or not manifest_path.exists():
        return _find_manifest(path)
    if manifest_path.name.lower() == "skill.md":
        return _skill_md_manifest(manifest_path.parent, [manifest_path])
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _load_remote_manifest(url: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as temp_dir:
        target = Path(temp_dir) / "package"
        lower_url = url.lower()
        if lower_url.endswith(".json") or lower_url.endswith("/plugin.json"):
            data = _download_bytes(url)
            return json.loads(data.decode("utf-8"))
        if lower_url.endswith("skill.md"):
            target.mkdir(parents=True, exist_ok=True)
            skill_path = target / "SKILL.md"
            skill_path.write_bytes(_download_bytes(url))
            return _skill_md_manifest(target, [skill_path])
        download_url = _github_zip_url(url) or url
        data = _download_bytes(download_url)
        zip_path = target.with_suffix(".zip")
        zip_path.write_bytes(data)
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(target)
        return _find_manifest(target)


def _download_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "DevAgent-Studio-Marketplace/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def _github_zip_url(url: str) -> str | None:
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return None
    owner, repo = parts[0], parts[1].removesuffix(".git")
    branch = "main"
    if len(parts) >= 5 and parts[2] == "tree":
        branch = parts[3]
    return f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/{branch}"


def _find_manifest(root: Path) -> dict[str, Any]:
    direct = root / "plugin.json"
    if direct.exists():
        return json.loads(direct.read_text(encoding="utf-8"))
    matches = list(root.rglob("plugin.json"))
    if matches:
        return json.loads(matches[0].read_text(encoding="utf-8"))
    skill_matches = sorted(root.rglob("SKILL.md"), key=lambda path: (len(path.relative_to(root).parts), path.as_posix()))
    if not skill_matches:
        raise FileNotFoundError("plugin.json or SKILL.md not found in package")
    package_root = _external_skill_package_root(root, skill_matches)
    return _skill_md_manifest(package_root, skill_matches)


def _external_skill_package_root(root: Path, skill_paths: list[Path]) -> Path:
    children = [path for path in root.iterdir() if path.is_dir()]
    if len(children) == 1 and all(_is_relative_to(path, children[0]) for path in skill_paths):
        return children[0]
    return root


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _skill_md_manifest(package_root: Path, skill_paths: list[Path]) -> dict[str, Any]:
    package_id = _slugify(package_root.name) or "external-skill-pack"
    skills = []
    used_codes: set[str] = set()
    for index, skill_path in enumerate(skill_paths, start=1):
        content = skill_path.read_text(encoding="utf-8", errors="replace").strip()
        title = _skill_md_title(content) or _title_from_path(skill_path)
        description = _skill_md_description(content, title)
        code_base = f"external.{package_id}.{_slugify(title) or f'skill-{index}'}"
        code = code_base
        suffix = 2
        while code in used_codes:
            code = f"{code_base}-{suffix}"
            suffix += 1
        used_codes.add(code)
        relative_path = skill_path.relative_to(package_root).as_posix() if _is_relative_to(skill_path, package_root) else skill_path.name
        skills.append(
            {
                "code": code,
                "name": title,
                "description": description,
                "category": "external-skill",
                "execution_type": "prompt",
                "permissions": ["llm.call"],
                "input_schema": {"goal": "string", "context": "string", "project_path": "string"},
                "output_schema": {"report_markdown": "string"},
                "default_input": {
                    "goal": "Use this imported SKILL.md capability.",
                    "context": "",
                    "project_path": ".",
                    "_source_format": "External SKILL.md",
                    "_source_path": relative_path,
                    "_conversion_mode": "Prompt Skill",
                    "_safety_note": "Third-party code is not executed. The SKILL.md content is used only as prompt instructions.",
                },
                "prompt_template": _external_skill_prompt(title, relative_path, content),
            }
        )
    return {
        "package_id": package_id,
        "name": _title_from_path(package_root),
        "version": "1.0.0",
        "package_type": "skill_pack",
        "author": "External SKILL.md",
        "description": f"Converted from {len(skills)} external SKILL.md file(s).",
        "source_format": "skill_md",
        "compatibility": {"imported_from": "SKILL.md", "mode": "declarative_prompt"},
        "permissions": ["llm.call"],
        "skills": skills,
    }


def _external_skill_prompt(title: str, relative_path: str, content: str) -> str:
    return (
        f"You are executing the imported external Skill `{title}` from `{relative_path}`.\n\n"
        "Use the following SKILL.md instructions as policy and task guidance. Do not claim to have executed external code.\n\n"
        f"--- SKILL.md ---\n{content}\n--- END SKILL.md ---\n\n"
        "User goal: {{goal}}\n"
        "Project path: {{project_path}}\n"
        "Context: {{context}}\n\n"
        "Return a concise Markdown result with assumptions, steps, and next actions."
    )


def _skill_md_title(content: str) -> str | None:
    frontmatter_name = re.search(r"(?im)^title:\s*(.+)$|^name:\s*(.+)$", content)
    if frontmatter_name:
        return (frontmatter_name.group(1) or frontmatter_name.group(2) or "").strip().strip("\"'")
    heading = re.search(r"(?m)^#\s+(.+)$", content)
    if heading:
        return heading.group(1).strip()
    return None


def _skill_md_description(content: str, title: str) -> str:
    lines = content.splitlines()
    if lines and lines[0].strip() == "---":
        for index, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                lines = lines[index + 1 :]
                break
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("---"):
            continue
        return line[:280]
    return f"External Skill imported from SKILL.md: {title}"


def _title_from_path(path: Path) -> str:
    return path.stem.replace("-", " ").replace("_", " ").strip().title() or path.name


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug[:80]
