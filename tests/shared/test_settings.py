from __future__ import annotations

from pathlib import Path

import pytest

from src.shared.settings import Settings


def test_environment_file_loads_openai_and_project_relative_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "LLM_PROVIDER",
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
        "ARTIFACT_ROOT",
        "RUN_ROOT",
        "REPOSITORY_IMPORT_ROOT",
        "SANDBOX_BACKEND",
    ):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / ".env").write_text(
        "LLM_PROVIDER=openai\n"
        "OPENAI_API_KEY=test-key\n"
        "OPENAI_MODEL=gpt-5.4-mini\n"
        "SANDBOX_BACKEND=local\n",
        encoding="utf-8",
    )

    settings = Settings.from_environment(project_root=tmp_path)

    assert settings.llm_provider == "openai"
    assert settings.openai_api_key == "test-key"
    assert settings.sandbox_backend == "local"
    assert settings.artifact_root == tmp_path / ".artifacts"
    assert settings.run_root == tmp_path / ".runs"
    assert settings.repository_import_root == tmp_path / "examples"


def test_process_environment_wins_over_environment_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".env").write_text("LLM_PROVIDER=openai\n", encoding="utf-8")
    monkeypatch.setenv("LLM_PROVIDER", "demo")

    settings = Settings.from_environment(project_root=tmp_path)

    assert settings.llm_provider == "demo"


def test_invalid_environment_file_reports_line_without_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    (tmp_path / ".env").write_text("not-an-assignment\n", encoding="utf-8")

    with pytest.raises(ValueError, match="line 1"):
        Settings.from_environment(project_root=tmp_path)
