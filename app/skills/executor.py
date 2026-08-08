from __future__ import annotations

import time
from typing import Any
from uuid import uuid4

from app.harness.events import utc_now_iso
from app.persistence.rag_store import rag_store
from app.persistence.sqlite_store import task_store
from app.providers.llm_provider import llm_provider
from app.skills.base import SkillContext
from app.skills.builtin import builtin_plugin
from app.skills.contract import validate_skill_contract
from app.skills.registry import skill_registry
from app.skills.sandbox import python_skill_sandbox_status, run_python_skill_sandbox


def ensure_builtin_skills_seeded() -> None:
    task_store.seed_builtin_skills(builtin_plugin(), skill_registry.list_skills())


def execute_skill(
    skill_code: str,
    input_data: dict[str, Any] | None = None,
    *,
    agent_code: str = "skill_console",
    task_id: str | None = None,
) -> dict[str, Any]:
    ensure_builtin_skills_seeded()
    skill = task_store.get_skill(skill_code)
    if not skill:
        raise KeyError(f"Skill not found: {skill_code}")
    if not skill.get("enabled"):
        raise PermissionError(f"Skill disabled: {skill_code}")
    permissions = skill.get("permissions") if isinstance(skill.get("permissions"), list) else []
    approval = task_store.get_skill_approval(skill_code, agent_code)
    if permissions and not (approval and approval.get("allowed")):
        raise PermissionError(f"Skill `{skill_code}` is not approved for agent `{agent_code}`.")
    contract = validate_skill_contract(skill)
    if not contract["valid"]:
        raise ValueError(f"Skill contract invalid: {'; '.join(contract['errors'])}")
    missing_dependencies = _missing_dependencies(skill)
    if missing_dependencies:
        raise RuntimeError(f"Skill dependencies are missing: {', '.join(missing_dependencies)}")

    payload = {**(skill.get("default_input") or {}), **(input_data or {})}
    log_id = f"skill_log_{uuid4().hex}"
    started = time.perf_counter()
    try:
        try:
            output = skill_registry.execute(
                skill_code,
                SkillContext(task_id=task_id, agent_code=agent_code, variables={}),
                payload,
            )
        except KeyError:
            output = _execute_declarative_skill(skill, payload)
        latency_ms = int((time.perf_counter() - started) * 1000)
        task_store.save_skill_execution_log(
            {
                "log_id": log_id,
                "skill_code": skill_code,
                "agent_code": agent_code,
                "task_id": task_id,
                "input": payload,
                "output": output,
                "status": "completed",
                "latency_ms": latency_ms,
                "created_at": utc_now_iso(),
            }
        )
        return {
            "log_id": log_id,
            "skill": skill,
            "input": payload,
            "output": output,
            "status": "completed",
            "latency_ms": latency_ms,
        }
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        task_store.save_skill_execution_log(
            {
                "log_id": log_id,
                "skill_code": skill_code,
                "agent_code": agent_code,
                "task_id": task_id,
                "input": payload,
                "output": {},
                "status": "failed",
                "error_message": str(exc),
                "latency_ms": latency_ms,
                "created_at": utc_now_iso(),
            }
        )
        raise


def _execute_declarative_skill(skill: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    execution_type = str(skill.get("execution_type") or "prompt")
    if execution_type == "python":
        default_input = skill.get("default_input") if isinstance(skill.get("default_input"), dict) else {}
        entrypoint_path = str(default_input.get("_entrypoint_path") or skill.get("entrypoint") or "")
        function_name = str(default_input.get("_entrypoint_function") or "run")
        timeout_seconds = int(default_input.get("_timeout_seconds") or 10)
        output = run_python_skill_sandbox(entrypoint_path, function_name, payload, timeout_seconds=timeout_seconds)
        sandbox_status = python_skill_sandbox_status()
        return {
            **output,
            "_sandbox": {
                **sandbox_status,
                "timeout_seconds": timeout_seconds,
                "entrypoint": entrypoint_path,
                "third_party_code_executed": True,
            },
        }
    if execution_type == "prompt":
        template = str((skill.get("default_input") or {}).get("_prompt_template") or skill.get("description") or skill.get("name") or "")
        user_prompt = _render_template(template, payload)
        fallback = (
            f"# {skill.get('name')}\n\n"
            f"Declarative prompt skill executed.\n\n"
            f"## Input\n\n```json\n{payload}\n```"
        )
        text = llm_provider.generate(
            "You are a ValuSee marketplace skill. Return a concise Markdown report based only on the provided input.",
            user_prompt,
            fallback,
            agent=f"skill:{skill.get('code')}",
            prompt_version=f"{skill.get('code')}.marketplace.v1",
        )
        return {"report_markdown": text, "answer_source": "llm" if llm_provider.enabled else "fallback"}
    if execution_type == "rule":
        return {
            "report_markdown": f"# {skill.get('name')}\n\nRule skill registered from marketplace.\n\nInput keys: {', '.join(payload.keys())}",
            "input": payload,
        }
    return {
        "report_markdown": f"# {skill.get('name')}\n\nDeclarative skill type `{execution_type}` is registered. Custom execution is not enabled.",
        "input": payload,
    }


def _render_template(template: str, payload: dict[str, Any]) -> str:
    rendered = template
    for key, value in payload.items():
        rendered = rendered.replace("{{" + key + "}}", str(value))
    return rendered


def _missing_dependencies(skill: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    dependencies = skill.get("dependencies") if isinstance(skill.get("dependencies"), list) else []
    for dependency in dependencies:
        if not isinstance(dependency, dict):
            continue
        dep_type = str(dependency.get("type") or "")
        dep_ref = str(dependency.get("ref") or dependency.get("name") or "")
        if not dep_ref:
            continue
        if dep_type == "mcp_tool":
            if ":" in dep_ref:
                server_id, tool_name = dep_ref.split(":", 1)
                found = task_store.get_mcp_tool(server_id, tool_name)
            else:
                found = any(tool.get("name") == dep_ref for tool in task_store.list_mcp_tools())
            if not found:
                missing.append(f"mcp_tool:{dep_ref}")
        elif dep_type == "rag_collection":
            if not rag_store.list_documents(dep_ref):
                missing.append(f"rag_collection:{dep_ref}")
        elif dep_type == "prompt_version":
            agent = str(dependency.get("agent") or "reporter")
            if not task_store.get_prompt_version(agent, dep_ref):
                missing.append(f"prompt_version:{agent}/{dep_ref}")
        elif dep_type == "skill":
            if not task_store.get_skill(dep_ref):
                missing.append(f"skill:{dep_ref}")
        elif dep_type == "llm_model":
            if not llm_provider.enabled:
                missing.append(f"llm_model:{dep_ref}")
    return missing
