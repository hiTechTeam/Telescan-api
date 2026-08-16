from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from beanie import PydanticObjectId
from pymongo import DESCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError

from src.domain.enums import ReportReason, ReportStatus
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
            "target_id": target_id,
            "reason": reason,
            "status": ReportStatus.PENDING,
        }
        update = {
            "$setOnInsert": {
                "public_id": uuid4(),
                "client_request_id": client_request_id,
                "reporter_telescan_id": getattr(reporter, "telescan_id"),
                "target_telescan_id": getattr(target, "telescan_id"),
                "details": details,
                "target_name": getattr(target, "tg_name", None),
                "target_username": getattr(target, "tg_username", None),
                "target_photo_url": getattr(target, "photo_s3_link", None),
                "created_at": now,
                "updated_at": now,
                "resolved_at": None,
                "retention_until": None,
                "moderator_id": None,
                "moderator_note": None,
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
            raw = await collection.find_one(
                {
                    "reporter_id": reporter_id,
                    "client_request_id": client_request_id,
                }
            )
            if raw is None:
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
        now: datetime,
    ) -> ReportDocument | None:
        resolved_at = None if status == ReportStatus.REVIEWING else now
        retention_until = (
            None if status == ReportStatus.REVIEWING else now + timedelta(days=180)
        )
        raw = await ReportDocument.get_pymongo_collection().find_one_and_update(
            {"public_id": report_id},
            {
                "$set": {
                    "status": status,
                    "updated_at": now,
                    "resolved_at": resolved_at,
                    "retention_until": retention_until,
                    "moderator_id": moderator_id,
                    "moderator_note": note,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        return ReportDocument.model_validate(raw) if raw else None

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
