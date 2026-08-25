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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    return parser.parse_args()


def migration_report(
    users, apple_identities, sessions, apply: bool
) -> dict[str, object]:
    telegram_index = users.index_information().get("uniq_tg_id")
    expected_filter = {"tg_id": {"$type": "number"}}
    needs_telegram_rebuild = (
        telegram_index is None
        or telegram_index.get("unique") is not True
        or telegram_index.get("partialFilterExpression") != expected_filter
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
        if telegram_index is not None and needs_telegram_rebuild:
            users.drop_index("uniq_tg_id")
        if needs_telegram_rebuild:
            users.create_index(
                [("tg_id", ASCENDING)],
                unique=True,
                name="uniq_tg_id",
                partialFilterExpression=expected_filter,
            )
        apple_identities.create_index(
            [("subject", ASCENDING)], unique=True, name="uniq_subject"
        )
        apple_identities.create_index(
            [("user_id", ASCENDING)], unique=True, name="uniq_user"
        )
        result = sessions.update_many(
            legacy_session_filter,
            {"$set": {"revoked_at": datetime.now(UTC)}},
        )
        legacy_sessions_revoked = result.modified_count

    return {
        "telegram_index_rebuild": needs_telegram_rebuild,
        "missing_apple_indexes": missing_apple_indexes,
        "apple_identity_count": apple_identities.count_documents({}),
        "legacy_active_sessions": legacy_active_sessions,
        "legacy_sessions_revoked": legacy_sessions_revoked,
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
        )
        mode = "APPLY" if args.apply else "DRY-RUN"
        print(f"{mode}: {report}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
