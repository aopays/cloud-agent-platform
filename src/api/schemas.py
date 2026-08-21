"""Pydantic transport models matching the public OpenAPI contract."""

from __future__ import annotations

from datetime import datetime

from pydantic import AnyUrl, BaseModel, ConfigDict, Field, field_validator

from src.models.tasks import TaskRecord
from src.shared.contracts import BudgetLimits, RepositorySpec, TaskSpec, TaskStatus


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class RepositoryInput(StrictModel):
    url: AnyUrl
    ref: str | None = Field(default=None, max_length=256)


class TaskLimitsInput(StrictModel):
    wall_time_seconds: int = Field(default=900, alias="wallTimeSeconds", ge=10, le=3600)
    max_agent_turns: int = Field(default=30, alias="maxAgentTurns", ge=1, le=100)
    max_input_tokens: int = Field(
        default=1_000_000,
        alias="maxInputTokens",
        ge=1_000,
        le=1_000_000,
    )


class CreateTaskRequest(StrictModel):
    instruction: str = Field(min_length=1, max_length=20_000)
    repository: RepositoryInput
    limits: TaskLimitsInput = Field(default_factory=TaskLimitsInput)

    @field_validator("instruction")
    @classmethod
    def instruction_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("instruction must not be blank")
        return value

    def to_spec(self) -> TaskSpec:
        return TaskSpec(
            instruction=self.instruction,
            repository=RepositorySpec(url=str(self.repository.url), ref=self.repository.ref),
            limits=BudgetLimits(
                wall_time_seconds=self.limits.wall_time_seconds,
                max_agent_turns=self.limits.max_agent_turns,
                max_input_tokens=self.limits.max_input_tokens,
            ),
        )


class ErrorResponse(BaseModel):
    code: str
    message: str
    retryable: bool = False


class UsageResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    agent_turns: int = Field(alias="agentTurns", ge=0)
    input_tokens: int = Field(alias="inputTokens", ge=0)
    output_tokens: int = Field(alias="outputTokens", ge=0)
    wall_time_seconds: float = Field(alias="wallTimeSeconds", ge=0)


class TaskResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    status: TaskStatus
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    started_at: datetime | None = Field(default=None, alias="startedAt")
    finished_at: datetime | None = Field(default=None, alias="finishedAt")
    result: str | None = None
    error: ErrorResponse | None = None
    usage: UsageResponse

    @classmethod
    def from_record(cls, record: TaskRecord) -> TaskResponse:
        error = None
        if record.error is not None:
            error = ErrorResponse(
                code=record.error.code,
                message=record.error.message,
                retryable=record.error.retryable,
            )
        return cls(
            id=record.task_id,
            status=record.status,
            createdAt=record.created_at,
            updatedAt=record.updated_at,
            startedAt=record.started_at,
            finishedAt=record.finished_at,
            result=record.result,
            error=error,
            usage=UsageResponse(
                agentTurns=record.usage.agent_turns,
                inputTokens=record.usage.input_tokens,
                outputTokens=record.usage.output_tokens,
                wallTimeSeconds=record.usage.wall_time_seconds,
            ),
        )
