"""Tool registry, policy hook, execution limits, and safe observations."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Protocol

from src.agent_runtime.errors import ToolCallRejected, ToolExecutionTimedOut
from src.agent_runtime.events import redact_text
from src.agent_runtime.provider import ToolCall
from src.shared.interfaces import SandboxSession
from src.tools.schema import SchemaValidationError, validate_arguments


class Permission(str, Enum):
    READ = "read"
    EXECUTE = "execute"
    WRITE = "write"
    RESULT = "result"


@dataclass(frozen=True, slots=True)
class ToolContext:
    sandbox: SandboxSession
    timeout_seconds: int
    max_output_bytes: int


@dataclass(frozen=True, slots=True)
class ToolExecution:
    output: str
    duration_ms: int = 0
    exit_code: int | None = None
    truncated: bool = False
    timed_out: bool = False

    @property
    def output_bytes(self) -> int:
        return len(self.output.encode("utf-8"))

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.output.encode("utf-8")).hexdigest()


ToolHandler = Callable[[dict[str, Any], ToolContext], Awaitable[ToolExecution]]


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    permission: Permission
    handler: ToolHandler

    def public_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


class ToolPolicy(Protocol):
    async def authorize(self, call: ToolCall, definition: ToolDefinition) -> None: ...


class DefaultToolPolicy:
    """P0 policy: reads, sandbox commands, and result submission; writes opt in."""

    def __init__(self, *, allow_write: bool = False, allow_execute: bool = True) -> None:
        self._allowed = {Permission.READ, Permission.RESULT}
        if allow_execute:
            self._allowed.add(Permission.EXECUTE)
        if allow_write:
            self._allowed.add(Permission.WRITE)

    async def authorize(self, call: ToolCall, definition: ToolDefinition) -> None:
        if definition.permission not in self._allowed:
            raise ToolCallRejected(
                f"tool permission '{definition.permission.value}' is not enabled"
            )
        relative_path = call.arguments.get("relative_path")
        if isinstance(relative_path, str):
            posix = PurePosixPath(relative_path)
            windows = PureWindowsPath(relative_path)
            if (
                posix.is_absolute()
                or windows.is_absolute()
                or windows.drive
                or windows.root
                or ".." in posix.parts
                or ".." in windows.parts
            ):
                raise ToolCallRejected("workspace path must be relative and must not contain '..'")


def _truncate_utf8(value: str, max_bytes: int) -> tuple[str, bool]:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value, False
    return encoded[:max_bytes].decode("utf-8", errors="ignore"), True


class ToolRegistry:
    def __init__(self, policy: ToolPolicy | None = None) -> None:
        self._definitions: dict[str, ToolDefinition] = {}
        self._policy = policy or DefaultToolPolicy()

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._definitions:
            raise ValueError(f"tool already registered: {definition.name}")
        self._definitions[definition.name] = definition

    def schemas(self) -> list[dict[str, Any]]:
        return [self._definitions[name].public_schema() for name in sorted(self._definitions)]

    def summarize_arguments(self, call: ToolCall) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        for key, value in call.arguments.items():
            if key == "content":
                raw = str(value).encode("utf-8")
                summary[key] = {"sizeBytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            elif key == "argv" and isinstance(value, list):
                raw = json_output(value).encode("utf-8")
                summary[key] = {
                    "executable": value[0] if value else None,
                    "argumentCount": max(0, len(value) - 1),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
            else:
                summary[key] = value
        return summary

    async def execute(self, call: ToolCall, context: ToolContext) -> ToolExecution:
        definition = self._definitions.get(call.name)
        if definition is None:
            raise ToolCallRejected(f"unknown tool: {call.name}")
        try:
            validate_arguments(call.arguments, definition.parameters)
        except SchemaValidationError as exc:
            raise ToolCallRejected(str(exc)) from exc
        await self._policy.authorize(call, definition)
        timeout = max(0.001, float(context.timeout_seconds))
        try:
            execution = await asyncio.wait_for(definition.handler(call.arguments, context), timeout)
        except asyncio.TimeoutError as exc:
            raise ToolExecutionTimedOut(f"tool '{call.name}' timed out") from exc

        output = redact_text(execution.output)
        output, registry_truncated = _truncate_utf8(output, context.max_output_bytes)
        return ToolExecution(
            output=output,
            duration_ms=execution.duration_ms,
            exit_code=execution.exit_code,
            truncated=execution.truncated or registry_truncated,
            timed_out=execution.timed_out,
        )


def json_output(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)
