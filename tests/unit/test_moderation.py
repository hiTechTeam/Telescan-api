import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from scripts.evidence_worker_gate import disable, enable, marker_is_safe
from src.core.config import Settings
from src.domain.enums import ReportPhotoEvidenceStatus, ReportReason, ReportStatus
from src.domain.errors import (
    InvalidModerationAction,
    ModerationConflict,
    ModerationItemNotFound,
    UserNotFound,
)
from src.services.photos import PhotoService
from src.services.report_evidence import ReportEvidenceService
from src.use_cases.moderation import (
    BlockUser,
    GetReport,
    ListBlockedUsers,
    ListReports,
    SubmitReport,
    UnblockUser,
    UpdateReportStatus,
)
from src.use_cases.profiles import GetPublicProfile
from tests.fakes import FakeBlocks, FakeReports, FakeStorage, FakeUsers


@pytest.mark.asyncio
async def test_report_captures_snapshot_and_deduplicates_only_same_request() -> None:
    users = FakeUsers()
    reporter = await users.upsert_telegram_profile(1, "Reporter", "reporter")
    target = await users.upsert_telegram_profile(2, "Target", "target")
    target.bio = "  Building privacy-friendly proximity tools  "
    target.photo_s3_link = "https://storage.example/target.jpg"
    reports = FakeReports()
    submit = SubmitReport(users, reports)

    request_id = uuid4()
    first = await submit.execute(
        str(reporter.id),
        target.telescan_id,
        request_id,
        "  repeated unwanted contact  ",
    )
    retried = await submit.execute(
        str(reporter.id),
        target.telescan_id,
        request_id,
        None,
    )
    repeated = await submit.execute(
        str(reporter.id), target.telescan_id, uuid4(), "new context"
    )

    assert retried.public_id == first.public_id
    assert repeated.public_id != first.public_id
    assert repeated.details == "new context"
    assert first.reason == ReportReason.OTHER
    assert first.details == "repeated unwanted contact"
    assert first.reporter_telescan_id == reporter.telescan_id
    assert first.target_telescan_id == target.telescan_id
    assert first.target_name == "Target"
    assert first.target_username == "target"
    assert first.target_bio == target.bio
    assert first.target_photo_url is None
    assert first.target_photo_source_url == target.photo_s3_link
    assert first.target_photo_evidence_status == ReportPhotoEvidenceStatus.COPY_FAILED
    assert first.status == ReportStatus.PENDING


@pytest.mark.asyncio
async def test_report_photo_is_copied_to_durable_moderation_evidence() -> None:
    users = FakeUsers()
    reporter = await users.upsert_telegram_profile(1, "Reporter", "reporter")
    target = await users.upsert_telegram_profile(2, "Target", "target")
    target.photo_s3_link = "https://storage.example/users/target/live.jpg"
    reports = FakeReports()
    storage = FakeStorage()
    evidence = ReportEvidenceService(reports, PhotoService(storage, 1024))

    report = await SubmitReport(users, reports, evidence).execute(
        str(reporter.id), target.telescan_id, uuid4(), None
    )

    assert report.target_photo_evidence_status == ReportPhotoEvidenceStatus.AVAILABLE
    assert report.target_photo_url.endswith(
        f"moderation/reports/{report.public_id}/evidence.jpg"
    )
    assert any(
        name.startswith(f"moderation/reports/{report.public_id}/evidence")
        for name in storage.uploaded
    )
    await storage.delete_by_url(target.photo_s3_link)
    assert report.target_photo_url not in storage.deleted


@pytest.mark.asyncio
async def test_failed_evidence_copy_is_explicit_and_retryable() -> None:
    class FailingOnceStorage(FakeStorage):
        def __init__(self) -> None:
            super().__init__()
            self.fail = True

        async def copy_by_url(self, source_url, object_name):
            if self.fail:
                self.fail = False
                raise OSError("storage unavailable")
            return await super().copy_by_url(source_url, object_name)

    users = FakeUsers()
    reporter = await users.upsert_telegram_profile(1, "Reporter", "reporter")
    target = await users.upsert_telegram_profile(2, "Target", "target")
    target.photo_s3_link = "https://storage.example/users/target/live.jpg"
    reports = FakeReports()
    storage = FailingOnceStorage()
    evidence = ReportEvidenceService(reports, PhotoService(storage, 1024))

    report = await SubmitReport(users, reports, evidence).execute(
        str(reporter.id), target.telescan_id, uuid4(), None
    )
    assert report.target_photo_evidence_status == ReportPhotoEvidenceStatus.COPY_FAILED
    assert report.target_photo_evidence_attempts == 1

    await evidence.run_once()

    assert report.target_photo_evidence_status == ReportPhotoEvidenceStatus.AVAILABLE
    assert report.target_photo_url is not None


