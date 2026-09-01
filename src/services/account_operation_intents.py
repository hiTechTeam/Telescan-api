import json
import os
import re
import stat
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import TypeAlias
from uuid import uuid4


INTENT_DIRECTORY = Path("/run/telescan-api-singleton/operation-intents")
OBJECT_ID_PATTERN = re.compile(r"^[0-9a-f]{24}$")
INTENT_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
IntentValue: TypeAlias = str | None

MERGE_PAYLOAD_FIELDS = frozenset(
    {
        "target_user_id",
        "apple_subject",
        "code_hash",
        "code_kind",
        "device_id",
        "created_at",
    }
)
DELETION_PAYLOAD_FIELDS = frozenset({"created_at"})


@dataclass(frozen=True, slots=True)
class AccountOperationIntent:
    intent_id: str
    journal_id: str
    operation_kind: str
    lookup_user_id: str
    user_ids: list[str]
    payload: dict[str, IntentValue]
    version: int = 1


def _validate_intent(intent: AccountOperationIntent) -> None:
    expected_payload_fields = (
        MERGE_PAYLOAD_FIELDS
        if intent.operation_kind == "merge"
        else DELETION_PAYLOAD_FIELDS
    )
    if (
        intent.version != 1
        or not INTENT_ID_PATTERN.fullmatch(intent.intent_id)
        or not OBJECT_ID_PATTERN.fullmatch(intent.journal_id)
        or intent.operation_kind not in {"merge", "deletion"}
        or not OBJECT_ID_PATTERN.fullmatch(intent.lookup_user_id)
        or not intent.user_ids
        or len(intent.user_ids) != len(set(intent.user_ids))
        or any(not OBJECT_ID_PATTERN.fullmatch(user_id) for user_id in intent.user_ids)
        or intent.lookup_user_id not in intent.user_ids
        or set(intent.payload) != expected_payload_fields
        or any(
            value is not None and not isinstance(value, str)
            for value in intent.payload.values()
        )
    ):
        raise RuntimeError("account operation intent is invalid")
    created_at = intent.payload.get("created_at")
    if not isinstance(created_at, str):
        raise RuntimeError("account operation intent timestamp is invalid")
    try:
        parsed_created_at = datetime.fromisoformat(created_at)
    except ValueError as error:
        raise RuntimeError("account operation intent timestamp is invalid") from error
    if parsed_created_at.tzinfo is None or parsed_created_at.utcoffset() is None:
        raise RuntimeError("account operation intent timestamp is invalid")
    if intent.operation_kind == "merge":
        target_user_id = intent.payload.get("target_user_id")
        required_strings = (
            target_user_id,
            intent.payload.get("apple_subject"),
            intent.payload.get("code_hash"),
            intent.payload.get("code_kind"),
            intent.payload.get("device_id"),
        )
        if (
            any(not isinstance(value, str) or not value for value in required_strings)
            or not isinstance(target_user_id, str)
            or not OBJECT_ID_PATTERN.fullmatch(target_user_id)
            or target_user_id == intent.lookup_user_id
            or set(intent.user_ids) != {intent.lookup_user_id, target_user_id}
        ):
            raise RuntimeError("account merge intent payload is invalid")


class AccountOperationIntentStore:
    def publish(
        self,
        operation_kind: str,
        lookup_user_id: str,
        user_ids: list[str],
        payload: dict[str, IntentValue],
    ) -> AccountOperationIntent:
        raise NotImplementedError

    def list(self, operation_kind: str | None = None) -> list[AccountOperationIntent]:
        raise NotImplementedError

    def complete(self, intent_id: str) -> None:
        raise NotImplementedError


