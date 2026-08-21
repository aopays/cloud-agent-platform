"""Built-in tools implemented exclusively through SandboxSession primitives."""

from __future__ import annotations

from time import monotonic
from typing import Any

from src.tools.registry import (
    Permission,
    ToolContext,
    ToolDefinition,
    ToolExecution,
    ToolRegistry,
    json_output,
)

_PATH = {"type": "string", "minLength": 1, "maxLength": 4096}


async def _list_files(arguments: dict[str, Any], context: ToolContext) -> ToolExecution:
    started = monotonic()
    files = await context.sandbox.list_files(arguments.get("relative_path", "."))
    return ToolExecution(json_output(files), int((monotonic() - started) * 1000))


async def _read_file(arguments: dict[str, Any], context: ToolContext) -> ToolExecution:
    started = monotonic()
    content = await context.sandbox.read_file(arguments["relative_path"])
    return ToolExecution(content, int((monotonic() - started) * 1000))


async def _search_text(arguments: dict[str, Any], context: ToolContext) -> ToolExecution:
    started = monotonic()
    matches = await context.sandbox.search_text(
        arguments["pattern"], arguments.get("relative_path", ".")
    )
    return ToolExecution(json_output(matches), int((monotonic() - started) * 1000))


async def _write_file(arguments: dict[str, Any], context: ToolContext) -> ToolExecution:
    started = monotonic()
    await context.sandbox.write_file(arguments["relative_path"], arguments["content"])
    return ToolExecution("file written", int((monotonic() - started) * 1000))


async def _run_command(arguments: dict[str, Any], context: ToolContext) -> ToolExecution:
    result = await context.sandbox.run_command(arguments["argv"], context.timeout_seconds)
    output = json_output({"stdout": result.stdout, "stderr": result.stderr})
    return ToolExecution(
        output=output,
        duration_ms=result.duration_ms,
        exit_code=result.exit_code,
        truncated=result.truncated,
        timed_out=result.timed_out,
    )


async def _submit_result(arguments: dict[str, Any], context: ToolContext) -> ToolExecution:
    del context
    return ToolExecution(arguments["content"])


def create_default_registry(
    *, allow_write: bool = False, allow_execute: bool = True
) -> ToolRegistry:
    from src.tools.registry import DefaultToolPolicy

    registry = ToolRegistry(DefaultToolPolicy(allow_write=allow_write, allow_execute=allow_execute))
    registry.register(
        ToolDefinition(
            "list_files",
            "List files below a relative workspace path.",
            {
                "type": "object",
                "properties": {"relative_path": _PATH},
                "additionalProperties": False,
            },
            Permission.READ,
            _list_files,
        )
    )
    registry.register(
        ToolDefinition(
            "read_file",
            "Read a UTF-8 file from the workspace.",
            {
                "type": "object",
                "properties": {"relative_path": _PATH},
                "required": ["relative_path"],
                "additionalProperties": False,
            },
            Permission.READ,
            _read_file,
        )
    )
    registry.register(
        ToolDefinition(
            "search_text",
            "Search text within the workspace.",
            {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "minLength": 1, "maxLength": 1000},
                    "relative_path": _PATH,
                },
                "required": ["pattern"],
                "additionalProperties": False,
            },
            Permission.READ,
            _search_text,
        )
    )
    registry.register(
        ToolDefinition(
            "write_file",
            "Write text to a relative workspace path when policy permits.",
            {
                "type": "object",
                "properties": {
                    "relative_path": _PATH,
                    "content": {"type": "string", "maxLength": 1_000_000},
                },
                "required": ["relative_path", "content"],
                "additionalProperties": False,
            },
            Permission.WRITE,
            _write_file,
        )
    )
    registry.register(
        ToolDefinition(
            "run_command",
            "Run an argv command inside the sandbox (never on the host).",
            {
                "type": "object",
                "properties": {
                    "argv": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1, "maxLength": 4096},
                        "minItems": 1,
                    }
                },
                "required": ["argv"],
                "additionalProperties": False,
            },
            Permission.EXECUTE,
            _run_command,
        )
    )
    registry.register(
        ToolDefinition(
            "submit_result",
            "Submit a final textual result.",
            {
                "type": "object",
                "properties": {"content": {"type": "string", "minLength": 1}},
                "required": ["content"],
                "additionalProperties": False,
            },
            Permission.RESULT,
            _submit_result,
        )
    )
    return registry
