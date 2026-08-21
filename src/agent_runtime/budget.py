"""Wall-time, turn, and token accounting for a bounded agent loop."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from time import monotonic

from src.agent_runtime.errors import BudgetExceeded, RuntimeTimedOut
from src.agent_runtime.provider import ModelUsage
from src.shared.contracts import BudgetLimits, Usage


@dataclass(slots=True)
class BudgetTracker:
    limits: BudgetLimits
    clock: Callable[[], float] = monotonic
    agent_turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    _started_at: float = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._started_at = self.clock()

    @property
    def elapsed_seconds(self) -> float:
        return max(0.0, self.clock() - self._started_at)

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self.limits.wall_time_seconds - self.elapsed_seconds)

    def check_before_turn(self) -> None:
        if self.remaining_seconds <= 0:
            raise RuntimeTimedOut("agent wall-time budget was exhausted")
        if self.agent_turns >= self.limits.max_agent_turns:
            raise BudgetExceeded("maximum agent turns were exhausted")
        if self.input_tokens >= self.limits.max_input_tokens:
            raise BudgetExceeded("input token budget was exhausted")

    def record_model_call(self, usage: ModelUsage) -> None:
        self.agent_turns += 1
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        if self.input_tokens > self.limits.max_input_tokens:
            raise BudgetExceeded("input token budget was exceeded")

    def snapshot(self) -> Usage:
        return Usage(
            agent_turns=self.agent_turns,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            wall_time_seconds=self.elapsed_seconds,
        )
