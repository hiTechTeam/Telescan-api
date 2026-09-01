"""Atomically persist the host-side production API deployment intent."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


DEFAULT_ROOT = Path("/home/ubuntu/telescan/.transactions/Telescan-api")
RELEASE_PREFIX = Path("/home/ubuntu/telescan/.releases/Telescan-api")
SNAPSHOT_PREFIX = Path("/home/ubuntu/telescan/.rollback/Telescan-api")
DEPLOY_ID_PATTERN = re.compile(r"^[0-9]+-[0-9]+$")
IMAGE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@:+-]{0,255}$")
PHASES = frozenset({"rollback", "candidate_commit", "manual"})
FIELDS = frozenset(
    {
        "version",
        "deploy_id",
        "phase",
        "release_dir",
        "snapshot_dir",
        "previous_image_ref",
        "rollback_image_ref",
        "candidate_image_ref",
        "candidate_image_id",
    }
)


class DeployIntentStore:
    def __init__(self, root: Path = DEFAULT_ROOT) -> None:
        self.root = root
        self.path = root / "active.json"

    def publish(self, payload: dict[str, Any]) -> None:
        self._ensure_root()
        if self.path.exists() or self.path.is_symlink():
            raise RuntimeError("an API deployment intent is already active")
        validated = validate_payload(payload)
        self._atomic_write(validated)

    def load(self) -> dict[str, Any]:
        self._ensure_root()
        if self.path.is_symlink() or not self.path.is_file():
            raise RuntimeError("API deployment intent is missing or unsafe")
        if self.path.stat().st_size > 8192:
            raise RuntimeError("API deployment intent is oversized")
        try:
            payload = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError("API deployment intent cannot be decoded") from error
        return validate_payload(payload)

    def set_phase(self, expected: str, phase: str) -> None:
        if expected not in PHASES or phase not in PHASES:
            raise RuntimeError("API deployment phase is invalid")
        payload = self.load()
        if payload["phase"] != expected:
            raise RuntimeError("API deployment phase changed concurrently")
        payload["phase"] = phase
        self._atomic_write(payload)

    def clear(self, expected: str) -> None:
        payload = self.load()
        if payload["phase"] != expected:
            raise RuntimeError("API deployment phase changed concurrently")
        self.path.unlink()
        self._fsync_root()

    def _ensure_root(self) -> None:
        if self.root.is_symlink():
            raise RuntimeError("API deployment transaction directory is unsafe")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.root.is_symlink() or not self.root.is_dir():
            raise RuntimeError("API deployment transaction directory is unsafe")

    def _atomic_write(self, payload: dict[str, Any]) -> None:
        temporary = self.root / f".active.{os.getpid()}.tmp"
        serialized = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
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
        os.replace(temporary, self.path)
        self._fsync_root()

    def _fsync_root(self) -> None:
        descriptor = os.open(
            self.root,
            os.O_CLOEXEC | os.O_DIRECTORY | os.O_RDONLY,
        )
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _validate_path(value: object, prefix: Path, label: str) -> str:
    if not isinstance(value, str):
        raise RuntimeError(f"{label} is invalid")
    path = Path(value)
    try:
        path.relative_to(prefix)
    except ValueError as error:
        raise RuntimeError(f"{label} is outside its approved prefix") from error
    if path == prefix or ".." in path.parts:
        raise RuntimeError(f"{label} is invalid")
    return str(path)


def validate_payload(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != FIELDS:
        raise RuntimeError("API deployment intent fields are invalid")
    deploy_id = payload.get("deploy_id")
    phase = payload.get("phase")
    if (
        payload.get("version") != 1
        or not isinstance(deploy_id, str)
        or not DEPLOY_ID_PATTERN.fullmatch(deploy_id)
        or phase not in PHASES
    ):
        raise RuntimeError("API deployment intent metadata is invalid")
    validated = dict(payload)
    validated["release_dir"] = _validate_path(
        payload.get("release_dir"), RELEASE_PREFIX, "release_dir"
    )
    validated["snapshot_dir"] = _validate_path(
        payload.get("snapshot_dir"), SNAPSHOT_PREFIX, "snapshot_dir"
    )
    for field in (
        "previous_image_ref",
        "rollback_image_ref",
        "candidate_image_ref",
        "candidate_image_id",
    ):
        value = payload.get(field)
        if not isinstance(value, str) or not IMAGE_PATTERN.fullmatch(value):
            raise RuntimeError(f"{field} is invalid")
    return validated


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    subparsers = parser.add_subparsers(dest="command", required=True)
    publish = subparsers.add_parser("publish")
    publish.add_argument("--deploy-id", required=True)
    publish.add_argument("--release-dir", required=True)
    publish.add_argument("--snapshot-dir", required=True)
    publish.add_argument("--previous-image-ref", required=True)
    publish.add_argument("--rollback-image-ref", required=True)
    publish.add_argument("--candidate-image-ref", required=True)
    publish.add_argument("--candidate-image-id", required=True)
    read = subparsers.add_parser("read")
    read.add_argument("--field", choices=sorted(FIELDS), required=True)
    phase = subparsers.add_parser("phase")
    phase.add_argument("--expected", choices=sorted(PHASES), required=True)
    phase.add_argument("--set", dest="new_phase", choices=sorted(PHASES), required=True)
    clear = subparsers.add_parser("clear")
    clear.add_argument("--expected", choices=sorted(PHASES), required=True)
    subparsers.add_parser("exists")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    store = DeployIntentStore(args.root)
    try:
        if args.command == "publish":
            store.publish(
                {
                    "version": 1,
                    "deploy_id": args.deploy_id,
                    "phase": "rollback",
                    "release_dir": args.release_dir,
                    "snapshot_dir": args.snapshot_dir,
                    "previous_image_ref": args.previous_image_ref,
                    "rollback_image_ref": args.rollback_image_ref,
                    "candidate_image_ref": args.candidate_image_ref,
                    "candidate_image_id": args.candidate_image_id,
                }
            )
        elif args.command == "read":
            value = store.load()[args.field]
            print(value)
        elif args.command == "phase":
            store.set_phase(args.expected, args.new_phase)
        elif args.command == "clear":
            store.clear(args.expected)
        elif args.command == "exists":
            return 0 if store.path.is_file() and not store.path.is_symlink() else 1
    except (OSError, RuntimeError) as error:
        print(f"API deployment intent error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
