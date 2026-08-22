"""HTTP routes for requirement discovery conversations."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import FileResponse, JSONResponse

from src.api.discovery_schemas import (
    AddDiscoveryMessageRequest,
    CreateDiscoverySessionRequest,
    DiscoverySessionResponse,
)
from src.api.routes import AuthDependency, _error
from src.api.schemas import ErrorResponse
from src.discovery import DiscoveryConflict, DiscoveryNotFound, DiscoveryService


def create_discovery_router(
    service: DiscoveryService,
    *,
    authenticate: AuthDependency,
) -> APIRouter:
    router = APIRouter(prefix="/v1/discovery-sessions", tags=["FDE discovery"])

    def response(session: object, request: Request) -> DiscoverySessionResponse:
        from src.discovery import DiscoverySession

        if not isinstance(session, DiscoverySession):
            raise TypeError("expected DiscoverySession")
        download_url = None
        if session.report_artifact is not None:
            download_url = str(
                request.url_for("download_discovery_report", sessionId=session.session_id)
            )
        return DiscoverySessionResponse.from_session(session, download_url=download_url)

    @router.post(
        "",
        status_code=status.HTTP_201_CREATED,
        response_model=DiscoverySessionResponse,
        operation_id="createDiscoverySession",
        summary="Start a multi-turn FDE customer discovery conversation",
        responses={503: {"model": ErrorResponse, "description": "Model unavailable"}},
    )
    async def create_session(
        body: CreateDiscoverySessionRequest,
        request: Request,
        tenant_id: str = Depends(authenticate),
    ) -> DiscoverySessionResponse | JSONResponse:
        try:
            session = await service.create(
                body.requirement,
                context=body.context,
                tenant_id=tenant_id,
            )
        except Exception:
            return _error(
                503,
                code="DISCOVERY_UNAVAILABLE",
                message="requirement discovery assistant is unavailable",
            )
        return response(session, request)

    @router.get(
        "/{sessionId}",
        response_model=DiscoverySessionResponse,
        operation_id="getDiscoverySession",
        summary="Get the conversation, status, and generated report",
        responses={404: {"model": ErrorResponse, "description": "Session not found"}},
    )
    async def get_session(
        sessionId: str,
        request: Request,
        tenant_id: str = Depends(authenticate),
    ) -> DiscoverySessionResponse | JSONResponse:
        try:
            session = await service.get(sessionId, tenant_id=tenant_id)
        except DiscoveryNotFound:
            return _error(404, code="DISCOVERY_NOT_FOUND", message="session not found")
        return response(session, request)

    @router.post(
        "/{sessionId}/messages",
        response_model=DiscoverySessionResponse,
        operation_id="addDiscoveryMessage",
        summary="Record customer evidence and continue FDE discovery",
        responses={
            404: {"model": ErrorResponse, "description": "Session not found"},
            409: {"model": ErrorResponse, "description": "Conversation conflict"},
            503: {"model": ErrorResponse, "description": "Model unavailable"},
        },
    )
    async def add_message(
        sessionId: str,
        body: AddDiscoveryMessageRequest,
        request: Request,
        tenant_id: str = Depends(authenticate),
    ) -> DiscoverySessionResponse | JSONResponse:
        try:
            session = await service.add_user_message(
                sessionId,
                body.content,
                tenant_id=tenant_id,
            )
        except DiscoveryNotFound:
            return _error(404, code="DISCOVERY_NOT_FOUND", message="session not found")
        except DiscoveryConflict as exc:
            return _error(409, code="DISCOVERY_CONFLICT", message=str(exc))
        except Exception:
            return _error(
                503,
                code="DISCOVERY_UNAVAILABLE",
                message="requirement discovery assistant is unavailable",
            )
        return response(session, request)

    @router.post(
        "/{sessionId}/finalize",
        response_model=DiscoverySessionResponse,
        operation_id="finalizeDiscoverySession",
        summary="Generate the FDE technical discovery and solution report",
        responses={
            404: {"model": ErrorResponse, "description": "Session not found"},
            503: {"model": ErrorResponse, "description": "Model unavailable"},
        },
    )
    async def finalize_session(
        sessionId: str,
        request: Request,
        tenant_id: str = Depends(authenticate),
    ) -> DiscoverySessionResponse | JSONResponse:
        try:
            session = await service.finalize(sessionId, tenant_id=tenant_id)
        except DiscoveryNotFound:
            return _error(404, code="DISCOVERY_NOT_FOUND", message="session not found")
        except Exception:
            return _error(
                503,
                code="DISCOVERY_UNAVAILABLE",
                message="requirement discovery assistant is unavailable",
            )
        return response(session, request)

    @router.get(
        "/{sessionId}/report",
        operation_id="downloadDiscoveryReport",
        name="download_discovery_report",
        summary="Download the finalized Markdown FDE technical solution",
        response_class=FileResponse,
        response_model=None,
        responses={
            200: {
                "description": "FDE technical discovery and solution report",
                "content": {"text/markdown": {"schema": {"type": "string", "format": "binary"}}},
            },
            404: {"model": ErrorResponse, "description": "Session not found"},
            409: {"model": ErrorResponse, "description": "Report is not ready"},
        },
    )
    async def download_report(
        sessionId: str,
        tenant_id: str = Depends(authenticate),
    ) -> FileResponse | JSONResponse:
        try:
            artifact = await service.report_artifact(sessionId, tenant_id=tenant_id)
        except DiscoveryNotFound:
            return _error(404, code="DISCOVERY_NOT_FOUND", message="session not found")
        except DiscoveryConflict as exc:
            return _error(409, code="REPORT_NOT_READY", message=str(exc))
        exists = await asyncio.to_thread(Path(artifact.storage_path).is_file)
        if not exists:
            return _error(404, code="REPORT_NOT_FOUND", message="report file not found")
        return FileResponse(
            artifact.storage_path,
            media_type=artifact.media_type,
            filename=artifact.name,
        )

    return router
