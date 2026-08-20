"""Issue, inspect, and revoke scoped App Review codes.

The command never stores or logs clear-text codes. Clear values are printed once
after a complete successful batch insert and must be copied directly into App
Store Connect review notes.
"""

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from pymongo import ASCENDING, MongoClient
from pymongo.errors import DuplicateKeyError

from src.core.config import Settings
from src.domain.enums import LinkCodeStatus
from src.services.codes import LinkCodeService


ISSUE_CONFIRMATION = "ISSUE_REVIEW_CODES"
AUDIT_RETENTION_DAYS = 90
MAX_GENERATION_ATTEMPTS = 100


@dataclass(frozen=True, slots=True)
class IssuedReviewCodeBatch:
    batch_id: UUID
    telescan_id: UUID
    username: str
    expires_at: datetime
    codes: tuple[str, ...]


def _bounded_int(value: str, minimum: int, maximum: int) -> int:
    parsed = int(value)
    if not minimum <= parsed <= maximum:
        raise argparse.ArgumentTypeError(
            f"value must be between {minimum} and {maximum}"
        )
    return parsed


def _count(value: str) -> int:
    return _bounded_int(value, 5, 10)


def _valid_days(value: str) -> int:
    return _bounded_int(value, 1, 60)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    issue = subparsers.add_parser("issue", help="issue a new review-code batch")
    issue.add_argument("--telescan-id", type=UUID, required=True)
    issue.add_argument("--count", type=_count, default=10)
    issue.add_argument("--valid-days", type=_valid_days, default=30)
    issue.add_argument("--issued-by", required=True)
    issue.add_argument("--apply", action="store_true")
    issue.add_argument("--confirm", default="")

    revoke = subparsers.add_parser("revoke", help="revoke unused codes in a batch")
    revoke.add_argument("--batch-id", type=UUID, required=True)
    revoke.add_argument("--revoked-by", required=True)
    revoke.add_argument("--apply", action="store_true")

    status = subparsers.add_parser("status", help="show metadata without code hashes")
    status.add_argument("--batch-id", type=UUID, required=True)
    return parser.parse_args()


def ensure_indexes(collection: Any) -> None:
    collection.create_index(
        [("public_id", ASCENDING)], unique=True, name="uniq_public_id"
    )
    collection.create_index(
        [("code_hash", ASCENDING)], unique=True, name="uniq_code_hash"
    )
    collection.create_index(
        [("batch_id", ASCENDING), ("status", ASCENDING)], name="batch_status"
    )
    collection.create_index(
        [("user_id", ASCENDING), ("status", ASCENDING)], name="user_status"
    )
    collection.create_index([("expires_at", ASCENDING)], name="expires_at")
    collection.create_index(
        [("retention_until", ASCENDING)],
        expireAfterSeconds=0,
        name="ttl_retention_until",
    )


def get_review_profile(users: Any, telescan_id: UUID) -> dict[str, Any]:
    user = users.find_one(
        {"telescan_id": telescan_id},
        {"tg_username": 1, "tg_name": 1, "telescan_id": 1},
    )
    if user is None:
        raise SystemExit(f"Telescan profile {telescan_id} was not found")
    username = str(user.get("tg_username") or "").strip()
    if not username:
        raise SystemExit("Review profile must have a public Telegram username")
    return user


def issue_review_codes(
    users: Any,
    collection: Any,
    service: LinkCodeService,
    telescan_id: UUID,
    count: int,
    valid_days: int,
    issued_by: str,
    now: datetime | None = None,
) -> IssuedReviewCodeBatch:
    current_time = now or datetime.now(UTC)
    operator = issued_by.strip()
    if not operator:
        raise ValueError("issued_by must not be blank")
    profile = get_review_profile(users, telescan_id)
    username = str(profile["tg_username"])
    batch_id = uuid4()
    expires_at = current_time + timedelta(days=valid_days)
    retention_until = expires_at + timedelta(days=AUDIT_RETENTION_DAYS)
    clear_codes: list[str] = []

    try:
        attempts = 0
        while len(clear_codes) < count and attempts < MAX_GENERATION_ATTEMPTS:
            attempts += 1
            clear_code = service.generate()
            document = {
                "public_id": uuid4(),
                "batch_id": batch_id,
                "code_hash": service.hash(clear_code),
                "user_id": profile["_id"],
                "status": LinkCodeStatus.ISSUED.value,
                "created_at": current_time,
                "expires_at": expires_at,
                "retention_until": retention_until,
                "issued_by": operator,
                "consumed_at": None,
                "consumed_by_device_id": None,
                "revoked_at": None,
                "revoked_by": None,
            }
            try:
                collection.insert_one(document)
            except DuplicateKeyError:
                continue
            clear_codes.append(clear_code)
    except Exception:
        collection.delete_many({"batch_id": batch_id})
        raise

    if len(clear_codes) != count:
        collection.delete_many({"batch_id": batch_id})
        raise RuntimeError("Could not allocate a complete unique review-code batch")

    return IssuedReviewCodeBatch(
        batch_id=batch_id,
        telescan_id=telescan_id,
        username=username,
        expires_at=expires_at,
        codes=tuple(clear_codes),
    )