@pytest.mark.asyncio
async def test_evidence_worker_waits_for_durable_release_commit(tmp_path) -> None:
    marker = tmp_path / "evidence-worker.enabled"
    users = FakeUsers()
    reporter = await users.upsert_telegram_profile(1, "Reporter", "reporter")
    target = await users.upsert_telegram_profile(2, "Target", "target")
    target.photo_s3_link = "https://storage.example/users/target/live.jpg"
    reports = FakeReports()
    storage = FakeStorage()
    evidence = ReportEvidenceService(
        reports,
        PhotoService(storage, 1024),
        marker,
    )

    report = await SubmitReport(users, reports, evidence).execute(
        str(reporter.id), target.telescan_id, uuid4(), None
    )
    assert report.target_photo_evidence_status == ReportPhotoEvidenceStatus.COPY_FAILED
    assert storage.uploaded == {}

    enable(marker)
    assert marker_is_safe(marker) is True
    await evidence.run_once()
    assert report.target_photo_evidence_status == ReportPhotoEvidenceStatus.AVAILABLE

    disable(marker)
    assert marker.exists() is False


@pytest.mark.asyncio
async def test_unknown_evidence_attach_outcome_is_read_back_without_deleting() -> None:
    class FailingAttachReports(FakeReports):
        async def update_photo_evidence(self, report_id, evidence_url, now):
            await super().update_photo_evidence(report_id, evidence_url, now)
            raise OSError("Mongo response was lost after commit")

    users = FakeUsers()
    reporter = await users.upsert_telegram_profile(1, "Reporter", "reporter")
    target = await users.upsert_telegram_profile(2, "Target", "target")
    target.photo_s3_link = "https://storage.example/users/target/live.jpg"
    reports = FailingAttachReports()
    storage = FakeStorage()
    evidence = ReportEvidenceService(reports, PhotoService(storage, 1024))
    report = await SubmitReport(users, reports).execute(
        str(reporter.id), target.telescan_id, uuid4(), None
    )
    result = await evidence.capture(report)

    deterministic_url = (
        f"https://storage.example/moderation/reports/{report.public_id}/evidence.jpg"
    )
    assert result.target_photo_evidence_status == ReportPhotoEvidenceStatus.AVAILABLE
    assert result.target_photo_url == deterministic_url
    assert deterministic_url not in storage.deleted
    assert f"moderation/reports/{report.public_id}/" not in storage.deleted
    assert report.public_id in reports.items


@pytest.mark.asyncio
async def test_concurrent_evidence_capture_serializes_same_report() -> None:
    class BlockingStorage(FakeStorage):
        def __init__(self) -> None:
            super().__init__()
            self.copy_started = asyncio.Event()
            self.allow_copy = asyncio.Event()
            self.copy_count = 0

        async def copy_by_url(self, source_url, object_name):
            self.copy_count += 1
            self.copy_started.set()
            await self.allow_copy.wait()
            return await super().copy_by_url(source_url, object_name)

    users = FakeUsers()
    reporter = await users.upsert_telegram_profile(1, "Reporter", "reporter")
    target = await users.upsert_telegram_profile(2, "Target", "target")
    target.photo_s3_link = "https://storage.example/users/target/live.jpg"
    reports = FakeReports()
    storage = BlockingStorage()
    evidence = ReportEvidenceService(reports, PhotoService(storage, 1024))
    report = await SubmitReport(users, reports).execute(
        str(reporter.id), target.telescan_id, uuid4(), None
    )

    first = asyncio.create_task(evidence.capture(report))
    await storage.copy_started.wait()
    second = asyncio.create_task(evidence.capture(report))
    await asyncio.sleep(0)
    storage.allow_copy.set()
    first_result, second_result = await asyncio.gather(first, second)

    assert storage.copy_count == 1
    assert (
        first_result.target_photo_evidence_status == ReportPhotoEvidenceStatus.AVAILABLE
    )
    assert (
        second_result.target_photo_evidence_status
        == ReportPhotoEvidenceStatus.AVAILABLE
    )
    assert storage.deleted == []


