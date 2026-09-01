from __future__ import annotations

import subprocess
import sys
from importlib import import_module
from pathlib import Path

import pytest

from scripts.check_api_topology import (
    API_ARGUMENTS,
    API_CONTAINER_NAME,
    API_EXECUTABLE,
    API_WORKING_DIRECTORY,
    is_api_process,
    validate_container_inventory,
)
from src.core.config import Settings
from src.runtime_topology import ApiInstanceLock


def _container(
    container_id: str,
    image_id: str,
    *,
    name: str = API_CONTAINER_NAME,
    service: str = "telescan-api",
    path: str = API_EXECUTABLE,
    arguments: list[str] | None = None,
) -> dict[str, object]:
    return {
        "Id": container_id,
        "Image": image_id,
        "Name": name,
        "Path": path,
        "Args": API_ARGUMENTS if arguments is None else arguments,
        "State": {"Running": True},
        "Config": {
            "Cmd": [API_EXECUTABLE, *API_ARGUMENTS],
            "WorkingDir": API_WORKING_DIRECTORY,
            "Labels": {"com.docker.compose.service": service},
        },
    }


def test_topology_accepts_one_expected_api_and_unrelated_runtime() -> None:
    expected = _container("api-id", "api-image")
    unrelated = _container(
        "mongo-id",
        "mongo-image",
        name="/mongo_db",
        service="mongo",
        path="mongod",
        arguments=["--auth"],
    )
    unrelated["Config"] = {
        "Cmd": ["mongod", "--auth"],
        "WorkingDir": "/data/db",
        "Labels": {"com.docker.compose.service": "mongo"},
    }

    validate_container_inventory([expected, unrelated], "api-id", "api-image")


@pytest.mark.parametrize(
    "duplicate",
    [
        _container("shadow-name", "other-image", name="/telescan_api_shadow"),
        _container("shadow-image", "api-image", name="/shadow", service="shadow"),
        _container("shadow-service", "other-image", name="/shadow"),
    ],
)
def test_topology_rejects_any_second_api_like_container(
    duplicate: dict[str, object],
) -> None:
    expected = _container("api-id", "api-image")

    with pytest.raises(RuntimeError, match="exactly one"):
        validate_container_inventory(
            [expected, duplicate],
            "api-id",
            "api-image",
        )


def test_api_process_inventory_detects_alternate_launchers() -> None:
    assert is_api_process([API_EXECUTABLE, "main.py"]) is True
    assert is_api_process([API_EXECUTABLE, "main.py", "--workers", "2"]) is True
    assert is_api_process(["python", "main.py"]) is True
    assert is_api_process(["python", "-m", "uvicorn", "src.app:app"]) is True
    assert is_api_process(["/usr/bin/uvicorn", "src.app:app", "--workers", "2"])
    assert is_api_process(["python", "worker.py"]) is False


def test_topology_rejects_second_api_started_with_alternate_asgi_command() -> None:
    expected = _container("api-id", "api-image")
    shadow = _container(
        "shadow-id",
        "shadow-image",
        name="/innocent-name",
        service="unrelated-label",
        path="python",
        arguments=["-m", "uvicorn", "src.app:app"],
    )
    shadow["Config"] = {
        "Cmd": ["python", "-m", "uvicorn", "src.app:app"],
        "WorkingDir": "/different/path",
        "Labels": {},
    }

    with pytest.raises(RuntimeError, match="exactly one"):
        validate_container_inventory([expected, shadow], "api-id", "api-image")


def test_kernel_lock_rejects_second_process_and_recovers_after_exit(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / "api.lock"
    parent_lock = ApiInstanceLock(lock_path)
    parent_lock.acquire()
    command = [
        sys.executable,
        "-c",
        (
            "from pathlib import Path; "
            "from src.runtime_topology import ApiInstanceLock; "
            "lock = ApiInstanceLock(Path(__import__('sys').argv[1])); "
            "lock.acquire(); lock.close()"
        ),
        str(lock_path),
    ]

    blocked = subprocess.run(command, check=False, capture_output=True)
    assert blocked.returncode != 0

    parent_lock.close()
    recovered = subprocess.run(command, check=False, capture_output=True)
    assert recovered.returncode == 0


def test_kernel_lock_rejects_unsafe_mode_and_symlink(tmp_path: Path) -> None:
    unsafe = tmp_path / "unsafe.lock"
    unsafe.touch(mode=0o644)
    with pytest.raises(RuntimeError, match="unsafe"):
        ApiInstanceLock(unsafe).acquire()

    target = tmp_path / "target.lock"
    target.touch(mode=0o600)
    link = tmp_path / "link.lock"
    link.symlink_to(target)
    with pytest.raises(RuntimeError, match="unavailable"):
        ApiInstanceLock(link).acquire()


@pytest.mark.asyncio
async def test_every_asgi_launcher_acquires_singleton_in_lifespan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_module = import_module("src.app")
    events: list[str] = []

    class FakeLock:
        def close(self) -> None:
            events.append("close")

    def acquire(environment: str):
        events.append(f"acquire:{environment}")
        return FakeLock()

    monkeypatch.setattr(app_module, "acquire_production_instance_lock", acquire)
    settings = Settings()
    settings.environment = "production"
    application = app_module.create_app(settings=settings, container=object())

    async with application.router.lifespan_context(application):
        assert events == ["acquire:production"]

    assert events == ["acquire:production", "close"]
