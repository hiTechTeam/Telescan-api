from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from scripts.migrate_account_operation_journals import (
    migrate_account_operation_journals,
)
from scripts.migrate_apple_auth import migration_report
from scripts.migrate_link_code_invariants import migrate_link_codes
from scripts.migrate_moderation_integrity import migrate_moderation
from scripts.migrate_universal_reports import migrate_reports
from scripts.migrate_users import migrate_users, remove_legacy_codes
from src.app import create_app
from src.core.config import Settings
from src.infrastructure.mongodb.documents import (
    BlockDocument,
    LinkCodeDocument,
    ReportDocument,
    ReviewCodeDocument,
    UserDocument,
)
from src.repositories.link_codes import LinkCodeRepository
from src.repositories.review_codes import ReviewCodeRepository
from src.schemas.moderation import ReportCreateRequest
from src.schemas.users import ProfileResponse


class Result:
    pass


class FakeCollection:
    def __init__(self, users):
        self.users = users
        self.updates = []

    def find(self, *_args, **_kwargs):
        return [dict(user) for user in self.users]

    def update_one(self, query, update):
        self.updates.append((query, update))
        user = next(item for item in self.users if item["_id"] == query["_id"])
        user.update(update["$set"])
        return Result()


class FakeMigrationCollection:
    def __init__(self, documents=None, indexes=None):
        self.documents = documents or []
        self.indexes = indexes or {}

    def index_information(self):
        return self.indexes

    def drop_index(self, name):
        self.indexes.pop(name, None)

    def create_index(self, _keys, *, name, unique=False, **options):
        self.indexes[name] = {"key": list(_keys), "unique": unique, **options}

    def distinct(self, key):
        return [document[key] for document in self.documents if key in document]

    def aggregate(self, _pipeline):
        counts = {}
        for document in self.documents:
            value = document.get("tg_id")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                counts[value] = counts.get(value, 0) + 1
        duplicates = sum(count > 1 for count in counts.values())
        return [{"count": duplicates}] if duplicates else []

    def find(self, query, _projection=None):
        items = [
            document for document in self.documents if self._matches(document, query)
        ]

        class Cursor(list):
            def sort(self, keys):
                for key, direction in reversed(keys):
                    super().sort(key=lambda item: item.get(key), reverse=direction < 0)
                return self

        return Cursor(items)

    def count_documents(self, query):
        if not query:
            return len(self.documents)
        return sum(self._matches(document, query) for document in self.documents)

    def update_many(self, query, update):
        modified = 0
        for document in self.documents:
            if self._matches(document, query):
                before = dict(document)
                document.update(update.get("$set", {}))
                for key in update.get("$unset", {}):
                    document.pop(key, None)
                for key, value in update.get("$max", {}).items():
                    if document.get(key) is None or document[key] < value:
                        document[key] = value
                if document != before:
                    modified += 1
        result = Result()
        result.modified_count = modified
        return result

    def update_one(self, query, update, **options):
        modified = 0
        for document in self.documents:
            if self._matches(document, query):
                before = dict(document)
                document.update(update.get("$set", {}))
                if document != before:
                    modified = 1
                break
        else:
            if options.get("upsert"):
                document = {
                    key: value
                    for key, value in query.items()
                    if not key.startswith("$") and not isinstance(value, dict)
                }
                document.update(update.get("$setOnInsert", {}))
                document.update(update.get("$set", {}))
                self.documents.append(document)
                modified = 1
        result = Result()
        result.modified_count = modified
        return result

    @staticmethod
    def _matches(document, query):
        for key, condition in query.items():
            if key == "$or":
                if not any(
                    FakeMigrationCollection._matches(document, branch)
                    for branch in condition
                ):
                    return False
                continue
            value = document.get(key)
            if isinstance(condition, dict):
                if "$nin" in condition and value in condition["$nin"]:
                    return False
                if "$in" in condition and value not in condition["$in"]:
                    return False
                if "$ne" in condition and value == condition["$ne"]:
                    return False
                if "$exists" in condition and (key in document) != condition["$exists"]:
                    return False
                continue
            if value != condition:
                return False
        return True


