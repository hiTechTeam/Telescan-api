"""Prepare durable account merge/deletion journal indexes.

Dry-run is the default.  The migration replaces the original all-status
target uniqueness rule with an active-history rule so an abandoned,
cancelled merge cannot lock a Telegram account forever.
"""

import argparse

from pymongo import ASCENDING, MongoClient

from src.core.config import Settings


APPLY_CONFIRMATION = "MIGRATE_ACCOUNT_OPERATION_JOURNALS"
LEGACY_TARGET_INDEX = "uniq_target_user"
TARGET_INDEX = "uniq_target_user_active"
ACTIVE_MERGE_STATUSES = [
    "prepared",
    "migrating",
    "mongo_complete",
    "completed",
]
EXPECTED_TARGET_INDEX = {
    "key": [("target_user_id", ASCENDING)],
    "unique": True,
    "partialFilterExpression": {"status": {"$in": ACTIVE_MERGE_STATUSES}},
}
EXPECTED_LEGACY_INDEX = {
    "key": [("target_user_id", ASCENDING)],
    "unique": True,
}
FENCE_USER_INDEX = "uniq_user"
FENCE_TTL_INDEX = "ttl_retention_until"
EXPECTED_FENCE_USER_INDEX = {
    "key": [("user_id", ASCENDING)],
    "unique": True,
}
EXPECTED_FENCE_TTL_INDEX = {
    "key": [("retention_until", ASCENDING)],
    "unique": False,
    "expireAfterSeconds": 0,
}


def _index_matches(actual: dict | None, expected: dict) -> bool:
    if actual is None:
        return False
    return (
        list(actual.get("key", [])) == expected["key"]
        and actual.get("unique", False) is expected.get("unique", False)
        and actual.get("partialFilterExpression")
        == expected.get("partialFilterExpression")
        and actual.get("expireAfterSeconds") == expected.get("expireAfterSeconds")
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    return parser.parse_args()


def migrate_account_operation_journals(
    account_merges, apply: bool, account_operation_fences=None
) -> dict[str, object]:
    indexes = account_merges.index_information()
    legacy_present = LEGACY_TARGET_INDEX in indexes
    target_present = TARGET_INDEX in indexes
    legacy_valid = _index_matches(
        indexes.get(LEGACY_TARGET_INDEX), EXPECTED_LEGACY_INDEX
    )
    target_valid = _index_matches(indexes.get(TARGET_INDEX), EXPECTED_TARGET_INDEX)
    fence_indexes = (
        account_operation_fences.index_information()
        if account_operation_fences is not None
        else {}
    )
    fence_user_present = FENCE_USER_INDEX in fence_indexes
    fence_ttl_present = FENCE_TTL_INDEX in fence_indexes
    fence_user_valid = _index_matches(
        fence_indexes.get(FENCE_USER_INDEX), EXPECTED_FENCE_USER_INDEX
    )
    fence_ttl_valid = _index_matches(
        fence_indexes.get(FENCE_TTL_INDEX), EXPECTED_FENCE_TTL_INDEX
    )
    authorized_proofs = account_merges.count_documents(
        {
            "authorized_at": {"$ne": None},
            "$or": [
                {"authorization_code_hash": {"$ne": None}},
                {"authorization_code_kind": {"$ne": None}},
                {"authorization_device_id": {"$ne": None}},
            ],
        }
    )
    proofs_redacted = 0
    if apply:
        if legacy_present and not legacy_valid:
            raise RuntimeError(
                f"Refusing migration: {LEGACY_TARGET_INDEX} has an unsafe definition"
            )
        if target_present and not target_valid:
            raise RuntimeError(
                f"Refusing migration: {TARGET_INDEX} has an unsafe definition"
            )
        if fence_user_present and not fence_user_valid:
            raise RuntimeError(
                f"Refusing migration: fence {FENCE_USER_INDEX} has an unsafe definition"
            )
        if fence_ttl_present and not fence_ttl_valid:
            raise RuntimeError(
                f"Refusing migration: fence {FENCE_TTL_INDEX} has an unsafe definition"
            )
        if legacy_present:
            account_merges.drop_index(LEGACY_TARGET_INDEX)
        if not target_present:
            account_merges.create_index(
                [("target_user_id", ASCENDING)],
                unique=True,
                name=TARGET_INDEX,
                partialFilterExpression={"status": {"$in": ACTIVE_MERGE_STATUSES}},
            )
        if account_operation_fences is not None and not fence_user_present:
            account_operation_fences.create_index(
                [("user_id", ASCENDING)],
                unique=True,
                name=FENCE_USER_INDEX,
            )
        if account_operation_fences is not None and not fence_ttl_present:
            account_operation_fences.create_index(
                [("retention_until", ASCENDING)],
                expireAfterSeconds=0,
                name=FENCE_TTL_INDEX,
            )
        result = account_merges.update_many(
            {"authorized_at": {"$ne": None}},
            {
                "$set": {
                    "authorization_code_hash": None,
                    "authorization_code_kind": None,
                    "authorization_device_id": None,
                }
            },
        )
        proofs_redacted = result.modified_count
    return {
        "legacy_target_index_present": legacy_present,
        "active_target_index_present": target_present,
        "legacy_target_index_valid": legacy_valid,
        "active_target_index_valid": target_valid,
        "active_target_index_invalid": bool(target_present and not target_valid),
        "fence_user_index_present": fence_user_present,
        "fence_user_index_valid": fence_user_valid,
        "fence_ttl_index_present": fence_ttl_present,
        "fence_ttl_index_valid": fence_ttl_valid,
        "fence_indexes_created": int(
            bool(
                apply
                and account_operation_fences is not None
                and not fence_user_present
            )
        )
        + int(
            bool(
                apply and account_operation_fences is not None and not fence_ttl_present
            )
        ),
        "legacy_target_index_dropped": bool(apply and legacy_present),
        "active_target_index_created": bool(apply and not target_present),
        "authorized_proofs_to_redact": authorized_proofs,
        "authorized_proofs_redacted": proofs_redacted,
    }


def main() -> None:
    args = parse_args()
    if args.apply and args.confirm != APPLY_CONFIRMATION:
        raise SystemExit(f"Refusing migration; pass --confirm {APPLY_CONFIRMATION}")
    settings = Settings()
    client = MongoClient(settings.mongo_url, tz_aware=True)
    try:
        database = client[settings.mongo_dbname]
        report = migrate_account_operation_journals(
            database["account_merges"],
            args.apply,
            database["account_operation_fences"],
        )
        mode = "APPLY" if args.apply else "DRY-RUN"
        print(f"{mode}: {report}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