@pytest.mark.asyncio
async def test_due_copy_failed_report_deletes_deterministic_prefix_and_record() -> None:
    class SourceGoneStorage(FakeStorage):
        async def copy_by_url(self, source_url, object_name):
            raise FileNotFoundError("live profile photo was already removed")

    users = FakeUsers()
    reporter = await users.upsert_telegram_profile(1, "Reporter", "reporter")
    target = await users.upsert_telegram_profile(2, "Target", "target")
    target.photo_s3_link = "https://storage.example/users/target/live.jpg"
    reports = FakeReports()
    storage = SourceGoneStorage()
    evidence = ReportEvidenceService(reports, PhotoService(storage, 1024))
    report = await SubmitReport(users, reports).execute(
        str(reporter.id), target.telescan_id, uuid4(), None
    )
    report.status = ReportStatus.RESOLVED
    report.retention_until = datetime.now(UTC) - timedelta(seconds=1)
    deterministic_key = f"moderation/reports/{report.public_id}/evidence.jpg"
    storage.uploaded[deterministic_key] = b"orphaned-before-unknown-CAS"

    await evidence.run_once()

    assert report.public_id not in reports.items
    assert f"moderation/reports/{report.public_id}/" in storage.deleted
    assert deterministic_key not in storage.uploaded


@pytest.mark.asyncio
async def test_self_report_and_self_block_are_rejected() -> None:
    users = FakeUsers()
    user = await users.upsert_telegram_profile(1, "Ada", "ada")

    with pytest.raises(InvalidModerationAction):
        await SubmitReport(users, FakeReports()).execute(
            str(user.id),
            user.telescan_id,
            uuid4(),
            None,
        )
    with pytest.raises(InvalidModerationAction):
        await BlockUser(users, FakeBlocks()).execute(str(user.id), user.telescan_id)


@pytest.mark.asyncio
async def test_block_hides_profiles_in_both_directions_and_can_be_removed() -> None:
    users = FakeUsers()
    first = await users.upsert_telegram_profile(1, "First", "first")
    second = await users.upsert_telegram_profile(2, "Second", "second")
    blocks = FakeBlocks()
    block = BlockUser(users, blocks)
    profiles = GetPublicProfile(users, blocks)

    created = await block.execute(str(first.id), second.telescan_id)
    assert created.blocked_telescan_id == second.telescan_id
    assert len(await ListBlockedUsers(blocks).execute(str(first.id))) == 1

    with pytest.raises(UserNotFound):
        await profiles.execute(str(first.id), second.telescan_id)
    with pytest.raises(UserNotFound):
        await profiles.execute(str(second.id), first.telescan_id)

    await UnblockUser(users, blocks).execute(str(first.id), second.telescan_id)
    assert await profiles.execute(str(first.id), second.telescan_id) is second


@pytest.mark.asyncio
async def test_internal_report_review_flow_records_actor_and_note() -> None:
    users = FakeUsers()
    reporter = await users.upsert_telegram_profile(1, "Reporter", "reporter")
    target = await users.upsert_telegram_profile(2, "Target", "target")
    reports = FakeReports()
    item = await SubmitReport(users, reports).execute(
        str(reporter.id),
        target.telescan_id,
        uuid4(),
        None,
    )

    pending = await ListReports(reports).execute(ReportStatus.PENDING, 50)
    assert [report.public_id for report in pending] == [item.public_id]
    updated = await UpdateReportStatus(reports).execute(
        item.public_id,
        ReportStatus.RESOLVED,
        "telegram:12345",
        "  confirmed  ",
    )
    assert updated.status == ReportStatus.RESOLVED
    assert updated.moderator_id == "telegram:12345"
    assert updated.moderator_note == "  confirmed  "
    assert updated.resolved_at is not None
    assert updated.retention_until > updated.resolved_at
    assert await GetReport(reports).execute(item.public_id) is updated

    with pytest.raises(InvalidModerationAction):
        await UpdateReportStatus(reports).execute(
            item.public_id,
            ReportStatus.PENDING,
            "telegram:12345",
            None,
        )
    with pytest.raises(ModerationItemNotFound):
        await GetReport(reports).execute(uuid4())


