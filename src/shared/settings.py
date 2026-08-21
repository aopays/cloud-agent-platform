"""Environment-backed settings without importing framework code."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _load_env_file(path: Path) -> None:
    """Load a predictable .env subset without overriding process variables."""

    if not path.is_file():
        return
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ValueError(f"invalid .env entry on line {line_number}")
        name, raw_value = line.split("=", 1)
        name = name.strip()
        if not _ENV_NAME.fullmatch(name):
            raise ValueError(f"invalid .env variable name on line {line_number}")
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(name, value)


def _project_path(value: str, project_root: Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else project_root / path


@dataclass(frozen=True, slots=True)
class Settings:
    app_env: str = "development"
    bearer_token: str = "local-demo-token"
    artifact_root: Path = PROJECT_ROOT / ".artifacts"
    run_root: Path = PROJECT_ROOT / ".runs"
    repository_import_root: Path = PROJECT_ROOT / "examples"
    repository_allowed_hosts: tuple[str, ...] = ("github.com", "gitlab.com")
    sandbox_backend: str = "local"
    llm_provider: str = "demo"
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.4-mini"
    openai_base_url: str = "https://api.openai.com"

    @classmethod
    def from_environment(
        cls,
        *,
        project_root: Path | None = None,
        env_file: Path | None = None,
    ) -> Settings:
        root = (project_root or PROJECT_ROOT).resolve()
        _load_env_file(env_file or root / ".env")
        return cls(
            app_env=os.getenv("APP_ENV", "development"),
            bearer_token=os.getenv("APP_BEARER_TOKEN", "local-demo-token"),
            artifact_root=_project_path(os.getenv("ARTIFACT_ROOT", ".artifacts"), root),
            run_root=_project_path(os.getenv("RUN_ROOT", ".runs"), root),
            repository_import_root=_project_path(
                os.getenv("REPOSITORY_IMPORT_ROOT", "examples"), root
            ),
            repository_allowed_hosts=tuple(
                host.strip().lower()
                for host in os.getenv("REPOSITORY_ALLOWED_HOSTS", "github.com,gitlab.com").split(
                    ","
                )
                if host.strip()
            ),
            sandbox_backend=os.getenv("SANDBOX_BACKEND", "local").lower(),
            llm_provider=os.getenv("LLM_PROVIDER", "demo").lower(),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5.4-mini"),
            openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com"),
        )
