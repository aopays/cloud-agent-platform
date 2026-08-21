import pytest

from src.shared.contracts import BudgetLimits, TaskStatus, can_transition
from src.shared.events import AgentEvent


def test_terminal_state_cannot_transition() -> None:
    assert not can_transition(TaskStatus.SUCCEEDED, TaskStatus.RUNNING)


def test_running_task_can_be_cancelled_via_cancelling() -> None:
    assert can_transition(TaskStatus.RUNNING, TaskStatus.CANCELLING)
    assert can_transition(TaskStatus.CANCELLING, TaskStatus.CANCELLED)


def test_budget_limits_reject_unbounded_turns() -> None:
    with pytest.raises(ValueError, match="max_agent_turns"):
        BudgetLimits(max_agent_turns=101)


def test_event_uses_public_contract_names() -> None:
    event = AgentEvent(
        task_id="task_123",
        attempt_id="attempt_001",
        sequence=1,
        event_type="task.status_changed",
        payload={"from": "CREATED", "to": "QUEUED"},
    )

    public = event.to_public_dict()

    assert public["taskId"] == "task_123"
    assert public["attemptId"] == "attempt_001"
    assert public["type"] == "task.status_changed"
    assert public["timestamp"].endswith("Z")
