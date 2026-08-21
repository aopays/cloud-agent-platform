#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

port="${APP_PORT:-8001}"
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi

if ! .venv/bin/python -c 'import fastapi, httpx, pydantic, uvicorn' 2>/dev/null; then
  echo "Installing project dependencies..."
  .venv/bin/python -m pip install -c requirements.lock -e '.[dev]'
fi

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created $project_root/.env"
  echo "Fill OPENAI_API_KEY in .env, then run this command again."
  exit 2
fi

.venv/bin/python scripts/preflight.py
echo "Home:      http://127.0.0.1:$port/"
echo "Discovery: http://127.0.0.1:$port/discovery"
echo "API docs:  http://127.0.0.1:$port/docs"
exec .venv/bin/python -m uvicorn src.main:app --host 127.0.0.1 --port "$port" --app-dir "$project_root"
