from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from src.agent_runtime.errors import RuntimeTimedOut
from src.agent_runtime.loop import AgentRuntime, RuntimeResult
from src.agent_runtime.provider import Message, ModelResponse, ModelUsage, ToolCall
from src.main import create_app
from src.platform import create_platform
from src.shared.contracts import RepositorySpec, TaskSpec, TaskStatus, Usage
from src.shared.settings import Settings
from src.tools.builtin import create_default_registry

pytestmark = pytest.mark.e2e


def _wait_for_terminal(client: TestClient, task_id: str) -> dict[str, object]:
    response = None
    for _ in range(150):
        response = client.get(
            f"/v1/tasks/{task_id}",
            headers={"Authorization": "Bearer test-token"},
        )
        if response.json()["status"] in {
            "SUCCEEDED",
            "FAILED",
            "CANCELLED",
            "TIMED_OUT",
        }:
            return cast(dict[str, object], response.json())
        time.sleep(0.02)
    raise AssertionError(f"task did not finish: {response.json() if response else None}")


def _platform(tmp_path: Path):
    return create_platform(
        Settings(
            bearer_token="test-token",
            artifact_root=tmp_path / "artifacts",
            run_root=tmp_path / "runs",
            repository_import_root=tmp_path,
        )
    )


def _create_task(client: TestClient, repository: Path, key: str) -> str:
    response = client.post(
        "/v1/tasks",
        headers={
            "Authorization": "Bearer test-token",
            "Idempotency-Key": key,
        },
        json={
            "instruction": "Find TODO markers.",
            "repository": {"url": repository.as_uri()},
        },
    )
    assert response.status_code == 202
    return cast(str, response.json()["id"])


