from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from src.dependencies.container import Container, get_container
from src.dependencies.moderation import require_moderation_service
from src.domain.enums import ReportPhotoEvidenceStatus, ReportStatus
from src.schemas.moderation import (
    ModerationDecisionRequest,
    ModerationReportResponse,
)

router = APIRouter(
    prefix="/internal/v1/moderation",
    tags=["internal-moderation"],
    dependencies=[Depends(require_moderation_service)],
)


def _report(item: object) -> ModerationReportResponse:
    return ModerationReportResponse(
        report_id=getattr(item, "public_id"),
        reporter_telescan_id=getattr(item, "reporter_telescan_id", None),
        target_telescan_id=getattr(item, "target_telescan_id"),
        reason=getattr(item, "reason"),
        details=getattr(item, "details", None),
        target_name=getattr(item, "target_name", None),
        target_username=getattr(item, "target_username", None),
        target_bio=getattr(item, "target_bio", None),
        target_photo_url=getattr(item, "target_photo_url", None),
        target_photo_evidence_status=getattr(
            item,
            "target_photo_evidence_status",
            ReportPhotoEvidenceStatus.ABSENT,
        ),
        status=getattr(item, "status"),
        created_at=getattr(item, "created_at"),
        updated_at=getattr(item, "updated_at"),
        resolved_at=getattr(item, "resolved_at", None),
        retention_until=getattr(item, "retention_until", None),
        moderator_id=getattr(item, "moderator_id", None),
        moderator_note=getattr(item, "moderator_note", None),
        revision=getattr(item, "revision", 0),
        moderation_history=getattr(item, "moderation_history", []),
    )


@router.get("/reports", response_model=list[ModerationReportResponse])
async def list_reports(
    container: Annotated[Container, Depends(get_container)],
    report_status: Annotated[ReportStatus | None, Query(alias="status")] = (
        ReportStatus.PENDING
    ),
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[ModerationReportResponse]:
    reports = await container.list_reports.execute(report_status, limit)
    return [_report(item) for item in reports]


@router.get("/reports/{report_id}", response_model=ModerationReportResponse)
async def get_report(
    report_id: UUID,
    container: Annotated[Container, Depends(get_container)],
) -> ModerationReportResponse:
    return _report(await container.get_report.execute(report_id))


@router.patch("/reports/{report_id}", response_model=ModerationReportResponse)
async def update_report(
    report_id: UUID,
    payload: ModerationDecisionRequest,
    container: Annotated[Container, Depends(get_container)],
) -> ModerationReportResponse:
    item = await container.update_report_status.execute(
        report_id,
        payload.status,
        payload.moderator_id,
        payload.note,
        note_is_set="note" in payload.model_fields_set,
        expected_revision=payload.revision,
    )
    return _report(item)
