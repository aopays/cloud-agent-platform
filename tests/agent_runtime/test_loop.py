from __future__ import annotations

import asyncio
import unittest
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from src.agent_runtime import (
    AgentRuntime,
    BudgetExceeded,
    DemoProvider,
    ModelResponse,
    ModelUsage,
    NoProgress,
    ProviderUnavailable,
    RepeatedToolCall,
    RuntimeCancelled,
    RuntimeTimedOut,
    ToolCall,
    ToolCallRejected,
    ToolExecutionTimedOut,
    TransientProviderError,
)
from src.agent_runtime.provider import Message
from src.shared.contracts import BudgetLimits
from src.shared.events import AgentEvent
from src.shared.interfaces import CommandResult
from src.tools import Permission, ToolDefinition, ToolExecution, ToolRegistry
from src.tools.builtin import create_default_registry


class MemorySink:
    def __init__(self) -> None:
        self.events: list[AgentEvent] = []

    async def append(self, event: AgentEvent) -> None:
        self.events.append(event)

    async def list_after(self, task_id: str, after_sequence: int = 0) -> list[AgentEvent]:
        return [
            event
            for event in self.events
            if event.task_id == task_id and event.sequence > after_sequence
        ]


class Cancellation:
    def __init__(self, cancelled: bool = False) -> None:
        self.cancelled = cancelled

    async def is_cancelled(self) -> bool:
        return self.cancelled


class FakeSandbox:
    workspace = Path("/isolated/workspace")

    def __init__(self) -> None:
        self.searches: list[tuple[str, str]] = []
        self.commands: list[tuple[list[str], int]] = []

    async def list_files(self, relative_path: str = ".") -> list[str]:
        return ["README.md", "src/app.py"]

    async def read_file(self, relative_path: str) -> str:
        return "TODO: test"

    async def search_text(self, pattern: str, relative_path: str = ".") -> list[str]:
        self.searches.append((pattern, relative_path))
        return ["src/app.py:1: TODO: test"]

    async def write_file(self, relative_path: str, content: str) -> None:
        return None

    async def run_command(self, argv: list[str], timeout_seconds: int) -> CommandResult:
        self.commands.append((argv, timeout_seconds))
        return CommandResult(0, "ok", "", 1)

    async def collect_artifacts(self, relative_paths: Iterable[str]) -> list[Path]:
        return []

    async def close(self) -> None:
        return None


class SequenceProvider:
    name = "test"
    model = "sequence"

    def __init__(self, responses: list[Any]) -> None:
        self.responses = responses
        self.calls = 0
        self.message_batches: list[tuple[Message, ...]] = []

    async def complete(
        self, messages: Sequence[Message], tools: Sequence[dict[str, Any]]
    ) -> ModelResponse:
        del tools
        self.message_batches.append(tuple(messages))
        value = self.responses[self.calls]
        self.calls += 1
        if isinstance(value, Exception):
            raise value
        return value


def limits(**overrides: int) -> BudgetLimits:
    values = {
        "wall_time_seconds": 30,
        "max_agent_turns": 10,
        "max_input_tokens": 1000,
        "max_tool_output_bytes": 1024,
        "max_tool_seconds": 2,
    }
    values.update(overrides)
    return BudgetLimits(**values)


async def run_runtime(runtime: AgentRuntime, sink: MemorySink, **kwargs: Any):
    return await runtime.run(
        task_id="task-1",
        attempt_id="attempt-1",
        instruction="Find TODOs",
        sandbox=kwargs.get("sandbox", FakeSandbox()),
        event_sink=sink,
        cancellation=kwargs.get("cancellation", Cancellation()),
        limits=kwargs.get("limits", limits()),
    )


class AgentRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_final_answer_and_monotonic_public_events(self) -> None:
        provider = SequenceProvider([ModelResponse(final_answer="done", usage=ModelUsage(12, 3))])
        sink = MemorySink()
        result = await run_runtime(AgentRuntime(provider, create_default_registry()), sink)

        self.assertEqual("done", result.final_answer)
        self.assertEqual(1, result.usage.agent_turns)
        self.assertEqual([1, 2], [event.sequence for event in sink.events])
        self.assertEqual("model.request_completed", sink.events[0].event_type)

    async def test_final_answer_and_event_payloads_are_redacted(self) -> None:
        provider = SequenceProvider(
            [
                ModelResponse(
                    final_answer="authorization: Bearer abcdefghijk",
                    action_summary="api_key=abcdefghijk",
                )
            ]
        )
        sink = MemorySink()
        result = await run_runtime(AgentRuntime(provider, create_default_registry()), sink)

        self.assertNotIn("abcdefghijk", result.final_answer)
        self.assertNotIn("abcdefghijk", str([event.payload for event in sink.events]))

    async def test_demo_provider_uses_sandbox_search_and_returns_report(self) -> None:
        sandbox = FakeSandbox()
        sink = MemorySink()
        result = await run_runtime(
            AgentRuntime(DemoProvider(), create_default_registry()), sink, sandbox=sandbox
        )

        self.assertEqual([("TODO|FIXME", ".")], sandbox.searches)
        self.assertIn("src/app.py", result.final_answer)
        self.assertIn("tool.started", [event.event_type for event in sink.events])
        self.assertIn("tool.completed", [event.event_type for event in sink.events])

    async def test_submit_result_tool_is_a_terminal_action(self) -> None:
        provider = SequenceProvider(
            [
                ModelResponse(
                    tool_calls=(ToolCall("result-1", "submit_result", {"content": "final report"}),)
                )
            ]
        )
        sink = MemorySink()
        result = await run_runtime(AgentRuntime(provider, create_default_registry()), sink)

        self.assertEqual("final report", result.final_answer)
        self.assertEqual(1, provider.calls)

    async def test_multiple_tool_calls_are_returned_as_observations(self) -> None:
        provider = SequenceProvider(
            [
                ModelResponse(
                    tool_calls=(
                        ToolCall("list-1", "list_files", {}),
                        ToolCall("read-1", "read_file", {"relative_path": "README.md"}),
                    )
                ),
                ModelResponse(final_answer="combined"),
            ]
        )
        sink = MemorySink()
        result = await run_runtime(AgentRuntime(provider, create_default_registry()), sink)

        self.assertEqual("combined", result.final_answer)
        completed = [event for event in sink.events if event.event_type == "tool.completed"]
        self.assertEqual(2, len(completed))
        history = provider.message_batches[1]
        call_items = [message for message in history if message.tool_call_id]
        self.assertEqual(
            ["assistant", "tool", "assistant", "tool"],
            [message.role for message in call_items],
        )

    async def test_unknown_tool_is_rejected_and_emits_safe_error(self) -> None:
        provider = SequenceProvider([ModelResponse(tool_calls=(ToolCall("1", "missing", {}),))])
        sink = MemorySink()

        with self.assertRaises(ToolCallRejected):
            await run_runtime(AgentRuntime(provider, create_default_registry()), sink)
        self.assertEqual("TOOL_CALL_REJECTED", sink.events[-1].payload["code"])

    async def test_cancelled_before_model_call(self) -> None:
        provider = SequenceProvider([ModelResponse(final_answer="should not run")])
        sink = MemorySink()

        with self.assertRaises(RuntimeCancelled):
            await run_runtime(
                AgentRuntime(provider, create_default_registry()),
                sink,
                cancellation=Cancellation(True),
            )
        self.assertEqual(0, provider.calls)
        self.assertEqual("CANCELLED", sink.events[-1].payload["code"])

    async def test_cancellation_interrupts_an_inflight_model_request(self) -> None:
        class BlockingProvider:
            name = "test"
            model = "blocking"

            async def complete(self, messages: Any, tools: Any) -> ModelResponse:
                del messages, tools
                await asyncio.sleep(10)
                return ModelResponse(final_answer="late")

        class CancelOnSecondCheck:
            checks = 0

            async def is_cancelled(self) -> bool:
                self.checks += 1
                return self.checks >= 2

        sink = MemorySink()
        with self.assertRaises(RuntimeCancelled):
            await run_runtime(
                AgentRuntime(BlockingProvider(), create_default_registry()),
                sink,
                cancellation=CancelOnSecondCheck(),
            )

    async def test_wall_time_is_checked_before_provider_call(self) -> None:
        class JumpClock:
            def __init__(self) -> None:
                self.calls = 0

            def __call__(self) -> float:
                self.calls += 1
                return 0 if self.calls == 1 else 31

        provider = SequenceProvider([ModelResponse(final_answer="late")])
        sink = MemorySink()
        with self.assertRaises(RuntimeTimedOut):
            await run_runtime(
                AgentRuntime(provider, create_default_registry(), clock=JumpClock()), sink
            )
        self.assertEqual(0, provider.calls)

    async def test_turn_budget_stops_an_unfinished_loop(self) -> None:
        response = ModelResponse(tool_calls=(ToolCall("1", "list_files", {}),))
        provider = SequenceProvider([response])
        sink = MemorySink()

        with self.assertRaises(BudgetExceeded):
            await run_runtime(
                AgentRuntime(provider, create_default_registry()),
                sink,
                limits=limits(max_agent_turns=1),
            )
        self.assertEqual("BUDGET_EXCEEDED", sink.events[-1].payload["code"])

    async def test_token_budget_is_enforced_after_provider_reports_usage(self) -> None:
        provider = SequenceProvider([ModelResponse(final_answer="done", usage=ModelUsage(1001, 1))])
        sink = MemorySink()

        with self.assertRaises(BudgetExceeded):
            await run_runtime(AgentRuntime(provider, create_default_registry()), sink)

    async def test_repeated_identical_call_is_stopped(self) -> None:
        repeated = ModelResponse(tool_calls=(ToolCall("same", "list_files", {}),))
        provider = SequenceProvider([repeated, repeated])
        sink = MemorySink()

        with self.assertRaises(RepeatedToolCall):
            await run_runtime(
                AgentRuntime(
                    provider,
                    create_default_registry(),
                    repeated_call_limit=1,
                    no_progress_limit=10,
                ),
                sink,
            )

    async def test_unchanged_observations_from_distinct_calls_are_stopped(self) -> None:
        provider = SequenceProvider(
            [
                ModelResponse(
                    tool_calls=(ToolCall(str(index), "list_files", {"relative_path": path}),)
                )
                for index, path in enumerate((".", "src", "tests"), 1)
            ]
        )
        sink = MemorySink()

        with self.assertRaises(NoProgress):
            await run_runtime(
                AgentRuntime(provider, create_default_registry(), no_progress_limit=2), sink
            )

    async def test_transient_provider_errors_retry_a_bounded_number(self) -> None:
        provider = SequenceProvider(
            [TransientProviderError("temporary"), ModelResponse(final_answer="recovered")]
        )
        sink = MemorySink()
        result = await run_runtime(AgentRuntime(provider, create_default_registry()), sink)

        self.assertEqual("recovered", result.final_answer)
        self.assertEqual(2, provider.calls)

    async def test_exhausted_provider_retries_preserve_only_safe_reason(self) -> None:
        provider = SequenceProvider(
            [TransientProviderError("OpenAI request returned retryable HTTP 429")] * 3
        )

        with self.assertRaisesRegex(ProviderUnavailable, "retryable HTTP 429"):
            await run_runtime(AgentRuntime(provider, create_default_registry()), MemorySink())

    async def test_slow_tool_is_timed_out(self) -> None:
        async def slow(arguments: dict[str, Any], context: Any) -> ToolExecution:
            del arguments, context
            await asyncio.sleep(0.05)
            return ToolExecution("late")

        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                "slow",
                "slow test tool",
                {"type": "object", "additionalProperties": False},
                Permission.READ,
                slow,
            )
        )
        provider = SequenceProvider([ModelResponse(tool_calls=(ToolCall("slow-1", "slow", {}),))])
        sink = MemorySink()
        runtime = AgentRuntime(provider, registry)

        # The public contract uses integer seconds. Override execution to prove
        # the registry itself enforces its context timeout without waiting a second.
        original_execute = registry.execute

        async def execute_with_short_timeout(call: ToolCall, context: Any) -> ToolExecution:
            context = type(context)(context.sandbox, 0.001, context.max_output_bytes)
            return await original_execute(call, context)

        registry.execute = execute_with_short_timeout  # type: ignore[method-assign]
        with self.assertRaises(ToolExecutionTimedOut):
            await run_runtime(runtime, sink)
        completed = [event for event in sink.events if event.event_type == "tool.completed"]
        self.assertEqual("error", completed[-1].payload["outcome"])


if __name__ == "__main__":
    unittest.main()
