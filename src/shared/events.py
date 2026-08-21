"""Public event envelope shared by API, scheduler, runtime, and sandbox."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True, slots=True)
class AgentEvent:
    task_id: str
    attempt_id: str
    sequence: int
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValueError("sequence must be positive")
        if not self.event_type.strip():
            raise ValueError("event_type must not be empty")

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "taskId": self.task_id,
            "attemptId": self.attempt_id,
            "sequence": self.sequence,
            "type": self.event_type,
            "timestamp": self.timestamp.isoformat().replace("+00:00", "Z"),
            "payload": self.payload,
        }
