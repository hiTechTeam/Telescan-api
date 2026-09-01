"""Read-only domain-reference and index audit.

Only aggregate counts are printed; document identifiers and user data are not.
Use ``--strict`` in deployment to fail when any invariant is violated.
"""

import argparse
from pymongo import MongoClient

from src.core.config import Settings


REQUIRED_COLLECTIONS = {
    "users",
    "apple_identities",
    "link_codes",
    "review_codes",
    "device_sessions",
    "rate_limits",
    "confirmation_requests",
    "reports",
    "blocks",
    "account_merges",
    "account_deletions",
    "account_operation_fences",
}


def _aggregate_count(collection, pipeline) -> int:
    result = list(collection.aggregate([*pipeline, {"$count": "count"}]))
    return result[0]["count"] if result else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def audit_database(database) -> dict[str, int]:
    users = set(database["users"].distinct("_id"))
    identities = database["apple_identities"]
    sessions = database["device_sessions"]
    blocks = database["blocks"]
    reports = database["reports"]
    merges = database["account_merges"]
    deletions = database["account_deletions"]
    fences = database["account_operation_fences"]

    missing_collections = REQUIRED_COLLECTIONS.difference(
        database.list_collection_names()
    )
    duplicate_issued_users = list(
        database["link_codes"].aggregate(
            [
                {"$match": {"status": "issued"}},
                {"$group": {"_id": "$user_id", "count": {"$sum": 1}}},
                {"$match": {"count": {"$gt": 1}}},
                {"$count": "count"},
            ]
        )
    )
    return {
        "missing_collections": len(missing_collections),
        "identity_missing_user": identities.count_documents(
            {"user_id": {"$nin": list(users)}}
        ),
        "session_missing_user": sessions.count_documents(
            {"user_id": {"$nin": list(users)}}
        ),
        "block_missing_endpoint": blocks.count_documents(
            {
                "$or": [
                    {"blocker_id": {"$nin": list(users)}},
                    {"blocked_id": {"$nin": list(users)}},
                ]
            }
        ),
        "self_blocks": blocks.count_documents(
            {"$expr": {"$eq": ["$blocker_id", "$blocked_id"]}}
        ),
        "report_missing_reporter": reports.count_documents(
            {"reporter_id": {"$ne": None, "$nin": list(users)}}
        ),
        "report_missing_target": reports.count_documents(
            {"target_id": {"$ne": None, "$nin": list(users)}}
        ),
        "active_merge_missing_target": merges.count_documents(
            {
                "status": {"$in": ["prepared", "migrating", "mongo_complete"]},
                "target_user_id": {"$nin": list(users)},
            }
        ),
        "active_merge_missing_source": merges.count_documents(
            {
                "status": {"$in": ["prepared", "migrating"]},
                "source_user_id": {"$nin": list(users)},
            }
        ),
        "unauthorized_advanced_merge": merges.count_documents(
            {
                "status": {"$in": ["migrating", "mongo_complete", "completed"]},
                "authorized_at": None,
            }
        ),
        "authorized_merge_retains_code_proof": merges.count_documents(
            {
                "authorized_at": {"$ne": None},
                "$or": [
                    {"authorization_code_hash": {"$ne": None}},
                    {"authorization_code_kind": {"$ne": None}},
                    {"authorization_device_id": {"$ne": None}},
                ],
            }
        ),
        "incomplete_merge_has_ttl": merges.count_documents(
            {
                "status": {"$in": ["prepared", "migrating", "mongo_complete"]},
                "retention_until": {"$ne": None},
            }
        ),
        "completed_deletion_still_has_user": deletions.count_documents(
            {
                "status": {"$in": ["db_complete", "completed"]},
                "user_id": {"$in": list(users)},
            }
        ),
        "incomplete_deletion_has_ttl": deletions.count_documents(
            {
                "status": {"$in": ["prepared", "db_complete"]},
                "retention_until": {"$ne": None},
            }
        ),
        "merge_source_missing_fence": _aggregate_count(
            merges,
            [
                {
                    "$match": {
                        "status": {
                            "$in": [
                                "prepared",
                                "migrating",
                                "mongo_complete",
                                "completed",
                            ]
                        }
                    }
                },
                {
                    "$lookup": {
                        "from": "account_operation_fences",
                        "localField": "source_user_id",
                        "foreignField": "user_id",
                        "as": "fences",
                    }
                },
                {
                    "$match": {
                        "fences": {
                            "$not": {
                                "$elemMatch": {
                                    "fenced": True,
                                    "operation_kind": "merge",
                                }
                            }
                        }
                    }
                },
            ],
        ),
        "active_merge_target_missing_fence": _aggregate_count(
            merges,
            [
                {"$match": {"status": {"$in": ["prepared", "migrating"]}}},
                {
                    "$lookup": {
                        "from": "account_operation_fences",
                        "localField": "target_user_id",
                        "foreignField": "user_id",
                        "as": "fences",
                    }
                },
                {
                    "$match": {
                        "fences": {
                            "$not": {
                                "$elemMatch": {
                                    "fenced": True,
                                    "operation_kind": "merge",
                                }
                            }
                        }
                    }
                },
            ],
        ),
        "deletion_missing_fence": _aggregate_count(
            deletions,
            [
                {
                    "$match": {
                        "status": {"$in": ["prepared", "db_complete", "completed"]}
                    }
                },
                {
                    "$lookup": {
                        "from": "account_operation_fences",
                        "localField": "user_id",
                        "foreignField": "user_id",
                        "as": "fences",
                    }
                },
                {
                    "$match": {
                        "fences": {
                            "$not": {
                                "$elemMatch": {
                                    "fenced": True,
                                    "operation_kind": "deletion",
                                }
                            }
                        }
                    }
                },
            ],
        ),
        "invalid_fence_state": fences.count_documents(
            {
                "$or": [
                    {
                        "fenced": True,
                        "$or": [
                            {"operation_kind": None},
                            {"operation_id": None},
                        ],
                    },
                    {
                        "fenced": {"$ne": True},
                        "$or": [
                            {"operation_kind": {"$ne": None}},
                            {"operation_id": {"$ne": None}},
                        ],
                    },
                ]
            }
        ),
        "orphan_merge_fence": _aggregate_count(
            fences,
            [
                {"$match": {"fenced": True, "operation_kind": "merge"}},
                {
                    "$lookup": {
                        "from": "account_merges",
                        "localField": "operation_id",
                        "foreignField": "_id",
                        "as": "journals",
                    }
                },
                {"$match": {"journals": {"$size": 0}}},
            ],
        ),
        "orphan_deletion_fence": _aggregate_count(
            fences,
            [
                {"$match": {"fenced": True, "operation_kind": "deletion"}},
                {
                    "$lookup": {
                        "from": "account_deletions",
                        "localField": "operation_id",
                        "foreignField": "_id",
                        "as": "journals",
                    }
                },
                {"$match": {"journals": {"$size": 0}}},
            ],
        ),
        "invalid_available_evidence": reports.count_documents(
            {
                "target_photo_evidence_status": "available",
                "target_photo_url": None,
            }
        ),
        "invalid_absent_evidence": reports.count_documents(
            {
                "target_photo_evidence_status": "absent",
                "$or": [
                    {"target_photo_url": {"$ne": None}},
                    {"target_photo_source_url": {"$ne": None}},
                ],
            }
        ),
        "invalid_failed_evidence": reports.count_documents(
            {
                "target_photo_evidence_status": "copy_failed",
                "$or": [
                    {"target_photo_source_url": None},
                    {"target_photo_url": {"$ne": None}},
                ],
            }
        ),
        "terminal_report_missing_retention": reports.count_documents(
            {
                "status": {"$in": ["resolved", "dismissed"]},
                "retention_until": None,
            }
        ),
        "moderation_revision_history_mismatch": reports.count_documents(
            {
                "$expr": {
                    "$ne": [
                        "$revision",
                        {"$size": {"$ifNull": ["$moderation_history", []]}},
                    ]
                }
            }
        ),
        "duplicate_issued_users": (
            duplicate_issued_users[0]["count"] if duplicate_issued_users else 0
        ),
    }


def main() -> None:
    args = parse_args()
    settings = Settings()
    client = MongoClient(settings.mongo_url, tz_aware=True)
    try:
        result = audit_database(client[settings.mongo_dbname])
    finally:
        client.close()
    print(f"READ-ONLY: {result}")
    if args.strict and any(result.values()):
        raise SystemExit("Domain invariant audit failed")


if __name__ == "__main__":
    main()
