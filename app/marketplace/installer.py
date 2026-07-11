from __future__ import annotations

import json
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
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _load_remote_manifest(url: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as temp_dir:
        target = Path(temp_dir) / "package"
        if url.endswith(".json") or url.endswith("/plugin.json"):
            data = _download_bytes(url)
            return json.loads(data.decode("utf-8"))
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
    if not matches:
        raise FileNotFoundError("plugin.json not found in package")
    return json.loads(matches[0].read_text(encoding="utf-8"))
