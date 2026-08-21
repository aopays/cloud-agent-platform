"""Explicit terminal conditions raised by the agent runtime."""

from __future__ import annotations


class RuntimeFailure(RuntimeError):
    """A bounded, user-safe runtime failure."""

    code = "RUNTIME_FAILURE"
    retryable = False


class RuntimeCancelled(RuntimeFailure):
    code = "CANCELLED"


class RuntimeTimedOut(RuntimeFailure):
    code = "TASK_TIMEOUT"


class BudgetExceeded(RuntimeFailure):
    code = "BUDGET_EXCEEDED"


class InvalidModelResponse(RuntimeFailure):
    code = "INVALID_MODEL_RESPONSE"


class ToolCallRejected(RuntimeFailure):
    code = "TOOL_CALL_REJECTED"


class ToolExecutionTimedOut(RuntimeFailure):
    code = "TOOL_TIMEOUT"


class ToolExecutionFailed(RuntimeFailure):
    code = "TOOL_EXECUTION_FAILED"


class RepeatedToolCall(RuntimeFailure):
    code = "REPEATED_TOOL_CALL"


class NoProgress(RuntimeFailure):
    code = "NO_PROGRESS"


class ProviderUnavailable(RuntimeFailure):
    code = "PROVIDER_UNAVAILABLE"
    retryable = True


class ProviderRequestFailed(RuntimeFailure):
    code = "PROVIDER_REQUEST_FAILED"
