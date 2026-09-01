from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from beanie import PydanticObjectId
from pymongo import DESCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError

from src.domain.enums import ReportPhotoEvidenceStatus, ReportReason, ReportStatus
from src.infrastructure.mongodb.documents import ReportDocument


class ReportRepository:
    async def create(
        self,
        reporter: Any,
        target: Any,
        client_request_id: UUID,
        reason: ReportReason,
        details: str | None,
        now: datetime,
    ) -> ReportDocument:
        reporter_id = PydanticObjectId(str(getattr(reporter, "id")))
        target_id = PydanticObjectId(str(getattr(target, "id")))
        collection = ReportDocument.get_pymongo_collection()
        query = {
            "reporter_id": reporter_id,
            "client_request_id": client_request_id,
        }
        update = {
            "$setOnInsert": {
                "public_id": uuid4(),
                "client_request_id": client_request_id,
                "reporter_id": reporter_id,
                "reporter_telescan_id": getattr(reporter, "telescan_id"),
                "target_id": target_id,
                "target_telescan_id": getattr(target, "telescan_id"),
                "reason": reason,
                "details": details,
                "target_name": getattr(target, "tg_name", None),
                "target_username": getattr(target, "tg_username", None),
                "target_bio": getattr(target, "bio", None),
                "target_photo_url": None,
                "target_photo_source_url": getattr(target, "photo_s3_link", None),
                "target_photo_evidence_status": (
                    ReportPhotoEvidenceStatus.COPY_FAILED
                    if getattr(target, "photo_s3_link", None)
                    else ReportPhotoEvidenceStatus.ABSENT
                ),
                "target_photo_evidence_attempts": 0,
                "status": ReportStatus.PENDING,
                "created_at": now,
                "updated_at": now,
                "resolved_at": None,
                "retention_until": None,
                "moderator_id": None,
                "moderator_note": None,
                "revision": 0,
                "moderation_history": [],
            }
        }
        try:
            raw = await collection.find_one_and_update(
                query,
                update,
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError:
            raw = await collection.find_one(query)
            if raw is None:
                raise
        return ReportDocument.model_validate(raw)

    async def get_by_public_id(self, report_id: UUID) -> ReportDocument | None:
        return await ReportDocument.find_one(ReportDocument.public_id == report_id)

    async def list_by_status(
        self,
        status: ReportStatus | None,
        limit: int,
    ) -> list[ReportDocument]:
        query: dict[str, object] = {}
        if status is not None:
            query["status"] = status
        cursor = (
            ReportDocument.get_pymongo_collection()
            .find(query)
            .sort("created_at", DESCENDING)
            .limit(limit)
        )
        return [ReportDocument.model_validate(raw) async for raw in cursor]

    async def update_status(
        self,
        report_id: UUID,
        status: ReportStatus,
        moderator_id: str,
        note: str | None,
        note_is_set: bool,
        expected_revision: int,
        now: datetime,
    ) -> ReportDocument | None:
        resolved_at = None if status == ReportStatus.REVIEWING else now
        retention_until = (
            None if status == ReportStatus.REVIEWING else now + timedelta(days=180)
        )
        collection = ReportDocument.get_pymongo_collection()
        current = await collection.find_one(
            {"public_id": report_id, "revision": expected_revision},
            {"status": 1, "moderator_note": 1},
        )
        if current is None:
            return None
        effective_note = note if note_is_set else current.get("moderator_note")
        fields: dict[str, object] = {
            "status": status,
            "updated_at": now,
            "resolved_at": resolved_at,
            "retention_until": retention_until,
            "moderator_id": moderator_id,
        }
        if note_is_set:
            fields["moderator_note"] = note
        raw = await collection.find_one_and_update(
            {"public_id": report_id, "revision": expected_revision},
            {
                "$set": fields,
                "$inc": {"revision": 1},
                "$push": {
                    "moderation_history": {
                        "revision": expected_revision + 1,
                        "from_status": current["status"],
                        "to_status": status,
                        "moderator_id": moderator_id,
                        "note": effective_note,
                        "note_changed": note_is_set,
                        "created_at": now,
                    }
                },
            },
            return_document=ReturnDocument.AFTER,
        )
        return ReportDocument.model_validate(raw) if raw else None

    async def update_photo_evidence(
        self, report_id: UUID, evidence_url: str, now: datetime
    ) -> ReportDocument | None:
        raw = await ReportDocument.get_pymongo_collection().find_one_and_update(
            {
                "public_id": report_id,
                "target_photo_evidence_status": (ReportPhotoEvidenceStatus.COPY_FAILED),
            },
            {
                "$set": {
                    "target_photo_url": evidence_url,
                    "target_photo_evidence_status": (
                        ReportPhotoEvidenceStatus.AVAILABLE
                    ),
                    "updated_at": now,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        return ReportDocument.model_validate(raw) if raw else None

    async def record_photo_evidence_attempt(
        self, report_id: UUID, now: datetime
    ) -> None:
        await ReportDocument.get_pymongo_collection().update_one(
            {
                "public_id": report_id,
                "target_photo_evidence_status": (ReportPhotoEvidenceStatus.COPY_FAILED),
            },
            {
                "$inc": {"target_photo_evidence_attempts": 1},
                "$set": {"updated_at": now},
            },
        )

    async def list_pending_photo_evidence(self, limit: int) -> list[ReportDocument]:
        cursor = (
            ReportDocument.get_pymongo_collection()
            .find(
                {
                    "target_photo_evidence_status": (
                        ReportPhotoEvidenceStatus.COPY_FAILED
                    )
                }
            )
            .sort("created_at", 1)
            .limit(limit)
        )
        return [ReportDocument.model_validate(raw) async for raw in cursor]

    async def list_due_for_cleanup(
        self, now: datetime, limit: int
    ) -> list[ReportDocument]:
        cursor = (
            ReportDocument.get_pymongo_collection()
            .find(
                {
                    "status": {"$in": [ReportStatus.RESOLVED, ReportStatus.DISMISSED]},
                    "retention_until": {"$lte": now},
                }
            )
            .sort("retention_until", 1)
            .limit(limit)
        )
        return [ReportDocument.model_validate(raw) async for raw in cursor]

    async def delete_by_public_id(self, report_id: UUID) -> None:
        await ReportDocument.get_pymongo_collection().delete_one(
            {"public_id": report_id}
        )

    async def anonymize_user(self, user_id: str) -> None:
        object_id = PydanticObjectId(user_id)
        collection = ReportDocument.get_pymongo_collection()
        await collection.update_many(
            {"reporter_id": object_id},
            {"$set": {"reporter_id": None, "reporter_telescan_id": None}},
        )
        await collection.update_many(
            {"target_id": object_id},
            {"$set": {"target_id": None}},
        )
