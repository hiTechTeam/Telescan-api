"""Verify or update the API's vendored copy of the canonical legal source."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "src" / "api" / "presentation" / "legal_documents.json"
DEFAULT_SOURCE = ROOT.parent / "Telescan-info" / "legal" / "legal_documents.json"


def validate(payload: bytes, label: str) -> None:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as error:
        raise SystemExit(f"{label} is not valid JSON: {error}") from error
    if data.get("schema_version") != 1:
        raise SystemExit(f"{label} has an unsupported schema")
    if not data.get("legal_version"):
        raise SystemExit(f"{label} has no legal_version")
    if set(data.get("documents", {})) != {"privacy", "terms"}:
        raise SystemExit(f"{label} must contain privacy and terms")


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--write", action="store_true")
    args = parser.parse_args()

    if not args.source.is_file():
        raise SystemExit(f"Canonical legal source is missing: {args.source}")
    source = args.source.read_bytes()
    validate(source, "canonical source")

    if args.write:
        DESTINATION.write_bytes(source)
        print(f"Updated {DESTINATION.relative_to(ROOT)} ({digest(source)})")
        return 0

    if not DESTINATION.is_file():
        raise SystemExit(f"Vendored legal source is missing: {DESTINATION}")
    vendored = DESTINATION.read_bytes()
    validate(vendored, "vendored source")
    if vendored != source:
        print(
            "Vendored legal source differs from the canonical source.",
            file=sys.stderr,
        )
        print(f"canonical sha256: {digest(source)}", file=sys.stderr)
        print(f"vendored sha256:  {digest(vendored)}", file=sys.stderr)
        print(
            "Run: python -m scripts.sync_legal_source --write",
            file=sys.stderr,
        )
        return 1
    print(f"Legal source matches canonical sha256 {digest(source)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
