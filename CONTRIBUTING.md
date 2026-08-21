# Contributing

Thank you for improving Cloud Agent Platform. Keep changes small, reviewable, and aligned
with the current MVP boundary.

## Local setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -c requirements.lock -e ".[dev]"
Copy-Item .env.example .env
```

Use `LLM_PROVIDER=demo` for deterministic tests. Never put a real API key in tests, fixtures,
issues, screenshots, or commits.

## Required checks

```powershell
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy src
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pytest -m security -q
.\.venv\Scripts\python.exe -m compileall -q src tests scripts
```

New behavior requires tests. Defect fixes require a regression test. Do not weaken security
defaults or silently broaden network, filesystem, command, credential, or approval access.

## Pull requests

- Explain the problem, scope, design trade-offs, security impact, and verification evidence.
- Update contracts and documentation when behavior changes.
- Avoid unrelated formatting or generated files.
- Keep production claims consistent with implemented adapters and executed tests.
