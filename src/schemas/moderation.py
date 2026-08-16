from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.domain.enums import ReportReason, ReportStatus


class ReportCreateRequest(BaseModel):
    client_request_id: Annotated[UUID, Field(alias="clientRequestId")]
    target_telescan_id: Annotated[UUID, Field(alias="targetTelescanId")]
    reason: ReportReason
    details: Annotated[str | None, Field(max_length=500)] = None
    model_config = ConfigDict(populate_by_name=True)


class ReportResponse(BaseModel):
    report_id: Annotated[UUID, Field(alias="reportId")]
    status: ReportStatus
    created_at: Annotated[datetime, Field(alias="createdAt")]
    model_config = ConfigDict(populate_by_name=True)


class BlockedProfileResponse(BaseModel):
    telescan_id: Annotated[UUID, Field(alias="telescanId")]
    name: str | None = None
    username: str | None = None
    photo_url: Annotated[str | None, Field(alias="photoUrl")] = None
    blocked_at: Annotated[datetime, Field(alias="blockedAt")]
    model_config = ConfigDict(populate_by_name=True)


class ModerationReportResponse(BaseModel):
    report_id: Annotated[UUID, Field(alias="reportId")]
    reporter_telescan_id: Annotated[UUID | None, Field(alias="reporterTelescanId")] = (
        None
    )
    target_telescan_id: Annotated[UUID, Field(alias="targetTelescanId")]
    reason: ReportReason
    details: str | None = None
    target_name: Annotated[str | None, Field(alias="targetName")] = None
    target_username: Annotated[str | None, Field(alias="targetUsername")] = None
    target_photo_url: Annotated[str | None, Field(alias="targetPhotoUrl")] = None
    status: ReportStatus
    created_at: Annotated[datetime, Field(alias="createdAt")]
    updated_at: Annotated[datetime, Field(alias="updatedAt")]
    resolved_at: Annotated[datetime | None, Field(alias="resolvedAt")] = None
    retention_until: Annotated[datetime | None, Field(alias="retentionUntil")] = None
    moderator_id: Annotated[str | None, Field(alias="moderatorId")] = None
    moderator_note: Annotated[str | None, Field(alias="moderatorNote")] = None
    model_config = ConfigDict(populate_by_name=True)


class ModerationDecisionRequest(BaseModel):
    status: ReportStatus
    moderator_id: Annotated[
        str, Field(alias="moderatorId", min_length=1, max_length=100)
    ]
    note: Annotated[str | None, Field(max_length=1000)] = None
    model_config = ConfigDict(populate_by_name=True)
