"""Atomically control the production moderation-evidence worker."""

from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path


MARKER = Path("/run/telescan-api-singleton/evidence-worker.enabled")


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_CLOEXEC | os.O_DIRECTORY | os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def marker_is_safe(path: Path = MARKER, expected_uid: int | None = None) -> bool:
    try:
        metadata = path.stat(follow_symlinks=False)
    except FileNotFoundError:
        return False
    return (
        stat.S_ISREG(metadata.st_mode)
        and not path.is_symlink()
        and stat.S_IMODE(metadata.st_mode) == 0o600
        and metadata.st_uid == (os.geteuid() if expected_uid is None else expected_uid)
        and metadata.st_nlink == 1
    )


def enable(path: Path = MARKER, expected_uid: int | None = None) -> None:
    directory = path.parent
    if directory.is_symlink() or not directory.is_dir():
        raise RuntimeError("evidence worker runtime directory is unsafe")
    temporary = directory / f".{path.name}.{os.getpid()}.tmp"
    descriptor = os.open(
        temporary,
        os.O_CLOEXEC | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_WRONLY,
        0o600,
    )
    try:
        os.write(descriptor, b"enabled\n")
        if expected_uid is not None:
            os.fchown(descriptor, expected_uid, expected_uid)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    _fsync_directory(directory)
    if not marker_is_safe(path, expected_uid):
        raise RuntimeError("evidence worker marker is unsafe")


def disable(path: Path = MARKER) -> None:
    if path.is_symlink():
        raise RuntimeError("evidence worker marker is unsafe")
    try:
        path.unlink()
    except FileNotFoundError:
        return
    _fsync_directory(path.parent)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("enable", "disable", "status"))
    parser.add_argument("--path", type=Path, default=MARKER)
    parser.add_argument("--expected-uid", type=int)
    args = parser.parse_args()
    try:
        if args.action == "enable":
            enable(args.path, args.expected_uid)
        elif args.action == "disable":
            disable(args.path)
        else:
            return 0 if marker_is_safe(args.path, args.expected_uid) else 1
    except (OSError, RuntimeError) as error:
        print(f"Evidence worker gate failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