class InMemoryAccountOperationIntentStore(AccountOperationIntentStore):
    def __init__(self) -> None:
        self._intents: dict[str, AccountOperationIntent] = {}

    def publish(
        self,
        operation_kind: str,
        lookup_user_id: str,
        user_ids: list[str],
        payload: dict[str, IntentValue],
    ) -> AccountOperationIntent:
        intent = AccountOperationIntent(
            intent_id=uuid4().hex,
            journal_id=uuid4().hex[:24],
            operation_kind=operation_kind,
            lookup_user_id=lookup_user_id,
            user_ids=sorted(set(user_ids)),
            payload=dict(payload),
        )
        self._intents[intent.intent_id] = intent
        return intent

    def list(self, operation_kind: str | None = None) -> list[AccountOperationIntent]:
        return [
            intent
            for intent in self._intents.values()
            if operation_kind is None or intent.operation_kind == operation_kind
        ]

    def complete(self, intent_id: str) -> None:
        self._intents.pop(intent_id, None)


class FileAccountOperationIntentStore(AccountOperationIntentStore):
    def __init__(self, directory: Path = INTENT_DIRECTORY) -> None:
        self._directory = directory

    def publish(
        self,
        operation_kind: str,
        lookup_user_id: str,
        user_ids: list[str],
        payload: dict[str, IntentValue],
    ) -> AccountOperationIntent:
        self._ensure_directory()
        intent = AccountOperationIntent(
            intent_id=uuid4().hex,
            journal_id=uuid4().hex[:24],
            operation_kind=operation_kind,
            lookup_user_id=lookup_user_id,
            user_ids=sorted(set(user_ids)),
            payload=dict(payload),
        )
        _validate_intent(intent)
        serialized = json.dumps(
            asdict(intent),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        temporary = self._directory / f".{intent.intent_id}.tmp"
        destination = self._directory / f"{intent.intent_id}.json"
        descriptor = os.open(
            temporary,
            os.O_CLOEXEC | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_WRONLY,
            0o600,
        )
        try:
            with os.fdopen(descriptor, "wb", closefd=False) as stream:
                stream.write(serialized)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            os.close(descriptor)
        os.replace(temporary, destination)
        self._fsync_directory()
        return intent

    def list(self, operation_kind: str | None = None) -> list[AccountOperationIntent]:
        self._ensure_directory()
        intents: list[AccountOperationIntent] = []
        for path in sorted(self._directory.glob("*.json")):
            metadata = path.stat(follow_symlinks=False)
            if (
                path.is_symlink()
                or not path.is_file()
                or metadata.st_size > 4096
                or metadata.st_uid != os.geteuid()
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_nlink != 1
            ):
                raise RuntimeError("account operation intent file is unsafe")
            try:
                payload = json.loads(path.read_text())
                intent = AccountOperationIntent(**payload)
            except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
                raise RuntimeError(
                    "account operation intent cannot be decoded"
                ) from error
            _validate_intent(intent)
            if path.name != f"{intent.intent_id}.json":
                raise RuntimeError("account operation intent filename mismatch")
            if operation_kind is None or intent.operation_kind == operation_kind:
                intents.append(intent)
        return intents

    def complete(self, intent_id: str) -> None:
        if not INTENT_ID_PATTERN.fullmatch(intent_id):
            raise RuntimeError("account operation intent id is invalid")
        self._ensure_directory()
        try:
            (self._directory / f"{intent_id}.json").unlink()
        except FileNotFoundError:
            return
        self._fsync_directory()

    def _ensure_directory(self) -> None:
        if self._directory.is_symlink():
            raise RuntimeError("account operation intent directory is unsafe")
        self._directory.mkdir(mode=0o700, parents=False, exist_ok=True)
        metadata = self._directory.stat(follow_symlinks=False)
        if (
            self._directory.is_symlink()
            or not self._directory.is_dir()
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o700
        ):
            raise RuntimeError("account operation intent directory is unsafe")

    def _fsync_directory(self) -> None:
        descriptor = os.open(
            self._directory,
            os.O_CLOEXEC | os.O_DIRECTORY | os.O_RDONLY,
        )
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


__all__ = [
    "AccountOperationIntent",
    "AccountOperationIntentStore",
    "FileAccountOperationIntentStore",
    "InMemoryAccountOperationIntentStore",
    "IntentValue",
]
