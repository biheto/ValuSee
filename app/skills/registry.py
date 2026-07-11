from __future__ import annotations

from app.skills.base import Skill, SkillContext
from typing import Any

from app.skills.builtin import builtin_plugin, builtin_skills


class SkillRegistry:
    def __init__(self, skills: list[Skill] | None = None):
        self._skills = {skill.code: skill for skill in (skills or builtin_skills())}

    def list_skills(self) -> list[dict[str, Any]]:
        return [
            {
                "code": skill.code,
                "name": skill.name,
                "description": skill.description,
                "category": getattr(skill, "category", "general"),
                "execution_type": getattr(skill, "execution_type", "agent"),
                "source_plugin": getattr(skill, "source_plugin", builtin_plugin()["plugin_id"]),
                "permissions": list(getattr(skill, "permissions", [])),
                "input_schema": dict(getattr(skill, "input_schema", {})),
                "output_schema": dict(getattr(skill, "output_schema", {})),
                "default_input": dict(getattr(skill, "default_input", {})),
            }
            for skill in self._skills.values()
        ]

    def get(self, code: str) -> Skill:
        if code not in self._skills:
            raise KeyError(f"Skill not found: {code}")
        return self._skills[code]

    def execute(self, code: str, context: SkillContext, input_data: dict) -> dict:
        return self.get(code).execute(context, input_data)


skill_registry = SkillRegistry()

