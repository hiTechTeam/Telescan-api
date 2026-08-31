"""Remove the obsolete pending-report uniqueness constraint.

The public client now submits one universal report type. Idempotency is
provided by ``client_request_id``; retaining the old reporter/target/reason
constraint would collapse every later report into the first pending one.
"""

import argparse

from pymongo import MongoClient

from src.core.config import Settings


APPLY_CONFIRMATION = "MIGRATE_UNIVERSAL_REPORTS"
LEGACY_PENDING_INDEX = "uniq_pending_report"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    return parser.parse_args()


def migrate_reports(reports, apply: bool) -> dict[str, object]:
    legacy_index_present = LEGACY_PENDING_INDEX in reports.index_information()
    indexes_dropped = 0
    if apply and legacy_index_present:
        reports.drop_index(LEGACY_PENDING_INDEX)
        indexes_dropped = 1
    return {
        "legacy_pending_index_present": legacy_index_present,
        "indexes_dropped": indexes_dropped,
    }


def main() -> None:
    args = parse_args()
    if args.apply and args.confirm != APPLY_CONFIRMATION:
        raise SystemExit(f"Refusing migration; pass --confirm {APPLY_CONFIRMATION}")
    settings = Settings()
    client = MongoClient(settings.mongo_url, tz_aware=True)
    try:
        report = migrate_reports(
            client[settings.mongo_dbname]["reports"],
            args.apply,
        )
        mode = "APPLY" if args.apply else "DRY-RUN"
        print(f"{mode}: {report}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
