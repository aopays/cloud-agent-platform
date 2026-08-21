from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from src.main import create_app
from src.platform import create_platform
from src.shared.settings import Settings


def app(tmp_path: Path):
    platform = create_platform(
        Settings(
            bearer_token="test-token",
            artifact_root=tmp_path / "artifacts",
            run_root=tmp_path / "runs",
            repository_import_root=tmp_path,
        )
    )
    return create_app(platform, start_worker=False)


def auth() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def test_multi_turn_discovery_generates_and_downloads_design_report(tmp_path: Path) -> None:
    with TestClient(app(tmp_path)) as client:
        created = client.post(
            "/v1/discovery-sessions",
            headers=auth(),
            json={
                "requirement": "设计一个物流司机排班用的软件",
                "context": "六周内交付，先做 Web 管理端",
            },
        )
        assert created.status_code == 201
        session_id = created.json()["id"]
        assert created.json()["status"] == "DISCOVERY"
        assert "调度员" in created.json()["messages"][-1]["content"]

        for answer in (
            "城市配送，100 名司机和 80 辆车，调度员和司机使用。",
            "必须满足工时休息规则，异常时由调度员审批。",
            "对接 TMS，Web 管理端和司机手机端，局部重排 10 秒内返回。",
        ):
            continued = client.post(
                f"/v1/discovery-sessions/{session_id}/messages",
                headers=auth(),
                json={"content": answer},
            )
            assert continued.status_code == 200
        assert continued.json()["status"] == "READY"

        finalized = client.post(
            f"/v1/discovery-sessions/{session_id}/finalize",
            headers=auth(),
        )
        assert finalized.status_code == 200
        body = finalized.json()
        assert body["status"] == "FINALIZED"
        assert "物流司机排班软件设计报告" in body["report"]
        assert body["artifact"]["name"] == "software-design-report.md"

        downloaded = client.get(body["artifact"]["downloadUrl"], headers=auth())
        assert downloaded.status_code == 200
        assert downloaded.headers["content-type"].startswith("text/markdown")
        assert "MVP 验收标准" in downloaded.text


def test_discovery_ui_and_openapi_are_exposed(tmp_path: Path) -> None:
    application = app(tmp_path)
    with TestClient(application) as client:
        page = client.get("/discovery")
        assert page.status_code == 200
        assert page.headers["cache-control"] == "no-store"
        assert "需求发现 Agent" in page.text
        assert "设计一个物流司机排班用的软件" in page.text
        assert '""":"&quot;"' not in page.text
        assert "element.textContent = value" in page.text

    schema = application.openapi()
    assert "/v1/discovery-sessions" in schema["paths"]
    report = schema["paths"]["/v1/discovery-sessions/{sessionId}/report"]["get"]
    assert "text/markdown" in report["responses"]["200"]["content"]


def test_discovery_requires_authentication(tmp_path: Path) -> None:
    with TestClient(app(tmp_path)) as client:
        response = client.post(
            "/v1/discovery-sessions",
            json={"requirement": "设计一个排班系统"},
        )
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"
