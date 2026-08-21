"""Docker-backed MVP sandbox.

Docker adds useful namespace and cgroup controls, but is not claimed as a final
boundary for arbitrary hostile code. Production should evaluate a stronger
runtime such as gVisor, Kata Containers, or Firecracker.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import shutil
from dataclasses import replace
from pathlib import Path

from src.shared.contracts import TaskSpec
from src.shared.interfaces import CommandResult

from .errors import SandboxLaunchError, SandboxPolicyError
from .policy import DockerResourceLimits, SandboxPolicy
from .process import validate_argv
from .session import WorkspaceSession, _validate_id

_SAFE_IMAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@-]{0,511}$")


def container_name(task_id: str, attempt_id: str) -> str:
    """Return a bounded non-secret name without exposing raw user identifiers."""

    digest = hashlib.sha256(f"{task_id}\0{attempt_id}".encode()).hexdigest()[:24]
    return f"cap-{digest}"


def build_create_argv(
    *,
    docker_binary: str,
    image: str,
    name: str,
    workspace: Path,
    limits: DockerResourceLimits,
    user: str = "65532:65532",
) -> list[str]:
    """Build an argv-only Docker command with secure-by-default P0 controls."""

    if not _SAFE_IMAGE.fullmatch(image):
        raise SandboxPolicyError("Docker image reference is invalid")
    if not re.fullmatch(r"cap-[a-f0-9]{24}", name):
        raise SandboxPolicyError("container name is invalid")
    if not re.fullmatch(r"[1-9][0-9]*:[1-9][0-9]*", user):
        raise SandboxPolicyError("container user must be a non-root numeric uid:gid")
    resolved_workspace = workspace.resolve(strict=True)
    if "," in str(resolved_workspace):
        raise SandboxPolicyError("workspace path cannot contain a comma for Docker --mount")
    mount = f"type=bind,source={resolved_workspace},target=/workspace"
    return [
        docker_binary,
        "create",
        "--name",
        name,
        "--init",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges=true",
        "--pids-limit",
        str(limits.pids),
        "--memory",
        str(limits.memory_bytes),
        "--memory-swap",
        str(limits.memory_bytes),
        "--cpus",
        str(limits.cpus),
        "--user",
        user,
        "--workdir",
        "/workspace",
        "--tmpfs",
        f"/tmp:rw,noexec,nosuid,nodev,size={limits.tmpfs_bytes}",
        "--mount",
        mount,
        "--label",
        "cloud-agent-platform.managed=true",
        image,
    ]


async def _docker_control(argv: list[str], timeout_seconds: int = 15) -> tuple[int, str]:
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except OSError as exc:
        raise SandboxLaunchError("Docker CLI could not be started") from exc
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        raise SandboxLaunchError("Docker control command timed out") from exc
    return process.returncode or 0, output[:4096].decode("utf-8", errors="replace")


class DockerSandboxSession(WorkspaceSession):
    """A container session with host-validated workspace file primitives."""

    def __init__(
        self,
        workspace: Path,
        session_root: Path,
        policy: SandboxPolicy,
        *,
        docker_binary: str,
        name: str,
    ) -> None:
        super().__init__(workspace, session_root, policy)
        self._docker_binary = docker_binary
        self._container_name = name

    async def run_command(self, argv: list[str], timeout_seconds: int) -> CommandResult:
        validate_argv(
            argv,
            max_items=self._policy.max_argv_items,
            max_argument_bytes=self._policy.max_argument_bytes,
        )
        encoded_argv = base64.urlsafe_b64encode(json.dumps(argv).encode()).decode()
        result = await self._run(
            [
                self._docker_binary,
                "exec",
                "--workdir",
                "/workspace",
                self._container_name,
                "python",
                "/opt/cloud-agent/run-command.py",
                encoded_argv,
            ],
            timeout_seconds,
            cwd=self.workspace,
            environment=None,
        )
        if result.timed_out:
            # Killing only the client is insufficient: the exec process could continue remotely.
            await _docker_control([self._docker_binary, "kill", self._container_name])
        return result

    async def cancel(self) -> None:
        await super().cancel()
        try:
            code, output = await _docker_control(
                [self._docker_binary, "kill", self._container_name]
            )
            if code != 0 and "is not running" not in output.lower():
                raise SandboxLaunchError(f"Docker kill failed: {output}")
        except SandboxLaunchError:
            # close() still attempts a force-removal; callers observe cleanup failure.
            pass

    async def close(self) -> None:
        if self._closed:
            return
        await self.cancel()
        code, output = await _docker_control(
            [self._docker_binary, "rm", "--force", self._container_name]
        )
        if code != 0:
            raise SandboxLaunchError(f"Docker removal failed: {output}")
        self._closed = True
        await asyncio.to_thread(shutil.rmtree, self._session_root, True)


class DockerSandboxProvider:
    """Create a fresh, network-disabled Docker container for each attempt."""

    def __init__(
        self,
        root: Path,
        *,
        image: str = "cloud-agent-sandbox:local",
        docker_binary: str = "docker",
        policy: SandboxPolicy | None = None,
        resources: DockerResourceLimits | None = None,
        user: str = "65532:65532",
    ) -> None:
        if not docker_binary:
            raise SandboxPolicyError("docker_binary must not be empty")
        if not _SAFE_IMAGE.fullmatch(image):
            raise SandboxPolicyError("Docker image reference is invalid")
        self._root = root
        self._image = image
        self._docker_binary = docker_binary
        self._policy = policy or SandboxPolicy()
        self._resources = resources or DockerResourceLimits()
        self._user = user

    async def create(self, task_id: str, attempt_id: str, spec: TaskSpec) -> DockerSandboxSession:
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
        name = container_name(task, attempt)
        policy = replace(
            self._policy,
            max_write_bytes=min(self._policy.max_write_bytes, self._resources.workspace_bytes),
            max_output_bytes=min(self._policy.max_output_bytes, spec.limits.max_tool_output_bytes),
            max_command_seconds=min(self._policy.max_command_seconds, spec.limits.max_tool_seconds),
        )
        try:
            create_argv = build_create_argv(
                docker_binary=self._docker_binary,
                image=self._image,
                name=name,
                workspace=workspace,
                limits=self._resources,
                user=self._user,
            )
            code, output = await _docker_control(create_argv)
            if code != 0:
                raise SandboxLaunchError(f"Docker create failed: {output}")
            code, output = await _docker_control([self._docker_binary, "start", name])
            if code != 0:
                raise SandboxLaunchError(f"Docker start failed: {output}")
        except Exception:
            try:
                await _docker_control([self._docker_binary, "rm", "--force", name])
            except SandboxLaunchError:
                pass
            await asyncio.to_thread(shutil.rmtree, session_root, True)
            raise
        return DockerSandboxSession(
            workspace,
            session_root,
            policy,
            docker_binary=self._docker_binary,
            name=name,
        )


__all__ = [
    "DockerResourceLimits",
    "DockerSandboxProvider",
    "DockerSandboxSession",
    "build_create_argv",
    "container_name",
]