def test_legacy_api_automatically_expires() -> None:
    active = Settings(
        enable_legacy_api=True,
        legacy_api_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    expired = Settings(
        enable_legacy_api=True,
        legacy_api_expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    assert active.legacy_api_active is True
    assert expired.legacy_api_active is False


def test_telegram_first_auth_does_not_enable_legacy_routes() -> None:
    settings = Settings(enable_telegram_first_auth=True)

    assert settings.telegram_first_auth_active is True
    assert settings.legacy_api_active is False


def _production_settings(**overrides) -> Settings:
    values = {
        "environment": "production",
        "mongo_username": "app-user",
        "mongo_password": "mongo-password-that-is-not-a-default",
        "mongo_host": "mongo",
        "mongo_dbname": "telescan",
        "jwt_secret": "jwt-secret-that-is-distinct-and-long",
        "link_code_hmac_secret": "link-secret-that-is-distinct-and-long",
        "review_code_hmac_secret": "review-secret-that-is-distinct-long",
        "bot_service_secret": "bot-secret-that-is-distinct-and-long",
        "moderation_service_secret": "moderation-secret-that-is-distinct",
        "s3_access_key": "s3-access-that-is-explicit",
        "s3_secret_key": "s3-secret-that-is-explicit-and-long",
        "s3_public_base_url": (
            "https://b16a45ef-34c8-400e-8e9f-c71d081ad546.selstorage.ru"
        ),
        "require_moderation_revision": True,
    }
    values.update(overrides)
    return Settings(**values)


def test_production_allows_native_only_empty_cors() -> None:
    settings = _production_settings(cors_origins=[])

    assert settings.cors_origins == []


def test_production_allows_scoped_telegram_first_auth() -> None:
    settings = _production_settings(enable_telegram_first_auth=True)

    assert settings.telegram_first_auth_active is True
    assert settings.legacy_api_active is False


def test_production_rejects_legacy_api_even_with_old_risk_flag() -> None:
    with pytest.raises(ValueError, match="legacy API is forbidden"):
        _production_settings(
            enable_legacy_api=True,
            production_legacy_risk_accepted=True,
            legacy_api_expires_at=datetime.now(UTC) + timedelta(hours=1),
        )


@pytest.mark.parametrize(
    ("setting", "value"),
    [
        ("s3_endpoint_url", "https://evil.example"),
        ("s3_endpoint_url", "https://s3.ru-7.storage.selcloud.ru:444"),
        ("s3_endpoint_url", "https://s3.ru-7.storage.selcloud.ru/foreign"),
        ("s3_public_base_url", "https://evil.example"),
        (
            "s3_public_base_url",
            "https://b16a45ef-34c8-400e-8e9f-c71d081ad546.selstorage.ru/foreign",
        ),
        (
            "s3_public_base_url",
            "https://s3.ru-7.storage.selcloud.ru/profile-photos-telescan",
        ),
        ("s3_bucket_name", "attacker-controlled-bucket"),
    ],
)
def test_production_rejects_foreign_s3_routing(setting, value) -> None:
    with pytest.raises(ValueError, match="S3"):
        _production_settings(**{setting: value})


@pytest.mark.parametrize(
    ("setting", "value"),
    [
        ("mongo_host", "evil.example"),
        ("mongo_port", 27018),
        ("mongo_dbname", "config"),
        ("mongo_username", "admin"),
        ("mongo_password", "short"),
    ],
)
def test_production_rejects_unsafe_mongodb_routing_and_credentials(
    setting, value
) -> None:
    with pytest.raises(ValueError, match="MongoDB"):
        _production_settings(**{setting: value})


def test_production_moderation_compatibility_window_is_explicit_and_bounded() -> None:
    with pytest.raises(ValueError, match="moderation CAS"):
        _production_settings(require_moderation_revision=False)

    settings = _production_settings(
        require_moderation_revision=False,
        moderation_revision_compatibility_expires_at=(
            datetime.now(UTC) + timedelta(days=1)
        ),
    )
    assert settings.require_moderation_revision is False


@pytest.mark.asyncio
async def test_consumed_link_proofs_are_rejected_after_their_deadline(
    monkeypatch,
) -> None:
    class CaptureCollection:
        query: dict | None = None
        update: dict | None = None

        async def find_one(self, query):
            self.query = query
            return None

        async def find_one_and_update(self, query, update, **_kwargs):
            self.query = query
            self.update = update
            return None

    now = datetime.now(UTC)
    device_id = uuid4()
    normal = CaptureCollection()
    monkeypatch.setattr(
        LinkCodeDocument,
        "get_pymongo_collection",
        classmethod(lambda _cls: normal),
    )
    await LinkCodeRepository().find_for_link("hash", device_id, now)
    assert normal.query is not None
    assert normal.query["$or"][1]["expires_at"] == {"$gt": now}

    review = CaptureCollection()
    monkeypatch.setattr(
        ReviewCodeDocument,
        "get_pymongo_collection",
        classmethod(lambda _cls: review),
    )
    await ReviewCodeRepository().find_for_link("hash", device_id, now)
    assert review.query is not None
    assert review.query["$or"][1]["retention_until"] == {"$gt": now}

    await ReviewCodeRepository().consume("hash", device_id, now)
    assert review.update is not None
    assert review.update["$min"]["retention_until"] == now + timedelta(days=30)


def test_public_profile_never_exposes_telegram_id() -> None:
    properties = ProfileResponse.model_json_schema(by_alias=True)["properties"]
    assert "tgId" not in properties
    assert "telegramId" not in properties
    assert "telescanId" in properties
    assert "bio" in properties


def test_universal_report_accepts_legacy_reason_during_client_rollout() -> None:
    payload = ReportCreateRequest.model_validate(
        {
            "clientRequestId": "223a0051-a330-49bb-b490-f4ad3a28676e",
            "targetTelescanId": "1262293d-e8c2-4742-b87f-e4392078db14",
            "reason": "other",
            "details": "context",
        }
    )

    assert payload.details == "context"


def test_own_profile_contract_cannot_target_another_user() -> None:
    schema = create_app(settings=Settings(), container=object()).openapi()
    photo_operation = schema["paths"]["/api/v1/users/me/photo"]["put"]
    body_schema = photo_operation["requestBody"]["content"]["multipart/form-data"][
        "schema"
    ]
    component_name = body_schema["$ref"].rsplit("/", maxsplit=1)[1]
    properties = schema["components"]["schemas"][component_name]["properties"]

    assert set(properties) == {"photo"}
    assert photo_operation["security"] == [{"HTTPBearer": []}]
    assert "requestBody" not in schema["paths"]["/api/v1/users/me"]["delete"]
    update_operation = schema["paths"]["/api/v1/users/me"]["patch"]
    assert update_operation["security"] == [{"HTTPBearer": []}]
    update_schema = update_operation["requestBody"]["content"]["application/json"][
        "schema"
    ]
    update_component = update_schema["$ref"].rsplit("/", maxsplit=1)[1]
    bio_schema = schema["components"]["schemas"][update_component]["properties"]["bio"]
    assert bio_schema["anyOf"][0]["maxLength"] == 36
    assert schema["paths"]["/api/v1/profiles/{telescan_id}"]["get"]["security"] == [
        {"HTTPBearer": []}
    ]
    status_operation = schema["paths"][
        "/api/v1/auth/logout-all/requests/{confirmation_id}"
    ]["get"]
    assert status_operation["security"] == [{"HTTPBearer": []}]
    assert schema["paths"]["/api/v1/reports"]["post"]["security"] == [
        {"HTTPBearer": []}
    ]
    report_schema_ref = schema["paths"]["/api/v1/reports"]["post"]["requestBody"][
        "content"
    ]["application/json"]["schema"]["$ref"]
    report_component = report_schema_ref.rsplit("/", maxsplit=1)[1]
    report_properties = schema["components"]["schemas"][report_component]["properties"]
    assert set(report_properties) == {
        "clientRequestId",
        "targetTelescanId",
        "details",
    }
    assert schema["paths"]["/api/v1/users/me/blocks"]["get"]["security"] == [
        {"HTTPBearer": []}
    ]
    assert schema["paths"]["/internal/v1/moderation/reports"]["get"]["security"] == [
        {"HTTPBearer": []}
    ]


def test_user_has_unique_telescan_and_telegram_indexes() -> None:
    documents = [index.document for index in UserDocument.Settings.indexes]
    assert any(
        index.get("unique") and index.get("name") == "uniq_telescan_id"
        for index in documents
    )
    assert any(
        index.get("unique") and index.get("name") == "uniq_tg_id" for index in documents
    )
    telegram_index = next(
        index for index in documents if index.get("name") == "uniq_tg_id"
    )
    assert telegram_index["partialFilterExpression"] == {"tg_id": {"$type": "number"}}


def test_moderation_documents_have_deduplication_and_lookup_indexes() -> None:
    report_indexes = [index.document for index in ReportDocument.Settings.indexes]
    block_indexes = [index.document for index in BlockDocument.Settings.indexes]

    assert any(
        index.get("unique") and index.get("name") == "uniq_reporter_request"
        for index in report_indexes
    )
    assert not any(
        index.get("name") == "uniq_pending_report" for index in report_indexes
    )
    assert any(
        index.get("unique") and index.get("name") == "uniq_blocker_blocked"
        for index in block_indexes
    )


def test_review_codes_have_unique_hash_and_delayed_audit_retention() -> None:
    indexes = [index.document for index in ReviewCodeDocument.Settings.indexes]
    assert any(
        index.get("unique") and index.get("name") == "uniq_code_hash"
        for index in indexes
    )
    assert any(
        index.get("expireAfterSeconds") == 0
        and index.get("name") == "ttl_retention_until"
        for index in indexes
    )


def test_link_codes_enforce_at_most_one_issued_code_per_user() -> None:
    indexes = [index.document for index in LinkCodeDocument.Settings.indexes]
    active = next(index for index in indexes if index.get("name") == "uniq_issued_user")

    assert active["unique"] is True
    assert active["partialFilterExpression"] == {"status": "issued"}


def test_migration_is_dry_run_and_idempotent() -> None:
    object_id = __import__("bson").ObjectId()
    collection = FakeCollection([{"_id": object_id, "tg_id": 1, "tg_name": "Ada"}])
    dry = migrate_users(collection, apply=False)
    assert dry["would_change"] == 1
    assert collection.updates == []

    applied = migrate_users(collection, apply=True)
    assert applied["would_change"] == 1
    assert "telescan_id" in collection.users[0]
    assert collection.users[0]["created_at"].tzinfo is not None

    repeated = migrate_users(collection, apply=True)
    assert repeated["would_change"] == 0


def test_legacy_code_cleanup_is_dry_run_confirmed_and_idempotent() -> None:
    users = FakeMigrationCollection(
        documents=[{"_id": "user-1", "code": "stale-sha256"}]
    )

    assert remove_legacy_codes(users, apply=False, confirmation="") == 1
    assert users.documents[0]["code"] == "stale-sha256"
    with pytest.raises(SystemExit, match="REMOVE_LEGACY_CODES"):
        remove_legacy_codes(users, apply=True, confirmation="wrong")

    assert (
        remove_legacy_codes(
            users,
            apply=True,
            confirmation="REMOVE_LEGACY_CODES",
        )
        == 1
    )
    assert "code" not in users.documents[0]
    assert (
        remove_legacy_codes(
            users,
            apply=True,
            confirmation="REMOVE_LEGACY_CODES",
        )
        == 0
    )


def test_universal_report_migration_removes_legacy_pending_index() -> None:
    reports = FakeMigrationCollection(indexes={"uniq_pending_report": {"unique": True}})

    dry_run = migrate_reports(reports, apply=False)
    assert dry_run == {"legacy_pending_index_present": True, "indexes_dropped": 0}
    assert "uniq_pending_report" in reports.indexes

    applied = migrate_reports(reports, apply=True)
    assert applied == {"legacy_pending_index_present": True, "indexes_dropped": 1}
    assert "uniq_pending_report" not in reports.indexes

    repeated = migrate_reports(reports, apply=True)
    assert repeated == {"legacy_pending_index_present": False, "indexes_dropped": 0}


def test_apple_auth_migration_revokes_only_legacy_sessions() -> None:
    users = FakeMigrationCollection(indexes={"uniq_tg_id": {"unique": True}})
    apple_identities = FakeMigrationCollection(
        documents=[{"subject": "apple-sub", "user_id": "apple-user"}]
    )
    sessions = FakeMigrationCollection(
        documents=[
            {"user_id": "apple-user", "revoked_at": None},
            {"user_id": "legacy-user", "revoked_at": None},
        ]
    )

    dry_run = migration_report(users, apple_identities, sessions, apply=False)
    assert dry_run["legacy_active_sessions"] == 1
    assert sessions.documents[1]["revoked_at"] is None

    applied = migration_report(users, apple_identities, sessions, apply=True)
    assert applied["legacy_sessions_revoked"] == 1
    assert sessions.documents[0]["revoked_at"] is None
    assert sessions.documents[1]["revoked_at"] is not None
    assert users.indexes["uniq_tg_id"]["partialFilterExpression"] == {
        "tg_id": {"$type": "number"}
    }

    repeated = migration_report(users, apple_identities, sessions, apply=True)
    assert repeated["legacy_active_sessions"] == 0
    assert repeated["legacy_sessions_revoked"] == 0


def test_apple_auth_migration_preserves_sessions_during_temporary_bypass() -> None:
    users = FakeMigrationCollection(indexes={"uniq_tg_id": {"unique": True}})
    apple_identities = FakeMigrationCollection()
    sessions = FakeMigrationCollection(
        documents=[{"user_id": "legacy-user", "revoked_at": None}]
    )

    report = migration_report(
        users,
        apple_identities,
        sessions,
        apply=True,
        revoke_legacy_sessions=False,
    )

    assert report["legacy_active_sessions"] == 1
    assert report["legacy_sessions_revoked"] == 0
    assert report["legacy_session_revocation_enabled"] is False
    assert sessions.documents[0]["revoked_at"] is None


def test_link_code_migration_deduplicates_before_unique_index() -> None:
    now = datetime.now(UTC)
    link_codes = FakeMigrationCollection(
        documents=[
            {
                "_id": "new",
                "user_id": "user-1",
                "status": "issued",
                "created_at": now,
                "expires_at": now + timedelta(minutes=5),
            },
            {
                "_id": "old",
                "user_id": "user-1",
                "status": "issued",
                "created_at": now - timedelta(seconds=1),
                "expires_at": now + timedelta(minutes=5),
            },
        ]
    )

    dry_run = migrate_link_codes(link_codes, apply=False)
    assert dry_run["duplicate_issued_codes"] == 1
    assert all(item["status"] == "issued" for item in link_codes.documents)

    applied = migrate_link_codes(link_codes, apply=True)
    assert applied["duplicates_revoked"] == 1
    assert (
        next(item for item in link_codes.documents if item["_id"] == "old")["status"]
        == "revoked"
    )
    assert link_codes.indexes["uniq_issued_user"]["partialFilterExpression"] == {
        "status": "issued"
    }


def test_link_code_migration_fails_closed_on_same_name_malformed_index() -> None:
    link_codes = FakeMigrationCollection(
        indexes={
            "uniq_issued_user": {
                "key": [("user_id", 1)],
                "unique": False,
                "partialFilterExpression": {"status": "issued"},
            }
        }
    )

    dry_run = migrate_link_codes(link_codes, apply=False)
    assert dry_run["index_invalid"] is True
    with pytest.raises(RuntimeError, match="unsafe definition"):
        migrate_link_codes(link_codes, apply=True)


def test_moderation_migration_replaces_ttl_and_marks_photo_for_copy() -> None:
    reports = FakeMigrationCollection(
        documents=[
            {
                "_id": "report-1",
                "target_photo_url": "https://storage.example/users/live.jpg",
            }
        ],
        indexes={"ttl_retention_until": {"expireAfterSeconds": 0}},
    )

    result = migrate_moderation(reports, apply=True)

    assert result["documents_changed"] == 1
    assert "ttl_retention_until" not in reports.indexes
    assert "status_retention" in reports.indexes
    report = reports.documents[0]
    assert report["target_photo_url"] is None
    assert report["target_photo_source_url"].endswith("/users/live.jpg")
    assert report["target_photo_evidence_status"] == "copy_failed"
    assert report["revision"] == 0

    repeated = migrate_moderation(reports, apply=True)
    assert repeated["documents_changed"] == 0
    assert report["target_photo_source_url"].endswith("/users/live.jpg")


def test_moderation_migration_preserves_partial_data_and_backfills_retention() -> None:
    resolved_at = datetime.now(UTC) - timedelta(days=1)
    history = [{"revision": 1, "moderator_id": "telegram:1"}]
    reports = FakeMigrationCollection(
        documents=[
            {
                "_id": "report-1",
                "status": "resolved",
                "resolved_at": resolved_at,
                "updated_at": resolved_at,
                "retention_until": None,
                "target_photo_url": (
                    "https://storage.example/moderation/reports/1/evidence.jpg"
                ),
                "target_photo_source_url": (
                    "https://storage.example/users/target/live.jpg"
                ),
                "target_photo_evidence_status": "available",
                "revision": 1,
                "moderation_history": history,
            }
        ],
        indexes={"status_retention": {}},
    )

    applied = migrate_moderation(reports, apply=True)
    report = reports.documents[0]

    assert applied["documents_changed"] == 1
    assert report["revision"] == 1
    assert report["moderation_history"] is history
    assert report["target_photo_evidence_status"] == "available"
    assert report["target_photo_url"].endswith("/evidence.jpg")
    assert report["target_photo_evidence_attempts"] == 0
    assert report["retention_until"] == resolved_at + timedelta(days=180)
    assert migrate_moderation(reports, apply=True)["documents_changed"] == 0


def test_moderation_migration_refuses_ambiguous_nonzero_revision() -> None:
    reports = FakeMigrationCollection(
        documents=[
            {
                "_id": "report-1",
                "status": "reviewing",
                "revision": 2,
                "target_photo_evidence_status": "absent",
                "target_photo_evidence_attempts": 0,
            }
        ]
    )

    with pytest.raises(RuntimeError, match="ambiguous moderation backfill"):
        migrate_moderation(reports, apply=True)

    assert "moderation_history" not in reports.documents[0]


def test_account_operation_migration_releases_cancelled_target_index() -> None:
    merges = FakeMigrationCollection(
        documents=[
            {
                "_id": "merge-1",
                "authorized_at": datetime.now(UTC),
                "authorization_code_hash": "proof",
                "authorization_code_kind": "link",
                "authorization_device_id": uuid4(),
            }
        ],
        indexes={
            "uniq_target_user": {
                "key": [("target_user_id", 1)],
                "unique": True,
            }
        },
    )

    dry_run = migrate_account_operation_journals(merges, apply=False)
    assert dry_run["legacy_target_index_present"] is True
    assert "uniq_target_user" in merges.indexes

    applied = migrate_account_operation_journals(merges, apply=True)
    assert applied["legacy_target_index_dropped"] is True
    assert "uniq_target_user" not in merges.indexes
    active = merges.indexes["uniq_target_user_active"]
    assert active["unique"] is True
    assert "cancelled" not in active["partialFilterExpression"]["status"]["$in"]
    assert applied["authorized_proofs_redacted"] == 1
    assert merges.documents[0]["authorization_code_hash"] is None
    assert merges.documents[0]["authorization_device_id"] is None


def test_account_operation_migration_fails_closed_on_malformed_active_index() -> None:
    merges = FakeMigrationCollection(
        indexes={
            "uniq_target_user_active": {
                "key": [("target_user_id", 1)],
                "unique": True,
                "partialFilterExpression": {"status": "prepared"},
            }
        }
    )

    report = migrate_account_operation_journals(merges, apply=False)
    assert report["active_target_index_invalid"] is True
    with pytest.raises(RuntimeError, match="unsafe definition"):
        migrate_account_operation_journals(merges, apply=True)


def test_account_operation_migration_creates_exact_fence_indexes() -> None:
    merges = FakeMigrationCollection()
    fences = FakeMigrationCollection()

    report = migrate_account_operation_journals(
        merges, apply=True, account_operation_fences=fences
    )

    assert report["fence_indexes_created"] == 2
    assert fences.indexes["uniq_user"] == {
        "key": [("user_id", 1)],
        "unique": True,
    }
    assert fences.indexes["ttl_retention_until"] == {
        "key": [("retention_until", 1)],
        "unique": False,
        "expireAfterSeconds": 0,
    }

    malformed = FakeMigrationCollection(
        indexes={
            "uniq_user": {"key": [("user_id", -1)], "unique": True},
        }
    )
    with pytest.raises(RuntimeError, match="fence uniq_user"):
        migrate_account_operation_journals(
            FakeMigrationCollection(),
            apply=True,
            account_operation_fences=malformed,
        )


def test_production_deploy_is_transactional_and_cleanup_is_separate() -> None:
    repository = Path(__file__).resolve().parents[2]
    deploy = (repository / ".github/workflows/deploy.yml").read_text()
    controller = (repository / "ops/deploy-production.sh").read_text()
    cleanup = (repository / ".github/workflows/remove-legacy-codes.yml").read_text()

    assert ".releases/Telescan-api/" in deploy
    assert "Upload immutable release" in deploy
    assert "DEPLOY_TELESCAN_API_WITH_ROLLBACK" in deploy
    assert "Telescan-api/$RELEASE_DIR" not in deploy
    assert "snapshot_dir=" in controller
    assert (
        'rsync -a --delete --exclude \'.env\' "$release_dir/" "$active_dir/"'
        in controller
    )
    assert (
        'rsync -a --delete --exclude \'.env\' "$snapshot_dir/" "$active_dir/"'
        in controller
    )
    assert controller.index("flock --exclusive --timeout 1800 9") < controller.index(
        '"$release_dir/" "$active_dir/"'
    )
    assert "--remove-legacy-codes" not in deploy
    assert "--remove-legacy-codes" not in controller.replace(
        "! grep -q -- '--remove-legacy-codes'", ""
    )
    assert "workflow_dispatch:" in cleanup
    assert "inputs.confirmation == 'REMOVE_LEGACY_CODES'" in cleanup
    assert "--apply --remove-legacy-codes --confirm REMOVE_LEGACY_CODES" in cleanup


def test_api_deploy_arms_recovery_and_keeps_ingress_closed_until_commit() -> None:
    repository = Path(__file__).resolve().parents[2]
    controller = (repository / "ops/deploy-production.sh").read_text()
    service = (
        repository / "ops/systemd/telescan-api-release-recovery.service"
    ).read_text()
    path = (repository / "ops/systemd/telescan-api-release-recovery.path").read_text()

    publish = controller.index('python3 "$intent_cli" publish')
    recovery_unit_sync = controller.index(
        'sudo sync -f "/etc/systemd/system/$recovery_service"'
    )
    recovery_wants_sync = controller.index(
        "sudo sync -f /etc/systemd/system/multi-user.target.wants"
    )
    watcher = controller.index('systemctl is-active --quiet "$recovery_path"', publish)
    close = controller.index("if ! close_gate", watcher)
    stop = controller.index("docker compose stop --timeout 30", close)
    local = controller.index('verify_local_candidate "$release_dir"', stop)
    commit = controller.index("intent_phase rollback candidate_commit", local)
    evidence_enable = controller.index(
        'set_evidence_worker "$release_dir" enable', commit
    )
    open_ingress = controller.index("if ! open_gate", commit)
    public = controller.index('verify_public_candidate "$release_dir"', open_ingress)
    clear = controller.index("intent_clear candidate_commit", public)

    assert recovery_unit_sync < publish
    assert recovery_wants_sync < publish
    assert (
        publish
        < watcher
        < close
        < stop
        < local
        < commit
        < evidence_enable
        < open_ingress
        < public
        < clear
    )
    assert "--owner api-deploy" in controller
    assert "--allow-http-loopback --base-url http://127.0.0.1:8000" in controller
    assert "candidate_commit manual" in controller
    assert "no old-image rollback is permitted" in controller
    assert "PathChanged=" in path
    assert "ConditionPathExists=" in service
    assert "Restart=on-failure" in service
    assert "RestartPreventExitStatus=20" in service
    assert (
        "ops/test-deploy-production.sh"
        in (repository / ".github/workflows/deploy.yml").read_text()
        or (repository / "ops/test-deploy-production.sh").is_file()
    )

    recovery = controller.split("recover_transaction() {", maxsplit=1)[1].split(
        'if [[ "$mode" == recover ]]', maxsplit=1
    )[0]
    assert recovery.index("close_gate || return") < recovery.index(
        "run_backup_and_lock_database || return"
    )

    rollback = controller.split("restore_previous_release() {", maxsplit=1)[1].split(
        "finish_committed_candidate() {", maxsplit=1
    )[0]
    for critical in (
        'rsync -a --delete --exclude \'.env\' "$snapshot_dir/" "$active_dir/" '
        "|| return",
        'docker tag "$rollback_image_ref" "$runtime_image_ref" || return',
        'wait_healthy "$container_id" || return',
        'verify_topology "$release_dir" || return',
        "open_gate || return",
    ):
        assert critical in rollback
    assert "intent_clear rollback" in rollback


def test_account_lock_topology_is_pinned_to_one_api_process() -> None:
    repository = Path(__file__).resolve().parents[2]
    main = (repository / "main.py").read_text()
    compose = (repository / "docker-compose.yaml").read_text()
    controller = (repository / "ops/deploy-production.sh").read_text()

    assert "WORKERS = 1" in main
    assert "workers=WORKERS" in main
    assert "replicas: 1" in compose
    assert "container_name: telescan_api" in compose
    assert "check_api_topology.py" in controller
    assert "--check-host-processes" in controller
    assert "preprovision_runtime" in controller
    assert "10001:10001:750" in controller
    assert "10001:10001:600" in controller
    assert "production-instance.lock" in controller
    assert "sudo -u '#10001'" not in controller
    assert '--path "$runtime_dir/evidence-worker.enabled"' in controller