@pytest.mark.asyncio
async def test_moderation_note_tristate_revision_cas_and_terminal_state() -> None:
    users = FakeUsers()
    reporter = await users.upsert_telegram_profile(1, "Reporter", "reporter")
    target = await users.upsert_telegram_profile(2, "Target", "target")
    reports = FakeReports()
    report = await SubmitReport(users, reports).execute(
        str(reporter.id), target.telescan_id, uuid4(), None
    )
    update = UpdateReportStatus(reports)

    reviewing = await update.execute(
        report.public_id,
        ReportStatus.REVIEWING,
        "telegram:1",
        "investigating",
        expected_revision=0,
    )
    assert reviewing.revision == 1
    assert reviewing.moderator_note == "investigating"
    assert reviewing.moderation_history[-1].note_changed is True

    with pytest.raises(ModerationConflict):
        await update.execute(
            report.public_id,
            ReportStatus.RESOLVED,
            "telegram:2",
            expected_revision=0,
        )

    resolved = await update.execute(
        report.public_id,
        ReportStatus.RESOLVED,
        "telegram:2",
        note_is_set=False,
        expected_revision=1,
    )
    assert resolved.revision == 2
    assert resolved.moderator_note == "investigating"
    assert resolved.moderation_history[-1].note_changed is False
    assert resolved.retention_until - resolved.resolved_at >= timedelta(days=180)

    with pytest.raises(InvalidModerationAction):
        await update.execute(
            report.public_id,
            ReportStatus.DISMISSED,
            "telegram:2",
            expected_revision=2,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("note", "note_is_set", "expected_note", "note_changed"),
    [
        (None, False, "existing", False),
        (None, True, None, True),
        ("", True, "", True),
        ("   ", True, "   ", True),
    ],
)
async def test_moderation_note_preserves_all_three_wire_states(
    note: str | None,
    note_is_set: bool,
    expected_note: str | None,
    note_changed: bool,
) -> None:
    users = FakeUsers()
    reporter = await users.upsert_telegram_profile(1, "Reporter", "reporter")
    target = await users.upsert_telegram_profile(2, "Target", "target")
    reports = FakeReports()
    report = await SubmitReport(users, reports).execute(
        str(reporter.id), target.telescan_id, uuid4(), None
    )
    report.moderator_note = "existing"

    updated = await UpdateReportStatus(reports).execute(
        report.public_id,
        ReportStatus.REVIEWING,
        "telegram:1",
        note,
        note_is_set=note_is_set,
        expected_revision=0,
    )

    assert updated.moderator_note == expected_note
    assert updated.moderation_history[-1].note_changed is note_changed


@pytest.mark.asyncio
async def test_production_cas_gate_rejects_missing_revision() -> None:
    settings = Settings(
        environment="production",
        mongo_username="app-user",
        mongo_password="mongo-password-that-is-not-a-default",
        mongo_host="mongo",
        mongo_dbname="telescan",
        jwt_secret="jwt-secret-that-is-distinct-and-long",
        link_code_hmac_secret="link-secret-that-is-distinct-and-long",
        review_code_hmac_secret="review-secret-that-is-distinct-long",
        bot_service_secret="bot-secret-that-is-distinct-and-long",
        moderation_service_secret="moderation-secret-that-is-distinct",
        s3_access_key="s3-access-that-is-explicit",
        s3_secret_key="s3-secret-that-is-explicit-and-long",
        s3_public_base_url=(
            "https://profile-photos-telescan.s3.ru-7.storage.selcloud.ru"
        ),
        cors_origins=[],
        require_moderation_revision=True,
    )
    users = FakeUsers()
    reporter = await users.upsert_telegram_profile(1, "Reporter", "reporter")
    target = await users.upsert_telegram_profile(2, "Target", "target")
    reports = FakeReports()
    report = await SubmitReport(users, reports).execute(
        str(reporter.id), target.telescan_id, uuid4(), None
    )

    with pytest.raises(ModerationConflict):
        await UpdateReportStatus(
            reports,
            revision_required=settings.require_moderation_revision,
        ).execute(
            report.public_id,
            ReportStatus.REVIEWING,
            "telegram:1",
        )


@pytest.mark.asyncio
async def test_reviewing_to_reviewing_transition_is_rejected() -> None:
    users = FakeUsers()
    reporter = await users.upsert_telegram_profile(1, "Reporter", "reporter")
    target = await users.upsert_telegram_profile(2, "Target", "target")
    reports = FakeReports()
    report = await SubmitReport(users, reports).execute(
        str(reporter.id), target.telescan_id, uuid4(), None
    )
    update = UpdateReportStatus(reports)
    await update.execute(
        report.public_id,
        ReportStatus.REVIEWING,
        "telegram:1",
        expected_revision=0,
    )

    with pytest.raises(InvalidModerationAction):
        await update.execute(
            report.public_id,
            ReportStatus.REVIEWING,
            "telegram:1",
            expected_revision=1,
        )


@pytest.mark.asyncio
async def test_deleted_account_is_removed_from_blocks_and_anonymized_in_reports() -> (
    None
):
    users = FakeUsers()
    reporter = await users.upsert_telegram_profile(1, "Reporter", "reporter")
    target = await users.upsert_telegram_profile(2, "Target", "target")
    reports = FakeReports()
    blocks = FakeBlocks()
    report = await reports.create(
        reporter,
        target,
        uuid4(),
        ReportReason.OTHER,
        "context",
        datetime.now(UTC),
    )
    await blocks.create(str(reporter.id), target, datetime.now(UTC))

    await reports.anonymize_user(str(reporter.id))
    await blocks.delete_for_user(str(reporter.id))

    assert report.reporter_id is None
    assert report.reporter_telescan_id is None
    assert not blocks.items
