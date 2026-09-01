"""Enforce at most one issued link code per user.

Dry-run is the default. Duplicate issued records are deterministically reduced
to the newest record before the partial unique index is created.
"""

import argparse
from datetime import UTC, datetime

from pymongo import ASCENDING, MongoClient

from src.core.config import Settings


APPLY_CONFIRMATION = "MIGRATE_LINK_CODE_INVARIANTS"
INDEX_NAME = "uniq_issued_user"
EXPECTED_INDEX = {
    "key": [("user_id", ASCENDING)],
    "unique": True,
    "partialFilterExpression": {"status": "issued"},
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    return parser.parse_args()


def migrate_link_codes(collection, apply: bool) -> dict[str, object]:
    issued = list(
        collection.find(
            {"status": "issued"},
            {"_id": 1, "user_id": 1, "created_at": 1},
        ).sort([("user_id", ASCENDING), ("created_at", -1), ("_id", -1)])
    )
    seen_users: set[object] = set()
    duplicate_ids: list[object] = []
    for item in issued:
        user_id = item["user_id"]
        if user_id in seen_users:
            duplicate_ids.append(item["_id"])
        else:
            seen_users.add(user_id)

    indexes = collection.index_information()
    index = indexes.get(INDEX_NAME)
    index_present = index is not None
    index_valid = index is not None and all(
        (
            list(index.get("key", [])) == EXPECTED_INDEX["key"],
            index.get("unique") is True,
            index.get("partialFilterExpression")
            == EXPECTED_INDEX["partialFilterExpression"],
            "expireAfterSeconds" not in index,
        )
    )
    revoked = 0
    if apply and index_present and not index_valid:
        raise RuntimeError(
            f"Refusing migration: {INDEX_NAME} exists with an unsafe definition"
        )
    if apply and duplicate_ids:
        now = datetime.now(UTC)
        result = collection.update_many(
            {"_id": {"$in": duplicate_ids}, "status": "issued"},
            {
                "$set": {"status": "revoked"},
                "$max": {"expires_at": now},
            },
        )
        revoked = result.modified_count
    if apply and not index_present:
        collection.create_index(
            [("user_id", ASCENDING)],
            unique=True,
            name=INDEX_NAME,
            partialFilterExpression={"status": "issued"},
        )
    return {
        "issued_users": len(seen_users),
        "duplicate_issued_codes": len(duplicate_ids),
        "duplicates_revoked": revoked,
        "index_present": index_present,
        "index_valid": index_valid,
        "index_invalid": bool(index_present and not index_valid),
        "index_created": bool(apply and not index_present),
    }


def main() -> None:
    args = parse_args()
    if args.apply and args.confirm != APPLY_CONFIRMATION:
        raise SystemExit(f"Refusing migration; pass --confirm {APPLY_CONFIRMATION}")
    settings = Settings()
    client = MongoClient(settings.mongo_url, tz_aware=True)
    try:
        report = migrate_link_codes(
            client[settings.mongo_dbname]["link_codes"], args.apply
        )
        mode = "APPLY" if args.apply else "DRY-RUN"
        print(f"{mode}: {report}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
