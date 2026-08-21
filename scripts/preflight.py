"""Validate local configuration without printing secrets or making API calls."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.platform import create_platform  # noqa: E402
from src.shared.settings import Settings  # noqa: E402


def main() -> int:
    try:
        settings = Settings.from_environment(project_root=ROOT)
        create_platform(settings)
    except (OSError, ValueError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "status": "ready",
                "environment": settings.app_env,
                "llmProvider": settings.llm_provider,
                "model": settings.openai_model,
                "sandboxBackend": settings.sandbox_backend,
                "repositoryImportRoot": str(settings.repository_import_root),
                "apiKeyConfigured": bool(settings.openai_api_key),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
