from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from app.harness.events import EventSink


@dataclass
class AgentExecutionContext:
    goal: str
    project_path: str | None = None
    task_id: str = field(default_factory=lambda: f"task_{uuid4().hex}")
    status: str = "created"
    variables: dict[str, Any] = field(default_factory=dict)
    events: EventSink = field(default_factory=EventSink)

    def to_state(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "goal": self.goal,
            "project_path": self.project_path,
            "status": self.status,
            "events": self.events.to_list(),
            **self.variables,
        }

