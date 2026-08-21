"""Workspace primitives and the explicitly trusted local adapter."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import stat
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path

from src.shared.contracts import TaskSpec
from src.shared.interfaces import CommandResult

from .errors import SandboxClosedError, SandboxPathError, SandboxPolicyError
from .paths import WorkspacePaths, open_for_write
from .policy import SandboxPolicy
from .process import run_bounded_process, terminate_process_tree, validate_argv

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_CLEANUP_RETRY_DELAYS_SECONDS = (0.02, 0.05, 0.1, 0.2)


def _validate_id(value: str, label: str) -> str:
    if not _SAFE_ID.fullmatch(value):
        raise SandboxPolicyError(f"{label} contains unsafe characters")
    return value


class WorkspaceSession:
    """Reusable bounded file implementation for a per-attempt workspace."""

    def __init__(self, workspace: Path, session_root: Path, policy: SandboxPolicy) -> None:
        self._workspace = workspace.resolve(strict=True)
        self._session_root = session_root.resolve(strict=True)
        self._paths = WorkspacePaths(self._workspace)
        self._policy = policy
        self._cancel_event = asyncio.Event()
        self._closed = False
        self._active: set[asyncio.subprocess.Process] = set()

    @property
    def workspace(self) -> Path:
        return self._workspace

    def _ensure_active(self) -> None:
        if self._closed:
            raise SandboxClosedError("sandbox session is closed")
        if self._cancel_event.is_set():
            raise SandboxClosedError("sandbox session is cancelled")

    async def list_files(self, relative_path: str = ".") -> list[str]:
        self._ensure_active()
        root = self._paths.existing(relative_path, directory=True)
        results: list[str] = []
        for current, directories, files in os.walk(root, followlinks=False):
            current_path = Path(current)
            directories[:] = sorted(
                name for name in directories if not (current_path / name).is_symlink()
            )
            for name in sorted(files):
                candidate = current_path / name
                if candidate.is_symlink() or not candidate.is_file():
                    continue
                results.append(candidate.relative_to(self._workspace).as_posix())
                if len(results) >= self._policy.max_search_files:
                    return results
        return results

    async def read_file(self, relative_path: str) -> str:
        self._ensure_active()
        path = self._paths.existing(relative_path, directory=False)
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
            try:
                if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                    raise SandboxPathError("path is not a regular file")
                content = os.read(descriptor, self._policy.max_file_bytes + 1)
            finally:
                os.close(descriptor)
        except OSError as exc:
            raise SandboxPathError("file could not be safely opened") from exc
        if len(content) > self._policy.max_file_bytes:
            raise SandboxPolicyError("file exceeds the read limit")
        return content.decode("utf-8", errors="replace")

    async def search_text(self, pattern: str, relative_path: str = ".") -> list[str]:
        self._ensure_active()
        if not pattern or len(pattern.encode("utf-8")) > 4_096:
            raise SandboxPolicyError("search pattern is empty or too large")
        alternatives = pattern.split("|")
        if len(alternatives) > 10 or any(
            not item or len(item.encode("utf-8")) > 128 for item in alternatives
        ):
            raise SandboxPolicyError("search accepts at most ten bounded literal alternatives")
        root = self._paths.existing(relative_path)
        candidates = (
            [root]
            if root.is_file()
            else [self._workspace / path for path in await self.list_files(relative_path)]
        )
        matches: list[str] = []
        for index, path in enumerate(candidates):
            if index >= self._policy.max_search_files:
                break
            try:
                text = await self.read_file(path.relative_to(self._workspace).as_posix())
            except (SandboxPathError, SandboxPolicyError):
                continue
            for line_number, line in enumerate(text.splitlines(), start=1):
                if any(item in line for item in alternatives):
                    display = line if len(line) <= 500 else f"{line[:500]}…"
                    matches.append(
                        f"{path.relative_to(self._workspace).as_posix()}:{line_number}:{display}"
                    )
                    if len(matches) >= self._policy.max_search_matches:
                        return matches
        return matches

    async def write_file(self, relative_path: str, content: str) -> None:
        self._ensure_active()
        if not self._policy.allow_writes:
            raise SandboxPolicyError("workspace writes are disabled")
        encoded = content.encode("utf-8")
        if len(encoded) > self._policy.max_write_bytes:
            raise SandboxPolicyError("content exceeds the write limit")
        path = self._paths.writable_file(relative_path)
        try:
            descriptor = open_for_write(path)
            try:
                view = memoryview(encoded)
                while view:
                    written = os.write(descriptor, view)
                    view = view[written:]
            finally:
                os.close(descriptor)
        except OSError as exc:
            raise SandboxPathError("destination could not be safely written") from exc

    async def collect_artifacts(self, relative_paths: Iterable[str]) -> list[Path]:
        self._ensure_active()
        artifacts: list[Path] = []
        total = 0
        for relative_path in relative_paths:
            path = self._paths.existing(relative_path, directory=False)
            size = path.stat().st_size
            total += size
            if total > self._policy.max_artifact_bytes:
                raise SandboxPolicyError("artifacts exceed the total byte limit")
            artifacts.append(path)
        return artifacts

    async def _run(
        self,
        argv: Sequence[str],
        timeout_seconds: int,
        *,
        cwd: Path,
        environment: Mapping[str, str] | None,
    ) -> CommandResult:
        self._ensure_active()
        validate_argv(
            argv,
            max_items=self._policy.max_argv_items,
            max_argument_bytes=self._policy.max_argument_bytes,
        )
        if timeout_seconds < 1:
            raise SandboxPolicyError("timeout_seconds must be positive")
        process_holder: list[asyncio.subprocess.Process] = []

        def register(process: asyncio.subprocess.Process) -> None:
            process_holder.append(process)
            self._active.add(process)

        try:
            return await run_bounded_process(
                argv,
                cwd=cwd,
                timeout_seconds=min(timeout_seconds, self._policy.max_command_seconds),
                output_bytes=self._policy.max_output_bytes,
                cancel_event=self._cancel_event,
                environment=environment,
                on_started=register,
            )
        finally:
            for process in process_holder:
                self._active.discard(process)

    async def cancel(self) -> None:
        self._cancel_event.set()
        await asyncio.gather(
            *(terminate_process_tree(process) for process in tuple(self._active)),
            return_exceptions=True,
        )

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self.cancel()
        for retry_delay in (*_CLEANUP_RETRY_DELAYS_SECONDS, None):
            try:
                await asyncio.to_thread(shutil.rmtree, self._session_root)
                return
            except FileNotFoundError:
                return
            except OSError:
                if retry_delay is None:
                    raise
                # Windows may briefly retain a process or file handle after cancellation.
                await asyncio.sleep(retry_delay)


class LocalSandboxSession(WorkspaceSession):
    """Trusted-development adapter; this does not isolate untrusted code."""

    @staticmethod
    def _sanitized_environment(workspace: Path) -> dict[str, str]:
        allowed = ("PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "LANG", "LC_ALL")
        environment = {name: os.environ[name] for name in allowed if name in os.environ}
        environment.update({"HOME": str(workspace), "USERPROFILE": str(workspace)})
        return environment

    async def run_command(self, argv: list[str], timeout_seconds: int) -> CommandResult:
        return await self._run(
            argv,
            timeout_seconds,
            cwd=self.workspace,
            environment=self._sanitized_environment(self.workspace),
        )


class LocalSandboxProvider:
    """Create host subprocess sessions only when trusted execution is explicit.

    This adapter is useful for tests and local demonstrations. It provides path,
    output, timeout and process cleanup controls, but it cannot enforce network,
    CPU, memory, PID or kernel isolation and must never run untrusted repositories.
    """

    def __init__(
        self,
        root: Path,
        *,
        allow_trusted_execution: bool = False,
        policy: SandboxPolicy | None = None,
    ) -> None:
        self._root = root
        self._trusted = allow_trusted_execution
        self._policy = policy or SandboxPolicy()

    async def create(self, task_id: str, attempt_id: str, spec: TaskSpec) -> LocalSandboxSession:
        if not self._trusted:
            raise SandboxPolicyError(
                "local sandbox is trusted-only; pass allow_trusted_execution=True explicitly"
            )
        task = _validate_id(task_id, "task_id")
        attempt = _validate_id(attempt_id, "attempt_id")
        root = self._root.resolve()
        root.mkdir(parents=True, exist_ok=True)
        session_root = root / task / attempt
        try:
            session_root.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            raise SandboxPolicyError("attempt workspace already exists") from exc
        workspace = session_root / "workspace"
        workspace.mkdir()
        policy = replace(
            self._policy,
            max_output_bytes=min(self._policy.max_output_bytes, spec.limits.max_tool_output_bytes),
            max_command_seconds=min(self._policy.max_command_seconds, spec.limits.max_tool_seconds),
        )
        return LocalSandboxSession(workspace, session_root, policy)


__all__ = ["LocalSandboxProvider", "LocalSandboxSession", "WorkspaceSession"]
