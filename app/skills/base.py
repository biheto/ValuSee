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

    def execute(self, context: SkillContext, input_data: dict[str, Any]) -> dict[str, Any]:
        """Run a capability and return structured output."""

