from datetime import UTC, datetime
from uuid import uuid4

import pytest

from src.domain.enums import ReportReason, ReportStatus
from src.domain.errors import (
    InvalidModerationAction,
    ModerationItemNotFound,
    UserNotFound,
)
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
from tests.fakes import FakeBlocks, FakeReports, FakeUsers


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
    assert first.target_photo_url == target.photo_s3_link
    assert first.status == ReportStatus.PENDING


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

    await UnblockUser(blocks).execute(str(first.id), second.telescan_id)
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
    assert updated.moderator_note == "confirmed"
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
