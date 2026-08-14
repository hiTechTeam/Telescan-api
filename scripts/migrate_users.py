"""Idempotently prepare legacy users for authentication v2.

Dry-run is the default.  The normal apply mode only fills missing fields; it
never deletes users, profile data, or legacy hashes.  Removing old `code`
fields is a separate, explicitly confirmed post-rollout operation.
"""

import argparse
from collections import Counter
from datetime import UTC, datetime
from uuid import uuid4

from pymongo import MongoClient

from src.core.config import Settings


REMOVE_CONFIRMATION = "REMOVE_LEGACY_CODES"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write missing v2 fields")
    parser.add_argument(
        "--remove-legacy-codes",
        action="store_true",
        help="post-rollout only: unset the old users.code field",
    )
    parser.add_argument("--confirm", default="")
    return parser.parse_args()


def migrate_users(collection, apply: bool) -> dict[str, int]:
    scanned = changed = 0
    telegram_ids: list[int] = []
    for user in collection.find({}, {"tg_id": 1, "telescan_id": 1, "created_at": 1, "updated_at": 1}):
        scanned += 1
        if "tg_id" in user:
            telegram_ids.append(user["tg_id"])
        now = datetime.now(UTC)
        created_at = getattr(user.get("_id"), "generation_time", now)
        updates: dict[str, object] = {}
        if not user.get("telescan_id"):
            updates["telescan_id"] = uuid4()
        if not user.get("created_at"):
            updates["created_at"] = created_at
        if not user.get("updated_at"):
            updates["updated_at"] = created_at
        if updates:
            changed += 1
            if apply:
                collection.update_one(
                    {"_id": user["_id"]},
                    {"$set": updates},
                )

    duplicates = sum(count - 1 for count in Counter(telegram_ids).values() if count > 1)
    return {"scanned": scanned, "would_change": changed, "duplicate_tg_ids": duplicates}


def remove_legacy_codes(collection, apply: bool, confirmation: str) -> int:
    count = collection.count_documents({"code": {"$exists": True}})
    if not apply:
        return count
    if confirmation != REMOVE_CONFIRMATION:
        raise SystemExit(
            f"Refusing destructive cleanup; pass --confirm {REMOVE_CONFIRMATION}"
        )
    collection.update_many({"code": {"$exists": True}}, {"$unset": {"code": ""}})
    return count


def main() -> None:
    args = parse_args()
    settings = Settings()
    client = MongoClient(settings.mongo_url, tz_aware=True)
    try:
        users = client[settings.mongo_dbname]["users"]
        report = migrate_users(users, apply=args.apply)
        report["legacy_codes"] = users.count_documents({"code": {"$exists": True}})
        if args.remove_legacy_codes:
            report["legacy_codes_removed"] = remove_legacy_codes(
                users, apply=args.apply, confirmation=args.confirm
            )
        mode = "APPLY" if args.apply else "DRY-RUN"
        print(f"{mode}: {report}")
        if report["duplicate_tg_ids"]:
            raise SystemExit("Duplicate tg_id values must be resolved manually before index creation")
    finally:
        client.close()


if __name__ == "__main__":
    main()
