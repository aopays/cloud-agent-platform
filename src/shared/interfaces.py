"""Ports that keep the control plane independent from concrete adapters."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from src.shared.contracts import Artifact, TaskSpec
from src.shared.events import AgentEvent


@dataclass(frozen=True, slots=True)
class CommandResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    truncated: bool = False
    timed_out: bool = False


class EventSink(Protocol):
    async def append(self, event: AgentEvent) -> None: ...

    async def append_next(
        self,
        task_id: str,
        attempt_id: str,
        event_type: str,
        payload: dict[str, object],
    ) -> AgentEvent: ...

    async def list_after(self, task_id: str, after_sequence: int = 0) -> list[AgentEvent]: ...


class ArtifactStore(Protocol):
    async def put_text(
        self, task_id: str, name: str, content: str, media_type: str = "text/plain"
    ) -> Artifact: ...

    async def list(self, task_id: str) -> list[Artifact]: ...

    async def get(self, task_id: str, artifact_id: str) -> Artifact | None: ...

    async def delete(self, task_id: str, artifact_id: str) -> bool: ...


class CancellationSignal(Protocol):
    async def is_cancelled(self) -> bool: ...


class SandboxSession(Protocol):
    @property
    def workspace(self) -> Path: ...

    async def list_files(self, relative_path: str = ".") -> list[str]: ...

    async def read_file(self, relative_path: str) -> str: ...

    async def search_text(self, pattern: str, relative_path: str = ".") -> list[str]: ...

    async def write_file(self, relative_path: str, content: str) -> None: ...

    async def run_command(self, argv: list[str], timeout_seconds: int) -> CommandResult: ...

    async def collect_artifacts(self, relative_paths: Iterable[str]) -> list[Path]: ...

    async def close(self) -> None: ...


class SandboxProvider(Protocol):
    async def create(self, task_id: str, attempt_id: str, spec: TaskSpec) -> SandboxSession: ...


class TaskExecutor(Protocol):
    async def execute(self, task_id: str, attempt_id: str) -> None: ...
