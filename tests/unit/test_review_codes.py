from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from scripts.review_codes import (
    batch_status,
    issue_review_codes,
    revoke_review_codes,
)
from src.core.config import Settings
from src.domain.enums import LinkCodeStatus
from src.services.codes import LinkCodeService


class FakeUsersCollection:
    def __init__(self, user):
        self.user = user

    def find_one(self, query, _projection):
        return (
            self.user if query.get("telescan_id") == self.user["telescan_id"] else None
        )


class FakeReviewCodeCollection:
    def __init__(self):
        self.documents = []

    def insert_one(self, document):
        assert all(
            item["code_hash"] != document["code_hash"] for item in self.documents
        )
        self.documents.append(dict(document))
        return SimpleNamespace(inserted_id=document["public_id"])

    def delete_many(self, query):
        before = len(self.documents)
        self.documents = [
            item
            for item in self.documents
            if not all(item.get(key) == value for key, value in query.items())
        ]
        return SimpleNamespace(deleted_count=before - len(self.documents))

    def update_many(self, query, update):
        modified = 0
        for item in self.documents:
            if all(item.get(key) == value for key, value in query.items()):
                item.update(update["$set"])
                modified += 1
        return SimpleNamespace(modified_count=modified)

    def find(self, query, projection):
        included = {key for key, value in projection.items() if value and key != "_id"}
        return [
            {key: value for key, value in item.items() if key in included}
            for item in self.documents
            if all(item.get(key) == value for key, value in query.items())
        ]


def test_review_batch_stores_only_hashes_and_can_be_revoked() -> None:
    now = datetime(2026, 8, 20, tzinfo=UTC)
    telescan_id = uuid4()
    users = FakeUsersCollection(
        {
            "_id": __import__("bson").ObjectId(),
            "telescan_id": telescan_id,
            "tg_name": "App Review",
            "tg_username": "telescan_review",
        }
    )
    collection = FakeReviewCodeCollection()
    service = LinkCodeService("dedicated-review-secret", 8)

    batch = issue_review_codes(
        users,
        collection,
        service,
        telescan_id,
        count=5,
        valid_days=30,
        issued_by="release-operator",
        now=now,
    )

    assert len(batch.codes) == 5
    assert len(set(batch.codes)) == 5
    serialized = repr(collection.documents)
    assert all(code not in serialized for code in batch.codes)
    assert all(len(document["code_hash"]) == 64 for document in collection.documents)
    assert all(
        document["status"] == LinkCodeStatus.ISSUED.value
        for document in collection.documents
    )
    assert all(
        document["retention_until"] > document["expires_at"]
        for document in collection.documents
    )

    revoked = revoke_review_codes(
        collection,
        batch.batch_id,
        revoked_by="release-operator",
        now=now,
    )
    status = batch_status(collection, batch.batch_id)

    assert revoked == 5
    assert status["counts"][LinkCodeStatus.REVOKED.value] == 5
    assert status["counts"][LinkCodeStatus.ISSUED.value] == 0


def test_production_requires_a_dedicated_review_secret() -> None:
    production = {
        "environment": "production",
        "jwt_secret": "j" * 32,
        "link_code_hmac_secret": "l" * 32,
        "bot_service_secret": "b" * 32,
        "moderation_service_secret": "m" * 32,
        "cors_origins": ["https://tgtelescan.ru"],
        "require_moderation_revision": True,
    }

    with pytest.raises(ValueError, match="explicitly configured"):
        Settings.model_validate(production)

    production["review_code_hmac_secret"] = production["link_code_hmac_secret"]
    with pytest.raises(ValueError, match="distinct"):
        Settings.model_validate(production)
