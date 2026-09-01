from datetime import UTC, datetime
from uuid import UUID

from src.domain.enums import ReportReason, ReportStatus
from src.domain.errors import (
    InvalidModerationAction,
    ModerationConflict,
    ModerationItemNotFound,
    UserNotFound,
)
from src.domain.ports import (
    BlockRepositoryPort,
    ReportRepositoryPort,
    UserRepositoryPort,
)
from src.services.report_evidence import ReportEvidenceService
from src.services.account_operations import AccountOperationGuard


class SubmitReport:
    def __init__(
        self,
        users: UserRepositoryPort,
        reports: ReportRepositoryPort,
        evidence: ReportEvidenceService | None = None,
        account_operations: AccountOperationGuard | None = None,
    ) -> None:
        self._users = users
        self._reports = reports
        self._evidence = evidence
        self._account_operations = account_operations

    async def execute(
        self,
        reporter_id: str,
        target_telescan_id: UUID,
        client_request_id: UUID,
        details: str | None,
    ) -> object:
        reporter = await self._users.get_by_id(reporter_id)
        target = await self._users.get_by_telescan_id(target_telescan_id)
        if reporter is None or target is None:
            raise UserNotFound()
        if str(getattr(reporter, "id")) == str(getattr(target, "id")):
            raise InvalidModerationAction("You cannot report your own profile")

        normalized_details = details.strip() if details else None
        if self._account_operations is None:
            return await self._create_locked(
                reporter_id,
                target_telescan_id,
                client_request_id,
                normalized_details,
            )
        else:
            async with self._account_operations.admit_many(
                [reporter_id, str(getattr(target, "id"))]
            ):
                return await self._create_locked(
                    reporter_id,
                    target_telescan_id,
                    client_request_id,
                    normalized_details,
                )

    async def _create_locked(
        self,
        reporter_id: str,
        target_telescan_id: UUID,
        client_request_id: UUID,
        normalized_details: str | None,
    ) -> object:
        reporter = await self._users.get_by_id(reporter_id)
        target = await self._users.get_by_telescan_id(target_telescan_id)
        if reporter is None or target is None:
            raise UserNotFound()
        if str(getattr(reporter, "id")) == str(getattr(target, "id")):
            raise InvalidModerationAction("You cannot report your own profile")
        report = await self._reports.create(
            reporter,
            target,
            client_request_id,
            ReportReason.OTHER,
            normalized_details or None,
            datetime.now(UTC),
        )
        if self._evidence is not None:
            report = await self._evidence.capture(report)
        return report


class BlockUser:
    def __init__(
        self,
        users: UserRepositoryPort,
        blocks: BlockRepositoryPort,
        account_operations: AccountOperationGuard | None = None,
    ) -> None:
        self._users = users
        self._blocks = blocks
        self._account_operations = account_operations

    async def execute(self, blocker_id: str, target_telescan_id: UUID) -> object:
        target = await self._users.get_by_telescan_id(target_telescan_id)
        if target is None:
            raise UserNotFound()
        if blocker_id == str(getattr(target, "id")):
            raise InvalidModerationAction("You cannot block your own profile")
        if self._account_operations is None:
            return await self._create_locked(blocker_id, target_telescan_id)
        async with self._account_operations.admit_many(
            [blocker_id, str(getattr(target, "id"))]
        ):
            return await self._create_locked(blocker_id, target_telescan_id)

    async def _create_locked(self, blocker_id: str, target_telescan_id: UUID) -> object:
        target = await self._users.get_by_telescan_id(target_telescan_id)
        if target is None:
            raise UserNotFound()
        if blocker_id == str(getattr(target, "id")):
            raise InvalidModerationAction("You cannot block your own profile")
        return await self._blocks.create(blocker_id, target, datetime.now(UTC))


class UnblockUser:
    def __init__(
        self,
        users: UserRepositoryPort,
        blocks: BlockRepositoryPort,
        account_operations: AccountOperationGuard | None = None,
    ) -> None:
        self._users = users
        self._blocks = blocks
        self._account_operations = account_operations

    async def execute(self, blocker_id: str, target_telescan_id: UUID) -> None:
        target = await self._users.get_by_telescan_id(target_telescan_id)
        if target is None:
            raise UserNotFound()
        target_id = str(getattr(target, "id"))
        if self._account_operations is None:
            await self._delete_locked(blocker_id, target_telescan_id, target_id)
            return
        async with self._account_operations.admit_many([blocker_id, target_id]):
            await self._delete_locked(blocker_id, target_telescan_id, target_id)

    async def _delete_locked(
        self, blocker_id: str, target_telescan_id: UUID, expected_target_id: str
    ) -> None:
        target = await self._users.get_by_telescan_id(target_telescan_id)
        if target is None or str(getattr(target, "id")) != expected_target_id:
            raise UserNotFound()
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
    def __init__(
        self,
        reports: ReportRepositoryPort,
        revision_required: bool = False,
    ) -> None:
        self._reports = reports
        self._revision_required = revision_required

    async def execute(
        self,
        report_id: UUID,
        status: ReportStatus,
        moderator_id: str,
        note: str | None = None,
        *,
        note_is_set: bool = True,
        expected_revision: int | None = None,
    ) -> object:
        if status == ReportStatus.PENDING:
            raise InvalidModerationAction(
                "A moderation decision cannot restore pending"
            )
        if self._revision_required and expected_revision is None:
            raise ModerationConflict()
        current = await self._reports.get_by_public_id(report_id)
        if current is None:
            raise ModerationItemNotFound()
        current_status = getattr(current, "status")
        if current_status in {ReportStatus.RESOLVED, ReportStatus.DISMISSED}:
            raise InvalidModerationAction("A closed report is terminal")
        allowed_transitions = {
            ReportStatus.PENDING: {
                ReportStatus.REVIEWING,
                ReportStatus.RESOLVED,
                ReportStatus.DISMISSED,
            },
            ReportStatus.REVIEWING: {
                ReportStatus.RESOLVED,
                ReportStatus.DISMISSED,
            },
        }
        if status not in allowed_transitions.get(current_status, set()):
            raise InvalidModerationAction("Invalid moderation status transition")
        current_revision = int(getattr(current, "revision", 0))
        if expected_revision is not None and expected_revision != current_revision:
            raise ModerationConflict()
        report = await self._reports.update_status(
            report_id,
            status,
            moderator_id,
            note,
            note_is_set,
            current_revision,
            datetime.now(UTC),
        )
        if report is None:
            if await self._reports.get_by_public_id(report_id) is None:
                raise ModerationItemNotFound()
            raise ModerationConflict()
        return report
