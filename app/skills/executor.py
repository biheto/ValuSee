from __future__ import annotations

import time
from typing import Any
from uuid import uuid4

from app.harness.events import utc_now_iso
from app.persistence.sqlite_store import task_store
from app.providers.llm_provider import llm_provider
from app.skills.base import SkillContext
from app.skills.builtin import builtin_plugin
from app.skills.registry import skill_registry


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
    if execution_type == "prompt":
        template = str((skill.get("default_input") or {}).get("_prompt_template") or skill.get("description") or skill.get("name") or "")
        user_prompt = _render_template(template, payload)
        fallback = (
            f"# {skill.get('name')}\n\n"
            f"Declarative prompt skill executed.\n\n"
            f"## Input\n\n```json\n{payload}\n```"
        )
        text = llm_provider.generate(
            "You are a DevAgent Studio marketplace skill. Return a concise Markdown report based only on the provided input.",
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
