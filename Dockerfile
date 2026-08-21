FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    REPOSITORY_IMPORT_ROOT=/app/examples \
    ARTIFACT_ROOT=/app/.artifacts \
    RUN_ROOT=/app/.runs

WORKDIR /app

COPY pyproject.toml requirements.lock README.md LICENSE ./
COPY src ./src
COPY examples ./examples

RUN pip install --no-cache-dir -c requirements.lock .

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/.artifacts /app/.runs \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"]

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
