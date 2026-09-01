"""Prepare MongoDB and revoke sessions created before Apple authentication.

Dry-run is the default. Run this once before deploying the Apple-auth backend;
otherwise the legacy non-partial unique Telegram index permits only one user
without a Telegram ID. Existing user profiles are preserved; only sessions that
do not belong to an Apple identity are revoked.
"""

import argparse
from datetime import UTC, datetime

from pymongo import ASCENDING, MongoClient

from src.core.config import Settings


APPLY_CONFIRMATION = "MIGRATE_APPLE_AUTH"
TARGET_TELEGRAM_INDEX = "uniq_tg_id"
TRANSIENT_TELEGRAM_INDEX = "uniq_tg_id_partial"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    return parser.parse_args()


def migration_report(
    users,
    apple_identities,
    sessions,
    apply: bool,
    revoke_legacy_sessions: bool = True,
) -> dict[str, object]:
    index_information = users.index_information()
    target_telegram_index = index_information.get(TARGET_TELEGRAM_INDEX)
    transient_telegram_index = index_information.get(TRANSIENT_TELEGRAM_INDEX)
    expected_filter = {"tg_id": {"$type": "number"}}
    target_is_valid = (
        target_telegram_index is not None
        and target_telegram_index.get("unique") is True
        and target_telegram_index.get("partialFilterExpression") == expected_filter
    )
    needs_telegram_rebuild = not target_is_valid
    duplicate_telegram_ids = list(
        users.aggregate(
            [
                {"$match": {"tg_id": {"$type": "number"}}},
                {"$group": {"_id": "$tg_id", "count": {"$sum": 1}}},
                {"$match": {"count": {"$gt": 1}}},
                {"$count": "count"},
            ]
        )
    )
    duplicate_count = (
        duplicate_telegram_ids[0]["count"] if duplicate_telegram_ids else 0
    )
    apple_indexes = apple_identities.index_information()
    missing_apple_indexes = [
        name for name in ("uniq_subject", "uniq_user") if name not in apple_indexes
    ]
    apple_user_ids = apple_identities.distinct("user_id")
    legacy_session_filter = {
        "revoked_at": None,
        "user_id": {"$nin": apple_user_ids},
    }
    legacy_active_sessions = sessions.count_documents(legacy_session_filter)
    legacy_sessions_revoked = 0

    if apply:
        if duplicate_count:
            raise RuntimeError(
                "Refusing Telegram index migration: duplicate numeric tg_id values"
            )
        if needs_telegram_rebuild:
            if target_telegram_index is not None:
                users.drop_index(TARGET_TELEGRAM_INDEX)
            if transient_telegram_index is not None:
                users.drop_index(TRANSIENT_TELEGRAM_INDEX)
            users.create_index(
                [("tg_id", ASCENDING)],
                unique=True,
                name=TARGET_TELEGRAM_INDEX,
                partialFilterExpression=expected_filter,
            )
        apple_identities.create_index(
            [("subject", ASCENDING)], unique=True, name="uniq_subject"
        )
        apple_identities.create_index(
            [("user_id", ASCENDING)], unique=True, name="uniq_user"
        )
        if revoke_legacy_sessions:
            result = sessions.update_many(
                legacy_session_filter,
                {"$set": {"revoked_at": datetime.now(UTC)}},
            )
            legacy_sessions_revoked = result.modified_count

    return {
        "telegram_index_rebuild": needs_telegram_rebuild,
        "duplicate_telegram_ids": duplicate_count,
        "missing_apple_indexes": missing_apple_indexes,
        "apple_identity_count": apple_identities.count_documents({}),
        "legacy_active_sessions": legacy_active_sessions,
        "legacy_sessions_revoked": legacy_sessions_revoked,
        "legacy_session_revocation_enabled": revoke_legacy_sessions,
    }


def main() -> None:
    args = parse_args()
    if args.apply and args.confirm != APPLY_CONFIRMATION:
        raise SystemExit(f"Refusing migration; pass --confirm {APPLY_CONFIRMATION}")
    settings = Settings()
    client = MongoClient(settings.mongo_url, tz_aware=True)
    try:
        database = client[settings.mongo_dbname]
        report = migration_report(
            database["users"],
            database["apple_identities"],
            database["device_sessions"],
            args.apply,
            revoke_legacy_sessions=not settings.legacy_api_active,
        )
        mode = "APPLY" if args.apply else "DRY-RUN"
        print(f"{mode}: {report}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
