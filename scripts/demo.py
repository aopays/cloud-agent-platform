"""Run the complete offline TODO-report flow without starting an external server."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.main import create_app  # noqa: E402
from src.platform import create_platform  # noqa: E402
from src.shared.settings import Settings  # noqa: E402


def main() -> None:
    platform = create_platform(
        Settings(
            app_env="development",
            bearer_token="local-demo-token",
            artifact_root=ROOT / ".artifacts",
            run_root=ROOT / ".runs",
            repository_import_root=ROOT / "examples",
        )
    )
    headers = {
        "Authorization": "Bearer local-demo-token",
        "Idempotency-Key": "offline-demo-001",
    }
    with TestClient(create_app(platform)) as client:
        response = client.post(
            "/v1/tasks",
            headers=headers,
            json={
                "instruction": "读取仓库，找出所有 TODO 和 FIXME，生成 Markdown 报告。",
                "repository": {"url": (ROOT / "examples" / "demo-repo").as_uri()},
            },
        )
        response.raise_for_status()
        task_id = response.json()["id"]
        print(f"created: {task_id}")

        while True:
            task = client.get(
                f"/v1/tasks/{task_id}",
                headers={"Authorization": "Bearer local-demo-token"},
            ).json()
            print(f"status: {task['status']}")
            if task["status"] in {"SUCCEEDED", "FAILED", "CANCELLED", "TIMED_OUT"}:
                break
            time.sleep(0.05)

        print(json.dumps(task, ensure_ascii=False, indent=2))
        events = client.get(
            f"/v1/tasks/{task_id}/events",
            headers={"Authorization": "Bearer local-demo-token"},
        )
        print("\nevents:\n" + events.text)
        artifacts = client.get(
            f"/v1/tasks/{task_id}/artifacts",
            headers={"Authorization": "Bearer local-demo-token"},
        )
        print("artifacts:\n" + json.dumps(artifacts.json(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
