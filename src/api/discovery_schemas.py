"""Transport schemas for multi-turn requirement discovery."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.discovery import DiscoverySession, DiscoveryStatus


class DiscoveryStrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class CreateDiscoverySessionRequest(DiscoveryStrictModel):
    requirement: str = Field(min_length=1, max_length=20_000)
    context: str | None = Field(default=None, max_length=20_000)

    @field_validator("requirement")
    @classmethod
    def requirement_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("requirement must not be blank")
        return value.strip()

    @field_validator("context")
    @classmethod
    def context_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class AddDiscoveryMessageRequest(DiscoveryStrictModel):
    content: str = Field(min_length=1, max_length=20_000)

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must not be blank")
        return value.strip()


class DiscoveryMessageResponse(BaseModel):
    sequence: int = Field(ge=1)
    role: str
    content: str
    created_at: datetime = Field(alias="createdAt")


class DiscoveryArtifactResponse(BaseModel):
    id: str
    name: str
    media_type: str = Field(alias="mediaType")
    size_bytes: int = Field(alias="sizeBytes", ge=0)
    download_url: str = Field(alias="downloadUrl")


class DiscoverySessionResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    status: DiscoveryStatus
    initial_requirement: str = Field(alias="initialRequirement")
    context: str | None = None
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    current_round: int = Field(alias="currentRound", ge=0)
    recommended_rounds: int = Field(default=3, alias="recommendedRounds")
    can_finalize: bool = Field(alias="canFinalize")
    messages: list[DiscoveryMessageResponse]
    report: str | None = None
    artifact: DiscoveryArtifactResponse | None = None

    @classmethod
    def from_session(
        cls,
        session: DiscoverySession,
        *,
        download_url: str | None = None,
    ) -> DiscoverySessionResponse:
        artifact = None
        if session.report_artifact is not None and download_url is not None:
            artifact = DiscoveryArtifactResponse(
                id=session.report_artifact.artifact_id,
                name=session.report_artifact.name,
                mediaType=session.report_artifact.media_type,
                sizeBytes=session.report_artifact.size_bytes,
                downloadUrl=download_url,
            )
        return cls(
            id=session.session_id,
            status=session.status,
            initialRequirement=session.initial_requirement,
            context=session.context,
            createdAt=session.created_at,
            updatedAt=session.updated_at,
            currentRound=session.user_rounds,
            recommendedRounds=3,
            canFinalize=session.status is not DiscoveryStatus.FINALIZED,
            messages=[
                DiscoveryMessageResponse(
                    sequence=message.sequence,
                    role=message.role,
                    content=message.content,
                    createdAt=message.created_at,
                )
                for message in session.messages
            ],
            report=session.report,
            artifact=artifact,
        )
