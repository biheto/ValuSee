from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class SkillContext:
    task_id: str | None = None
    agent_code: str | None = None
    variables: dict[str, Any] = field(default_factory=dict)


class Skill(Protocol):
    code: str
    name: str
    description: str
    category: str
    execution_type: str
    source_plugin: str
    permissions: list[str]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]

    def execute(self, context: SkillContext, input_data: dict[str, Any]) -> dict[str, Any]:
        """Run a capability and return structured output."""

