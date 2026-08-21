"""FastAPI composition root for the Cloud Agent Platform MVP."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse

from src.api.discovery_routes import create_discovery_router
from src.api.routes import bearer_auth, install_task_api
from src.discovery_ui import DISCOVERY_UI
from src.models.repository import TaskNotFound
from src.observability import configure_logging
from src.platform import Platform, create_platform


def create_app(platform: Platform | None = None, *, start_worker: bool = True) -> FastAPI:
    configure_logging()
    platform = platform or create_platform()
    stop = asyncio.Event()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        worker_task = None
        if start_worker:
            worker_task = asyncio.create_task(platform.worker.run_forever(stop))
        try:
            yield
        finally:
            stop.set()
            if worker_task is not None:
                await worker_task

    app = FastAPI(
        title="Cloud Agent Platform API",
        version="0.1.0",
        description="Bounded and auditable autonomous repository tasks.",
        lifespan=lifespan,
    )
    app.state.platform = platform
    access_logger = logging.getLogger("cloud_agent.access")

    @app.middleware("http")
    async def access_log(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        started = monotonic()
        response = await call_next(request)
        access_logger.info(
            "http_request_completed",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": int((monotonic() - started) * 1000),
            },
        )
        return response

    install_task_api(
        app,
        platform.service,
        expected_bearer_token=platform.settings.bearer_token,
    )
    authenticate = bearer_auth(platform.settings.bearer_token)
    app.include_router(
        create_discovery_router(platform.discovery, authenticate=authenticate),
    )

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, exc: HTTPException) -> JSONResponse:
        code = "UNAUTHORIZED" if exc.status_code == 401 else "TASK_NOT_FOUND"
        message = "invalid bearer token" if exc.status_code == 401 else "task not found"
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": code, "message": message, "retryable": False},
        )

    @app.get("/healthz", tags=["operations"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", tags=["operations"])
    async def readyz() -> JSONResponse:
        checks = {
            "repositoryImportRoot": platform.settings.repository_import_root.is_dir(),
            "llmProvider": platform.settings.llm_provider in {"demo", "openai"},
            "sandboxBackend": platform.settings.sandbox_backend == "local"
            or shutil.which("docker") is not None,
        }
        ready = all(checks.values())
        return JSONResponse(
            status_code=200 if ready else 503,
            content={
                "status": "ready" if ready else "not_ready",
                "checks": checks,
                "mode": {
                    "environment": platform.settings.app_env,
                    "llmProvider": platform.settings.llm_provider,
                    "model": platform.settings.openai_model,
                    "sandboxBackend": platform.settings.sandbox_backend,
                },
            },
        )

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def home() -> HTMLResponse:
        return HTMLResponse(
            """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>Cloud Agent Platform</title></head>
<body style="font-family:system-ui;max-width:760px;margin:64px auto;padding:0 20px">
<h1>Cloud Agent Platform MVP</h1>
<p>平台已启动。请选择入口：</p>
<ul>
  <li><a href="/discovery">需求挖掘与软件设计报告</a></li>
  <li><a href="/docs">任务 API 文档</a></li>
  <li><a href="/readyz">配置与就绪状态</a></li>
</ul>
<p><strong>安全提示：</strong>local 沙箱只适合可信的本地开发输入。</p>
</body></html>""",
            headers={"Cache-Control": "no-store"},
        )

    @app.get(
        "/discovery",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    async def discovery_ui() -> HTMLResponse:
        return HTMLResponse(DISCOVERY_UI, headers={"Cache-Control": "no-store"})

    @app.get("/v1/tasks/{taskId}/events", operation_id="streamTaskEvents")
    async def task_events(
        taskId: str,
        after_sequence: int = Query(0, alias="afterSequence", ge=0),
        tenant_id: str = Depends(authenticate),
    ) -> StreamingResponse:
        try:
            await platform.service.get_task_for_tenant(taskId, tenant_id=tenant_id)
        except TaskNotFound:
            raise HTTPException(status_code=404, detail="task not found") from None
        events = await platform.events.list_after(taskId, after_sequence)

        async def stream() -> AsyncIterator[str]:
            for event in events:
                payload = json.dumps(event.to_public_dict(), ensure_ascii=False)
                yield f"id: {event.sequence}\nevent: {event.event_type}\ndata: {payload}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/v1/tasks/{taskId}/artifacts", operation_id="listTaskArtifacts")
    async def task_artifacts(
        taskId: str,
        request: Request,
        tenant_id: str = Depends(authenticate),
    ) -> dict[str, list[dict[str, object]]]:
        try:
            await platform.service.get_task_for_tenant(taskId, tenant_id=tenant_id)
        except TaskNotFound:
            raise HTTPException(status_code=404, detail="task not found") from None
        artifacts = await platform.artifacts.list(taskId)
        items: list[dict[str, object]] = []
        for artifact in artifacts:
            path = Path(artifact.storage_path)
            stat_result = await asyncio.to_thread(path.stat)
            created = datetime.fromtimestamp(stat_result.st_mtime, timezone.utc)
            items.append(
                {
                    "id": artifact.artifact_id,
                    "name": artifact.name,
                    "mediaType": artifact.media_type,
                    "sizeBytes": artifact.size_bytes,
                    "sha256": artifact.sha256,
                    "createdAt": created.isoformat(),
                    "downloadUrl": str(
                        request.url_for(
                            "download_artifact",
                            taskId=taskId,
                            artifactId=artifact.artifact_id,
                        )
                    ),
                }
            )
        return {"items": items}

    @app.get(
        "/v1/tasks/{taskId}/artifacts/{artifactId}",
        operation_id="downloadTaskArtifact",
        name="download_artifact",
        response_class=FileResponse,
        responses={
            200: {
                "description": "Artifact contents",
                "content": {
                    "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
                },
            },
            404: {
                "description": "Task or artifact not found",
                "content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}
                },
            },
        },
    )
    async def download_artifact(
        taskId: str,
        artifactId: str,
        tenant_id: str = Depends(authenticate),
    ) -> FileResponse:
        try:
            await platform.service.get_task_for_tenant(taskId, tenant_id=tenant_id)
        except TaskNotFound:
            raise HTTPException(status_code=404, detail="task not found") from None
        artifact = await platform.artifacts.get(taskId, artifactId)
        artifact_exists = artifact is not None and await asyncio.to_thread(
            Path(artifact.storage_path).is_file
        )
        if artifact is None or not artifact_exists:
            raise HTTPException(status_code=404, detail="artifact not found")
        return FileResponse(
            artifact.storage_path,
            media_type=artifact.media_type,
            filename=artifact.name,
        )

    return app


app = create_app()