def revoke_review_codes(
    collection: Any,
    batch_id: UUID,
    revoked_by: str,
    now: datetime | None = None,
) -> int:
    current_time = now or datetime.now(UTC)
    operator = revoked_by.strip()
    if not operator:
        raise ValueError("revoked_by must not be blank")
    result = collection.update_many(
        {"batch_id": batch_id, "status": LinkCodeStatus.ISSUED.value},
        {
            "$set": {
                "status": LinkCodeStatus.REVOKED.value,
                "revoked_at": current_time,
                "revoked_by": operator,
            }
        },
    )
    return int(result.modified_count)


def batch_status(collection: Any, batch_id: UUID) -> dict[str, Any]:
    documents = list(
        collection.find(
            {"batch_id": batch_id},
            {
                "_id": 0,
                "batch_id": 1,
                "status": 1,
                "created_at": 1,
                "expires_at": 1,
                "issued_by": 1,
                "consumed_at": 1,
                "revoked_at": 1,
                "revoked_by": 1,
            },
        )
    )
    if not documents:
        raise SystemExit(f"Review-code batch {batch_id} was not found")
    counts = {
        status.value: sum(document["status"] == status.value for document in documents)
        for status in LinkCodeStatus
    }
    first = documents[0]
    return {
        "batch_id": str(batch_id),
        "created_at": first["created_at"].isoformat(),
        "expires_at": first["expires_at"].isoformat(),
        "issued_by": first["issued_by"],
        "counts": counts,
    }


def main() -> None:
    args = parse_args()
    settings = Settings()
    client = MongoClient(settings.mongo_url, tz_aware=True)
    try:
        database = client[settings.mongo_dbname]
        users = database["users"]
        review_codes = database["review_codes"]

        if args.command == "issue":
            profile = get_review_profile(users, args.telescan_id)
            if not args.apply:
                print(
                    "DRY-RUN: would issue "
                    f"{args.count} codes for @{profile['tg_username']} "
                    f"valid for {args.valid_days} days"
                )
                return
            if args.confirm != ISSUE_CONFIRMATION:
                raise SystemExit(
                    "Refusing to issue long-lived credentials; pass "
                    f"--confirm {ISSUE_CONFIRMATION}"
                )
            ensure_indexes(review_codes)
            batch = issue_review_codes(
                users,
                review_codes,
                LinkCodeService(
                    settings.review_code_hmac_secret,
                    settings.link_code_length,
                ),
                args.telescan_id,
                args.count,
                args.valid_days,
                args.issued_by,
            )
            print(f"APPLY: batch_id={batch.batch_id}")
            print(f"profile=@{batch.username} ({batch.telescan_id})")
            print(f"expires_at={batch.expires_at.isoformat()}")
            print("Copy these values now; clear-text codes cannot be recovered:")
            for code in batch.codes:
                print(code)
            return

        if args.command == "revoke":
            if not args.apply:
                count = review_codes.count_documents(
                    {
                        "batch_id": args.batch_id,
                        "status": LinkCodeStatus.ISSUED.value,
                    }
                )
                print(f"DRY-RUN: would revoke {count} unused codes")
                return
            revoked = revoke_review_codes(
                review_codes,
                args.batch_id,
                args.revoked_by,
            )
            print(f"APPLY: revoked {revoked} unused codes")
            return

        print(batch_status(review_codes, args.batch_id))
    finally:
        client.close()


if __name__ == "__main__":
    main()
