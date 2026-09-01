"""Add moderation revisions/evidence fields and worker-owned retention."""

import argparse
from datetime import timedelta

from pymongo import ASCENDING, MongoClient

from src.core.config import Settings


APPLY_CONFIRMATION = "MIGRATE_MODERATION_INTEGRITY"
LEGACY_TTL_INDEX = "ttl_retention_until"
RETENTION_INDEX = "status_retention"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    return parser.parse_args()


def migrate_moderation(reports, apply: bool) -> dict[str, object]:
    indexes = reports.index_information()
    legacy_ttl_present = LEGACY_TTL_INDEX in indexes
    retention_index_present = RETENTION_INDEX in indexes
    plans: list[tuple[object, dict[str, object]]] = []
    manual_history_repairs = 0
    manual_retention_repairs = 0
    for report in reports.find(
        {},
        {
            "_id": 1,
            "status": 1,
            "created_at": 1,
            "updated_at": 1,
            "resolved_at": 1,
            "retention_until": 1,
            "target_photo_url": 1,
            "target_photo_source_url": 1,
            "target_photo_evidence_status": 1,
            "target_photo_evidence_attempts": 1,
            "revision": 1,
            "moderation_history": 1,
        },
    ):
        fields: dict[str, object] = {}
        history_present = "moderation_history" in report
        revision_present = "revision" in report
        history = report.get("moderation_history")
        revision = report.get("revision")
        if not revision_present:
            fields["revision"] = len(history) if isinstance(history, list) else 0
        if not history_present:
            if not revision_present or revision == 0:
                fields["moderation_history"] = []
            else:
                manual_history_repairs += 1
        elif not isinstance(history, list):
            manual_history_repairs += 1

        if "target_photo_evidence_status" not in report:
            source_url = report.get("target_photo_source_url") or report.get(
                "target_photo_url"
            )
            if "target_photo_source_url" not in report:
                fields["target_photo_source_url"] = source_url
            if report.get("target_photo_url") is not None:
                fields["target_photo_url"] = None
            fields["target_photo_evidence_status"] = (
                "copy_failed" if source_url else "absent"
            )
        if "target_photo_evidence_attempts" not in report:
            fields["target_photo_evidence_attempts"] = 0

        if (
            report.get("status") in {"resolved", "dismissed"}
            and report.get("retention_until") is None
        ):
            retention_base = report.get("resolved_at") or report.get("updated_at")
            if retention_base is None:
                manual_retention_repairs += 1
            else:
                fields["retention_until"] = retention_base + timedelta(days=180)

        if fields:
            plans.append((report["_id"], fields))

    changed = 0
    if apply:
        if manual_history_repairs or manual_retention_repairs:
            raise RuntimeError(
                "Refusing ambiguous moderation backfill; repair nonzero revisions "
                "without history and terminal reports without timestamps first"
            )
        for report_id, fields in plans:
            result = reports.update_one(
                {"_id": report_id},
                {"$set": fields},
            )
            changed += result.modified_count
        if legacy_ttl_present:
            reports.drop_index(LEGACY_TTL_INDEX)
        if not retention_index_present:
            reports.create_index(
                [("status", ASCENDING), ("retention_until", ASCENDING)],
                name=RETENTION_INDEX,
            )
    return {
        "documents_to_backfill": len(plans),
        "documents_changed": changed,
        "manual_history_repairs_required": manual_history_repairs,
        "manual_retention_repairs_required": manual_retention_repairs,
        "legacy_ttl_index_present": legacy_ttl_present,
        "retention_index_present": retention_index_present,
    }


def main() -> None:
    args = parse_args()
    if args.apply and args.confirm != APPLY_CONFIRMATION:
        raise SystemExit(f"Refusing migration; pass --confirm {APPLY_CONFIRMATION}")
    settings = Settings()
    client = MongoClient(settings.mongo_url, tz_aware=True)
    try:
        report = migrate_moderation(
            client[settings.mongo_dbname]["reports"], args.apply
        )
        mode = "APPLY" if args.apply else "DRY-RUN"
        print(f"{mode}: {report}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
