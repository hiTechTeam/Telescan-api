import fcntl
import os
import stat
from pathlib import Path


API_INSTANCE_LOCK_PATH = Path("/run/telescan-api-singleton/production-instance.lock")


class ApiInstanceLock:
    """Hold a host-shared kernel lock for the entire API process lifetime."""

    def __init__(self, path: Path = API_INSTANCE_LOCK_PATH) -> None:
        self._path = path
        self._descriptor: int | None = None

    def acquire(self) -> None:
        if self._descriptor is not None:
            return
        try:
            descriptor = os.open(
                self._path,
                os.O_CLOEXEC | os.O_CREAT | os.O_NOFOLLOW | os.O_RDWR,
                0o600,
            )
        except OSError as error:
            raise RuntimeError(
                "production API singleton lock is unavailable"
            ) from error
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_uid != os.geteuid()
            or metadata.st_nlink != 1
        ):
            os.close(descriptor)
            raise RuntimeError("production API singleton lock is unsafe")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            os.close(descriptor)
            raise RuntimeError(
                "another production API process already holds the singleton lock"
            ) from error
        self._descriptor = descriptor

    def close(self) -> None:
        if self._descriptor is None:
            return
        descriptor = self._descriptor
        self._descriptor = None
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def acquire_production_instance_lock(
    environment: str | None = None,
    path: Path = API_INSTANCE_LOCK_PATH,
) -> ApiInstanceLock | None:
    active_environment = environment or os.environ.get("ENVIRONMENT", "development")
    if active_environment.lower() != "production":
        return None
    instance_lock = ApiInstanceLock(path)
    instance_lock.acquire()
    return instance_lock


__all__ = [
    "API_INSTANCE_LOCK_PATH",
    "ApiInstanceLock",
    "acquire_production_instance_lock",
]
