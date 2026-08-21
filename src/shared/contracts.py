"""Cross-module value objects and lifecycle constants."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TaskStatus(str, Enum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    PREPARING = "PREPARING"
    RUNNING = "RUNNING"
    CANCELLING = "CANCELLING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"


TERMINAL_TASK_STATUSES = frozenset(
    {
        TaskStatus.SUCCEEDED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
        TaskStatus.TIMED_OUT,
    }
)


ALLOWED_TASK_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.CREATED: frozenset({TaskStatus.QUEUED, TaskStatus.CANCELLED, TaskStatus.FAILED}),
    TaskStatus.QUEUED: frozenset(
        {TaskStatus.PREPARING, TaskStatus.CANCELLED, TaskStatus.FAILED, TaskStatus.TIMED_OUT}
    ),
    TaskStatus.PREPARING: frozenset(
        {
            TaskStatus.RUNNING,
            TaskStatus.CANCELLING,
            TaskStatus.FAILED,
            TaskStatus.TIMED_OUT,
        }
    ),
    TaskStatus.RUNNING: frozenset(
        {
            TaskStatus.CANCELLING,
            TaskStatus.SUCCEEDED,
            TaskStatus.FAILED,
            TaskStatus.TIMED_OUT,
        }
    ),
    TaskStatus.CANCELLING: frozenset(
        {TaskStatus.CANCELLED, TaskStatus.FAILED, TaskStatus.TIMED_OUT}
    ),
    TaskStatus.SUCCEEDED: frozenset(),
    TaskStatus.FAILED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
    TaskStatus.TIMED_OUT: frozenset(),
}


@dataclass(frozen=True, slots=True)
class RepositorySpec:
    url: str
    ref: str | None = None


@dataclass(frozen=True, slots=True)
class BudgetLimits:
    wall_time_seconds: int = 900
    max_agent_turns: int = 30
    max_input_tokens: int = 1_000_000
    max_tool_output_bytes: int = 65_536
    max_tool_seconds: int = 30

    def __post_init__(self) -> None:
        if not 10 <= self.wall_time_seconds <= 3_600:
            raise ValueError("wall_time_seconds must be between 10 and 3600")
        if not 1 <= self.max_agent_turns <= 100:
            raise ValueError("max_agent_turns must be between 1 and 100")
        if self.max_input_tokens < 1_000:
            raise ValueError("max_input_tokens must be at least 1000")
        if self.max_tool_output_bytes < 1:
            raise ValueError("max_tool_output_bytes must be positive")
        if self.max_tool_seconds < 1:
            raise ValueError("max_tool_seconds must be positive")


@dataclass(frozen=True, slots=True)
class TaskSpec:
    instruction: str
    repository: RepositorySpec
    limits: BudgetLimits = field(default_factory=BudgetLimits)

    def __post_init__(self) -> None:
        if not self.instruction.strip():
            raise ValueError("instruction must not be empty")
        if len(self.instruction) > 20_000:
            raise ValueError("instruction must not exceed 20000 characters")


@dataclass(frozen=True, slots=True)
class Usage:
    agent_turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    wall_time_seconds: float = 0


@dataclass(frozen=True, slots=True)
class Artifact:
    artifact_id: str
    name: str
    media_type: str
    size_bytes: int
    sha256: str
    storage_path: str


def can_transition(current: TaskStatus, target: TaskStatus) -> bool:
    """Return whether the lifecycle permits an atomic state transition."""

    return target in ALLOWED_TASK_TRANSITIONS[current]
