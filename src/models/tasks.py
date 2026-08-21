"""Persistence-neutral records for tasks and execution attempts."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any

from src.shared.contracts import TaskSpec, TaskStatus, Usage


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class TaskError:
    code: str
    message: str
    retryable: bool = False


@dataclass(frozen=True, slots=True)
class TaskRecord:
    task_id: str
    tenant_id: str
    spec: TaskSpec
    status: TaskStatus = TaskStatus.CREATED
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: str | None = None
    error: TaskError | None = None
    usage: Usage = field(default_factory=Usage)
    version: int = 0
    cancellation_requested: bool = False

    def with_changes(self, **changes: Any) -> TaskRecord:
        """Return an immutable copy and advance its optimistic-lock version."""

        changes.setdefault("updated_at", utc_now())
        changes.setdefault("version", self.version + 1)
        return replace(self, **changes)


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    attempt_id: str
    task_id: str
    ordinal: int
    created_at: datetime = field(default_factory=utc_now)
    claimed_by: str | None = None
    finished_at: datetime | None = None
    terminal_committed: bool = False
