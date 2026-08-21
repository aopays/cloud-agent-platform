from pathlib import Path

from fastapi.testclient import TestClient

from src.main import create_app
from src.platform import create_platform
from src.shared.settings import Settings


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        bearer_token="test-token",
        artifact_root=tmp_path / "artifacts",
        run_root=tmp_path / "runs",
        repository_import_root=tmp_path,
    )


def test_home_links_to_user_entry_points(tmp_path: Path) -> None:
    app = create_app(create_platform(_settings(tmp_path)), start_worker=False)

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert 'href="/discovery"' in response.text
    assert 'href="/docs"' in response.text
    assert 'href="/readyz"' in response.text


def test_readiness_is_safe_and_reports_runtime_mode(tmp_path: Path) -> None:
    app = create_app(create_platform(_settings(tmp_path)), start_worker=False)

    with TestClient(app) as client:
        response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["mode"] == {
        "environment": "development",
        "llmProvider": "demo",
        "model": "gpt-5.4-mini",
        "sandboxBackend": "local",
    }
    assert "apiKey" not in response.text
