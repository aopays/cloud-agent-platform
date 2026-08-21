"""Task lifecycle HTTP routes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from secrets import compare_digest

from fastapi import APIRouter, Depends, FastAPI, Header, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.api.schemas import CreateTaskRequest, ErrorResponse, TaskResponse
from src.models.repository import IdempotencyConflict, TaskNotFound
from src.scheduler.service import TaskLifecycleService

AuthDependency = Callable[..., Awaitable[str]]


def _error(status_code: int, *, code: str, message: str) -> JSONResponse:
    body = ErrorResponse(code=code, message=message).model_dump(by_alias=True)
    return JSONResponse(status_code=status_code, content=body)


def bearer_auth(expected_token: str) -> AuthDependency:
    scheme = HTTPBearer(auto_error=False)

    async def authenticate(
        credentials: HTTPAuthorizationCredentials | None = Depends(scheme),  # noqa: B008
    ) -> str:
        if credentials is None or not compare_digest(credentials.credentials, expected_token):
            # Authentication intentionally returns the public Error schema rather
            # than FastAPI's default {"detail": ...} wrapper.
            from fastapi import HTTPException

            raise HTTPException(status_code=401, detail="invalid bearer token")
        return "local-tenant"

    return authenticate


def create_task_router(
    service: TaskLifecycleService,
    *,
    expected_bearer_token: str = "local-demo-token",
) -> APIRouter:
    router = APIRouter(prefix="/v1/tasks", tags=["tasks"])
    authenticate = bearer_auth(expected_bearer_token)

    @router.post(
        "",
        response_model=TaskResponse,
        status_code=status.HTTP_202_ACCEPTED,
        operation_id="createTask",
        responses={
            400: {"model": ErrorResponse, "description": "Invalid request"},
            409: {"model": ErrorResponse, "description": "Idempotency conflict"},
        },
    )
    async def create_task(
        request: CreateTaskRequest,
        idempotency_key: str = Header(
            alias="Idempotency-Key",
            min_length=8,
            max_length=128,
        ),
        tenant_id: str = Depends(authenticate),
    ) -> TaskResponse | JSONResponse:
        try:
            record = await service.create_task(
                request.to_spec(),
                idempotency_key=idempotency_key,
                tenant_id=tenant_id,
            )
        except IdempotencyConflict as exc:
            return _error(409, code="IDEMPOTENCY_CONFLICT", message=str(exc))
        return TaskResponse.from_record(record)

    @router.get(
        "/{taskId}",
        response_model=TaskResponse,
        operation_id="getTask",
        responses={404: {"model": ErrorResponse, "description": "Task not found"}},
    )
    async def get_task(
        taskId: str,
        _tenant_id: str = Depends(authenticate),
    ) -> TaskResponse | JSONResponse:
        if not taskId.startswith("task_"):
            return _error(404, code="TASK_NOT_FOUND", message="task not found")
        try:
            record = await service.get_task_for_tenant(taskId, tenant_id=_tenant_id)
        except TaskNotFound:
            return _error(404, code="TASK_NOT_FOUND", message="task not found")
        return TaskResponse.from_record(record)

    @router.post(
        "/{taskId}/cancel",
        response_model=TaskResponse,
        status_code=status.HTTP_202_ACCEPTED,
        operation_id="cancelTask",
        responses={404: {"model": ErrorResponse, "description": "Task not found"}},
    )
    async def cancel_task(
        taskId: str,
        _tenant_id: str = Depends(authenticate),
    ) -> TaskResponse | JSONResponse:
        if not taskId.startswith("task_"):
            return _error(404, code="TASK_NOT_FOUND", message="task not found")
        try:
            record = await service.cancel_task(taskId, tenant_id=_tenant_id)
        except TaskNotFound:
            return _error(404, code="TASK_NOT_FOUND", message="task not found")
        return TaskResponse.from_record(record)

    return router


def install_task_api(
    app: FastAPI,
    service: TaskLifecycleService,
    *,
    expected_bearer_token: str = "local-demo-token",
) -> None:
    """Install routes and map request validation to the documented 400 schema."""

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request,
        _exc: RequestValidationError,
    ) -> JSONResponse:
        return _error(400, code="INVALID_REQUEST", message="request validation failed")

    app.include_router(create_task_router(service, expected_bearer_token=expected_bearer_token))
