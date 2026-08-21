from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import install_task_api
from src.models.repository import InMemoryTaskRepository
from src.scheduler import CancellationBroker, InMemoryLeaseManager, InMemoryTaskQueue
from src.scheduler.service import TaskLifecycleService


def make_client() -> TestClient:
    service = TaskLifecycleService(
        repository=InMemoryTaskRepository(),
        queue=InMemoryTaskQueue(),
        leases=InMemoryLeaseManager(),
        cancellations=CancellationBroker(),
    )
    app = FastAPI()
    install_task_api(app, service, expected_bearer_token="test-token")
    return TestClient(app)


def headers(key: str = "idempotency-key-001") -> dict[str, str]:
    return {"Authorization": "Bearer test-token", "Idempotency-Key": key}


def payload(instruction: str = "find TODO") -> dict[str, object]:
    return {
        "instruction": instruction,
        "repository": {"url": "https://example.test/repository.git", "ref": "main"},
        "limits": {
            "wallTimeSeconds": 900,
            "maxAgentTurns": 30,
            "maxInputTokens": 100000,
        },
    }


def test_create_get_and_cancel_task() -> None:
    with make_client() as client:
        created = client.post("/v1/tasks", headers=headers(), json=payload())
        assert created.status_code == 202
        body = created.json()
        assert body["id"].startswith("task_")
        assert body["status"] == "QUEUED"
        assert "createdAt" in body

        fetched = client.get(f"/v1/tasks/{body['id']}", headers=headers())
        assert fetched.status_code == 200
        assert fetched.json()["id"] == body["id"]

        cancelled = client.post(f"/v1/tasks/{body['id']}/cancel", headers=headers())
        assert cancelled.status_code == 202
        assert cancelled.json()["status"] == "CANCELLED"


def test_repeated_key_returns_same_task_and_conflict_on_changed_input() -> None:
    with make_client() as client:
        first = client.post("/v1/tasks", headers=headers("repeat-key-001"), json=payload())
        repeated = client.post("/v1/tasks", headers=headers("repeat-key-001"), json=payload())
        conflict = client.post(
            "/v1/tasks",
            headers=headers("repeat-key-001"),
            json=payload("different request"),
        )

        assert first.status_code == repeated.status_code == 202
        assert first.json()["id"] == repeated.json()["id"]
        assert conflict.status_code == 409
        assert conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"


def test_requires_bearer_authentication_and_returns_not_found_schema() -> None:
    with make_client() as client:
        unauthorized = client.post(
            "/v1/tasks",
            headers={"Idempotency-Key": "missing-auth-001"},
            json=payload(),
        )
        missing = client.get("/v1/tasks/task_missing", headers=headers())

        assert unauthorized.status_code == 401
        assert missing.status_code == 404
        assert missing.json() == {
            "code": "TASK_NOT_FOUND",
            "message": "task not found",
            "retryable": False,
        }


def test_invalid_request_uses_documented_bad_request_schema() -> None:
    with make_client() as client:
        response = client.post(
            "/v1/tasks",
            headers=headers("invalid-request-001"),
            json=payload("   "),
        )

        assert response.status_code == 400
        assert response.json()["code"] == "INVALID_REQUEST"
