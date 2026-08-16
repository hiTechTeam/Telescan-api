from datetime import UTC, datetime
from uuid import UUID

from src.domain.enums import ReportReason, ReportStatus
from src.domain.errors import (
    InvalidModerationAction,
    ModerationItemNotFound,
    UserNotFound,
)
from src.domain.ports import (
    BlockRepositoryPort,
    ReportRepositoryPort,
    UserRepositoryPort,
)


class SubmitReport:
    def __init__(
        self,
        users: UserRepositoryPort,
        reports: ReportRepositoryPort,
    ) -> None:
        self._users = users
        self._reports = reports

    async def execute(
        self,
        reporter_id: str,
        target_telescan_id: UUID,
        client_request_id: UUID,
        reason: ReportReason,
        details: str | None,
    ) -> object:
        reporter = await self._users.get_by_id(reporter_id)
        target = await self._users.get_by_telescan_id(target_telescan_id)
        if reporter is None or target is None:
            raise UserNotFound()
        if str(getattr(reporter, "id")) == str(getattr(target, "id")):
            raise InvalidModerationAction("You cannot report your own profile")

        normalized_details = details.strip() if details else None
        return await self._reports.create(
            reporter,
            target,
            client_request_id,
            reason,
            normalized_details or None,
            datetime.now(UTC),
        )


class BlockUser:
    def __init__(
        self,
        users: UserRepositoryPort,
        blocks: BlockRepositoryPort,
    ) -> None:
        self._users = users
        self._blocks = blocks

    async def execute(self, blocker_id: str, target_telescan_id: UUID) -> object:
        target = await self._users.get_by_telescan_id(target_telescan_id)
        if target is None:
            raise UserNotFound()
        if blocker_id == str(getattr(target, "id")):
            raise InvalidModerationAction("You cannot block your own profile")
        return await self._blocks.create(blocker_id, target, datetime.now(UTC))


class UnblockUser:
    def __init__(self, blocks: BlockRepositoryPort) -> None:
        self._blocks = blocks

    async def execute(self, blocker_id: str, target_telescan_id: UUID) -> None:
        await self._blocks.delete(blocker_id, target_telescan_id)


class ListBlockedUsers:
    def __init__(self, blocks: BlockRepositoryPort) -> None:
        self._blocks = blocks

    async def execute(self, blocker_id: str) -> list[object]:
        return await self._blocks.list_for_user(blocker_id)


class ListReports:
    def __init__(self, reports: ReportRepositoryPort) -> None:
        self._reports = reports

    async def execute(
        self,
        status: ReportStatus | None,
        limit: int,
    ) -> list[object]:
        return await self._reports.list_by_status(status, limit)


class GetReport:
    def __init__(self, reports: ReportRepositoryPort) -> None:
        self._reports = reports

    async def execute(self, report_id: UUID) -> object:
        report = await self._reports.get_by_public_id(report_id)
        if report is None:
            raise ModerationItemNotFound()
        return report


class UpdateReportStatus:
    def __init__(self, reports: ReportRepositoryPort) -> None:
        self._reports = reports

    async def execute(
        self,
        report_id: UUID,
        status: ReportStatus,
        moderator_id: str,
        note: str | None,
    ) -> object:
        if status == ReportStatus.PENDING:
            raise InvalidModerationAction(
                "A moderation decision cannot restore pending"
            )
        normalized_note = note.strip() if note else None
        report = await self._reports.update_status(
            report_id,
            status,
            moderator_id,
            normalized_note or None,
            datetime.now(UTC),
        )
        if report is None:
            raise ModerationItemNotFound()
        return report
