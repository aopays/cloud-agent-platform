"""Vendor-neutral model messages and provider interface."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class Message:
    role: str
    content: str
    tool_call_id: str | None = None
    tool_name: str | None = None

    def __post_init__(self) -> None:
        if self.role not in {"system", "user", "assistant", "tool"}:
            raise ValueError(f"unsupported message role: {self.role}")


@dataclass(frozen=True, slots=True)
class ToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any]

    def __post_init__(self) -> None:
        if not self.call_id.strip() or not self.name.strip():
            raise ValueError("tool call id and name must not be empty")
        if not isinstance(self.arguments, dict):
            raise ValueError("tool arguments must be an object")


@dataclass(frozen=True, slots=True)
class ModelUsage:
    input_tokens: int = 0
    output_tokens: int = 0

    def __post_init__(self) -> None:
        if self.input_tokens < 0 or self.output_tokens < 0:
            raise ValueError("token usage must not be negative")


@dataclass(frozen=True, slots=True)
class ModelResponse:
    final_answer: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    action_summary: str | None = None
    usage: ModelUsage = field(default_factory=ModelUsage)

    def __post_init__(self) -> None:
        has_final = self.final_answer is not None
        if has_final == bool(self.tool_calls):
            raise ValueError("a response must contain exactly one of final_answer or tool_calls")
        if self.final_answer is not None and not self.final_answer.strip():
            raise ValueError("final_answer must not be empty")


class TransientProviderError(RuntimeError):
    """A provider error that may succeed on a bounded retry."""


class ProviderResponseError(RuntimeError):
    """A safe, non-retryable provider or response-contract failure."""


class LLMProvider(Protocol):
    name: str
    model: str

    async def complete(
        self, messages: Sequence[Message], tools: Sequence[dict[str, Any]]
    ) -> ModelResponse: ...


class DemoProvider:
    """Deterministic offline provider for the TODO-report demonstration."""

    name = "demo"
    model = "deterministic-todo-reporter-v1"

    async def complete(
        self, messages: Sequence[Message], tools: Sequence[dict[str, Any]]
    ) -> ModelResponse:
        del tools
        observations = [message for message in messages if message.role == "tool"]
        if not observations:
            return ModelResponse(
                tool_calls=(
                    ToolCall(
                        call_id="demo-search-todos",
                        name="search_text",
                        arguments={"pattern": "TODO|FIXME", "relative_path": "."},
                    ),
                ),
                action_summary="正在搜索仓库中的 TODO 和 FIXME 标记。",
                usage=ModelUsage(input_tokens=40, output_tokens=20),
            )

        matches = observations[-1].content
        report = "# TODO Report\n\n"
        if matches.strip() in {"", "[]"}:
            report += "No TODO or FIXME markers were found."
        else:
            report += "The following markers were found:\n\n```text\n"
            report += matches[:16_000]
            report += "\n```"
        return ModelResponse(
            final_answer=report,
            action_summary="已完成 TODO 扫描并生成报告。",
            usage=ModelUsage(input_tokens=60, output_tokens=max(1, len(report) // 4)),
        )
