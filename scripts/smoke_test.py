"""Exercise the public HTTP user journeys against a running local server."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]


def _require(response: httpx.Response, expected: int) -> dict[str, object]:
    if response.status_code != expected:
        raise RuntimeError(
            f"{response.request.method} {response.request.url} returned "
            f"{response.status_code}: {response.text[:500]}"
        )
    body = response.json()
    if not isinstance(body, dict):
        raise RuntimeError("expected a JSON object")
    return body


def run(base_url: str, token: str) -> dict[str, object]:
    auth = {"Authorization": f"Bearer {token}"}
    with httpx.Client(base_url=base_url, timeout=10) as client:
        home = client.get("/")
        home.raise_for_status()
        if "/discovery" not in home.text:
            raise RuntimeError("home page does not link to discovery")
        ready = _require(client.get("/readyz"), 200)
        if ready.get("status") != "ready":
            raise RuntimeError("server is not ready")
        discovery_page = client.get("/discovery")
        discovery_page.raise_for_status()

        session = _require(
            client.post(
                "/v1/discovery-sessions",
                headers=auth,
                json={
                    "requirement": "设计一个物流司机排班用的软件",
                    "context": "六周内交付，先做 Web 管理端",
                },
            ),
            201,
        )
        session_id = str(session["id"])
        for answer in (
            "城市配送，100 名司机和 80 辆车，调度员和司机使用。",
            "必须满足工时休息规则，异常时由调度员审批。",
            "对接 TMS，Web 管理端和司机手机端，局部重排 10 秒内返回。",
        ):
            session = _require(
                client.post(
                    f"/v1/discovery-sessions/{session_id}/messages",
                    headers=auth,
                    json={"content": answer},
                ),
                200,
            )
        if session.get("status") != "READY":
            raise RuntimeError("discovery session did not become READY")
        finalized = _require(
            client.post(
                f"/v1/discovery-sessions/{session_id}/finalize",
                headers=auth,
            ),
            200,
        )
        artifact = finalized.get("artifact")
        if not isinstance(artifact, dict):
            raise RuntimeError("discovery report artifact is missing")
        report = client.get(str(artifact["downloadUrl"]), headers=auth)
        report.raise_for_status()
        if "MVP 验收标准" not in report.text:
            raise RuntimeError("discovery report is incomplete")

        task = _require(
            client.post(
                "/v1/tasks",
                headers={**auth, "Idempotency-Key": f"smoke-{uuid4().hex}"},
                json={
                    "instruction": "读取仓库，找出所有 TODO 和 FIXME，生成 Markdown 报告。",
                    "repository": {"url": (ROOT / "examples" / "demo-repo").as_uri()},
                },
            ),
            202,
        )
        task_id = str(task["id"])
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            task = _require(client.get(f"/v1/tasks/{task_id}", headers=auth), 200)
            if task.get("status") in {"SUCCEEDED", "FAILED", "CANCELLED", "TIMED_OUT"}:
                break
            time.sleep(0.05)
        if task.get("status") != "SUCCEEDED":
            raise RuntimeError(f"repository task did not succeed: {task}")
        events = client.get(f"/v1/tasks/{task_id}/events", headers=auth)
        events.raise_for_status()
        if "event: tool.completed" not in events.text:
            raise RuntimeError("task events are incomplete")
        artifacts = _require(client.get(f"/v1/tasks/{task_id}/artifacts", headers=auth), 200)
        items = artifacts.get("items")
        if not isinstance(items, list) or not items or not isinstance(items[0], dict):
            raise RuntimeError("task artifact is missing")
        task_report = client.get(str(items[0]["downloadUrl"]), headers=auth)
        task_report.raise_for_status()
        if "TODO" not in task_report.text:
            raise RuntimeError("task report does not contain expected findings")

    return {
        "status": "passed",
        "baseUrl": base_url,
        "readiness": ready,
        "discoverySessionId": session_id,
        "discoveryReportBytes": len(report.content),
        "taskId": task_id,
        "taskStatus": task["status"],
        "taskReportBytes": len(task_report.content),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--token", default="local-demo-token")
    args = parser.parse_args()
    print(json.dumps(run(args.base_url, args.token), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
