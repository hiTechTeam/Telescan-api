from datetime import UTC, datetime

from pymongo import IndexModel

from scripts.migrate_users import migrate_users
from src.app import create_app
from src.core.config import Settings
from src.infrastructure.mongodb.documents import UserDocument
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


def test_public_profile_never_exposes_telegram_id() -> None:
    properties = ProfileResponse.model_json_schema(by_alias=True)["properties"]
    assert "tgId" not in properties
    assert "telegramId" not in properties
    assert "telescanId" in properties


def test_own_profile_contract_cannot_target_another_user() -> None:
    schema = create_app(settings=Settings(), container=object()).openapi()
    photo_operation = schema["paths"]["/api/v1/users/me/photo"]["put"]
    body_schema = photo_operation["requestBody"]["content"]["multipart/form-data"]["schema"]
    component_name = body_schema["$ref"].rsplit("/", maxsplit=1)[1]
    properties = schema["components"]["schemas"][component_name]["properties"]

    assert set(properties) == {"photo"}
    assert photo_operation["security"] == [{"HTTPBearer": []}]
    assert "requestBody" not in schema["paths"]["/api/v1/users/me"]["delete"]
    assert schema["paths"]["/api/v1/profiles/{telescan_id}"]["get"]["security"] == [
        {"HTTPBearer": []}
    ]


def test_user_has_unique_telescan_and_telegram_indexes() -> None:
    documents = [index.document for index in UserDocument.Settings.indexes]
    assert any(index.get("unique") and index.get("name") == "uniq_telescan_id" for index in documents)
    assert any(index.get("unique") and index.get("name") == "uniq_tg_id" for index in documents)


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
