from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4


BEIJING_TZ = timezone(timedelta(hours=8))
BEIJING_TIME_FORMAT = "%Y-%m-%d, %H:%M"


def utc_now_iso() -> str:
    return datetime.now(BEIJING_TZ).strftime(BEIJING_TIME_FORMAT)


@dataclass
class AgentEvent:
    task_id: str
    type: str
    content: str
    node: str | None = None
    agent: str | None = None
    status: str = "running"
    data: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: f"evt_{uuid4().hex}")
    timestamp: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "task_id": self.task_id,
            "type": self.type,
            "node": self.node,
            "agent": self.agent,
            "status": self.status,
            "content": self.content,
            "data": self.data,
            "timestamp": self.timestamp,
        }


class EventSink:
    def __init__(self):
        self.events: list[AgentEvent] = []

    def emit(
        self,
        task_id: str,
        type: str,
        content: str,
        node: str | None = None,
        agent: str | None = None,
        status: str = "running",
        data: dict[str, Any] | None = None,
    ) -> AgentEvent:
        event = AgentEvent(
            task_id=task_id,
            type=type,
            content=content,
            node=node,
            agent=agent,
            status=status,
            data=data or {},
        )
        self.events.append(event)
        return event

    def to_list(self) -> list[dict[str, Any]]:
        return [event.to_dict() for event in self.events]
