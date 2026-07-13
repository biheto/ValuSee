from __future__ import annotations

import time
from typing import Any
from uuid import uuid4

from app.harness.events import utc_now_iso
from app.persistence.sqlite_store import task_store
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
        output = skill_registry.execute(
            skill_code,
            SkillContext(task_id=task_id, agent_code=agent_code, variables={}),
            payload,
        )
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