def test_api_to_worker_todo_report_and_artifact_cleanup(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    access_key = "AKIA" + "ABCDEFGHIJKLMNOP"
    secret_key = "wJalrXUtnFEMI/K7MDENG/bPxRfiCY" + "EXAMPLEKEY"
    (repository / "app.py").write_text(
        "def run():\n"
        "    pass  # TODO: implement the task\n"
        f"# TODO AWS_ACCESS_KEY_ID={access_key}\n"
        f"# TODO AWS_SECRET_ACCESS_KEY={secret_key}\n",
        encoding="utf-8",
    )
    platform = _platform(tmp_path)
    app = create_app(platform)
    headers = {
        "Authorization": "Bearer test-token",
        "Idempotency-Key": "e2e-key-0001",
    }
    body = {
        "instruction": "Find all TODO markers and generate a report.",
        "repository": {"url": repository.as_uri()},
    }

    with TestClient(app) as client:
        created = client.post("/v1/tasks", headers=headers, json=body)
        assert created.status_code == 202
        task_id = created.json()["id"]

        completed = _wait_for_terminal(client, task_id)
        assert completed["status"] == "SUCCEEDED", completed
        assert "app.py:2" in cast(str, completed["result"])
        assert access_key not in cast(str, completed["result"])
        assert secret_key[:12] not in cast(str, completed["result"])
        assert "[REDACTED]" in cast(str, completed["result"])

        artifacts = client.get(
            f"/v1/tasks/{task_id}/artifacts",
            headers={"Authorization": "Bearer test-token"},
        )
        assert artifacts.status_code == 200
        assert artifacts.json()["items"][0]["name"] == "report.md"
        downloaded = client.get(
            artifacts.json()["items"][0]["downloadUrl"],
            headers={"Authorization": "Bearer test-token"},
        )
        assert downloaded.status_code == 200
        assert "app.py:2" in downloaded.text
        assert secret_key[:12] not in downloaded.text

        events = client.get(
            f"/v1/tasks/{task_id}/events",
            headers={"Authorization": "Bearer test-token"},
        )
        assert events.status_code == 200
        assert "event: tool.completed" in events.text

    attempt_directories = list((tmp_path / "runs").glob("task_*/attempt_*"))
    assert attempt_directories == []


def test_runtime_openapi_describes_binary_artifact_download(tmp_path: Path) -> None:
    schema = create_app(_platform(tmp_path), start_worker=False).openapi()
    operation = schema["paths"]["/v1/tasks/{taskId}/artifacts/{artifactId}"]["get"]

    assert "application/octet-stream" in operation["responses"]["200"]["content"]
    assert operation["responses"]["200"]["content"]["application/octet-stream"]["schema"] == {
        "type": "string",
        "format": "binary",
    }
    assert "404" in operation["responses"]


def test_queued_task_can_be_cancelled_idempotently(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    platform = _platform(tmp_path)
    app = create_app(platform, start_worker=False)
    headers = {
        "Authorization": "Bearer test-token",
        "Idempotency-Key": "e2e-key-0002",
    }

    with TestClient(app) as client:
        created = client.post(
            "/v1/tasks",
            headers=headers,
            json={
                "instruction": "Wait for cancellation.",
                "repository": {"url": repository.as_uri()},
            },
        )
        task_id = created.json()["id"]
        cancel_headers = {"Authorization": "Bearer test-token"}
        first = client.post(f"/v1/tasks/{task_id}/cancel", headers=cancel_headers)
        second = client.post(f"/v1/tasks/{task_id}/cancel", headers=cancel_headers)
        assert first.json()["status"] == "CANCELLED"
        assert second.json()["status"] == "CANCELLED"
        events = client.get(
            f"/v1/tasks/{task_id}/events",
            headers=cancel_headers,
        )
        assert '"from": "CREATED", "to": "QUEUED"' in events.text
        assert '"from": "QUEUED", "to": "CANCELLED"' in events.text


class _TimeoutRuntime:
    async def run(self, **_kwargs: object) -> object:
        raise RuntimeTimedOut("test wall clock exhausted")


class _WriteProvider:
    name = "test"
    model = "write-attempt"

    async def complete(
        self, _messages: list[Message], _tools: list[dict[str, Any]]
    ) -> ModelResponse:
        return ModelResponse(
            tool_calls=(ToolCall("write-1", "write_file", {"relative_path": "x", "content": "x"}),),
            usage=ModelUsage(input_tokens=1, output_tokens=1),
        )


class _BlockingProvider:
    name = "test"
    model = "blocking"

    async def complete(
        self, _messages: list[Message], _tools: list[dict[str, Any]]
    ) -> ModelResponse:
        await asyncio.sleep(30)
        return ModelResponse(final_answer="unexpected")


class _LongCommandProvider:
    name = "test"
    model = "long-command"

    async def complete(
        self, messages: list[Message], _tools: list[dict[str, Any]]
    ) -> ModelResponse:
        if not any(message.role == "tool" for message in messages):
            return ModelResponse(
                tool_calls=(
                    ToolCall(
                        "long-command-1",
                        "run_command",
                        {"argv": [sys.executable, "-c", "import time; time.sleep(30)"]},
                    ),
                )
            )
        return ModelResponse(final_answer="unexpected")


class _SlowSuccessRuntime:
    async def run(self, **_kwargs: object) -> RuntimeResult:
        await asyncio.sleep(0.08)
        return RuntimeResult("slow success", Usage(agent_turns=1))


class _CancellationProbeRuntime:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def run(self, **_kwargs: object) -> RuntimeResult:
        self.started.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        return RuntimeResult("unexpected", Usage())


@pytest.mark.parametrize(
    ("runtime", "expected_status", "expected_code"),
    [
        (_TimeoutRuntime(), "TIMED_OUT", "TASK_TIMEOUT"),
        (
            AgentRuntime(_WriteProvider(), create_default_registry(allow_write=False)),
            "FAILED",
            "TOOL_CALL_REJECTED",
        ),
    ],
)
def test_worker_maps_timeout_and_policy_rejection(
    tmp_path: Path,
    runtime: object,
    expected_status: str,
    expected_code: str,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    platform = _platform(tmp_path)
    platform.worker.runtime = cast(Any, runtime)

    with TestClient(create_app(platform)) as client:
        task_id = _create_task(client, repository, f"e2e-{expected_status.lower()}-001")
        completed = _wait_for_terminal(client, task_id)
        assert completed["status"] == expected_status
        error = cast(dict[str, object], completed["error"])
        assert error["code"] == expected_code


def test_running_task_cancellation_reaches_sandbox_and_terminal_state(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    platform = _platform(tmp_path)
    platform.worker.runtime = AgentRuntime(_BlockingProvider(), create_default_registry())

    with TestClient(create_app(platform)) as client:
        task_id = _create_task(client, repository, "e2e-running-cancel")
        for _ in range(100):
            current = client.get(
                f"/v1/tasks/{task_id}",
                headers={"Authorization": "Bearer test-token"},
            ).json()
            if current["status"] == "RUNNING":
                break
            time.sleep(0.01)
        assert current["status"] == "RUNNING"
        cancelled = client.post(
            f"/v1/tasks/{task_id}/cancel",
            headers={"Authorization": "Bearer test-token"},
        )
        assert cancelled.json()["status"] == "CANCELLING"
        completed = _wait_for_terminal(client, task_id)
        assert completed["status"] == "CANCELLED"

    assert list((tmp_path / "runs").glob("task_*/attempt_*")) == []


def test_worker_renews_short_lease_during_long_execution(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    platform = _platform(tmp_path)
    platform.worker.runtime = cast(Any, _SlowSuccessRuntime())
    platform.worker.lease_ttl_seconds = 0.02

    with TestClient(create_app(platform)) as client:
        task_id = _create_task(client, repository, "e2e-heartbeat-001")
        completed = _wait_for_terminal(client, task_id)
        assert completed["status"] == "SUCCEEDED", completed


def test_worker_cancels_runtime_immediately_when_visibility_renewal_fails(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        repository = tmp_path / "repository"
        repository.mkdir()
        platform = _platform(tmp_path)
        runtime = _CancellationProbeRuntime()
        platform.worker.runtime = cast(Any, runtime)
        platform.worker.lease_ttl_seconds = 0.02

        async def fail_visibility(_receipt: str, *, timeout_seconds: float) -> bool:
            assert timeout_seconds > 0
            await runtime.started.wait()
            return False

        platform.queue.extend_visibility = cast(Any, fail_visibility)
        await platform.service.create_task(
            TaskSpec("Find TODO markers", RepositorySpec(repository.as_uri())),
            idempotency_key="lease-loss-test-001",
            tenant_id="local-tenant",
        )

        await asyncio.wait_for(platform.worker.run_once(), timeout=1)
        assert runtime.started.is_set()
        assert runtime.cancelled.is_set()

    asyncio.run(scenario())


def test_cleanup_failure_wins_over_concurrent_cancellation(tmp_path: Path) -> None:
    async def scenario() -> None:
        repository = tmp_path / "repository"
        repository.mkdir()
        platform = _platform(tmp_path)
        platform.worker.runtime = cast(Any, _SlowSuccessRuntime())
        original_create = platform.worker.sandbox_provider.create

        async def create_with_failing_close(*args: object, **kwargs: object):
            session = await original_create(*args, **kwargs)  # type: ignore[arg-type]
            original_close = session.close

            async def failing_close() -> None:
                await original_close()
                raise RuntimeError("simulated cleanup failure")

            session.close = cast(Any, failing_close)  # type: ignore[method-assign]
            return session

        platform.worker.sandbox_provider.create = cast(Any, create_with_failing_close)
        task = await platform.service.create_task(
            TaskSpec("Find TODO markers", RepositorySpec(repository.as_uri())),
            idempotency_key="cleanup-cancel-test-001",
            tenant_id="local-tenant",
        )
        worker = asyncio.create_task(platform.worker.run_once())
        for _ in range(100):
            current = await platform.service.get_task(task.task_id)
            if current.status == TaskStatus.RUNNING:
                break
            await asyncio.sleep(0.002)
        assert current.status == TaskStatus.RUNNING
        await platform.service.cancel_task(task.task_id, tenant_id="local-tenant")
        await asyncio.wait_for(worker, timeout=1)

        finished = await platform.service.get_task(task.task_id)
        assert finished.status == TaskStatus.FAILED
        assert finished.error is not None
        assert finished.error.code == "CLEANUP_FAILED"

    asyncio.run(scenario())


def test_api_cancellation_stops_an_active_sandbox_command(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    platform = _platform(tmp_path)
    platform.worker.runtime = AgentRuntime(
        _LongCommandProvider(), create_default_registry(allow_execute=True)
    )

    with TestClient(create_app(platform)) as client:
        task_id = _create_task(client, repository, "e2e-command-cancel")
        auth = {"Authorization": "Bearer test-token"}
        for _ in range(150):
            events = client.get(f"/v1/tasks/{task_id}/events", headers=auth).text
            if "event: tool.started" in events:
                break
            time.sleep(0.02)
        assert "event: tool.started" in events
        cancelled = client.post(f"/v1/tasks/{task_id}/cancel", headers=auth)
        assert cancelled.json()["status"] == "CANCELLING"
        completed = _wait_for_terminal(client, task_id)
        assert completed["status"] == "CANCELLED", completed

    assert list((tmp_path / "runs").glob("task_*/attempt_*")) == []
