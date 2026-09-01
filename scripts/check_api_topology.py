"""Fail closed unless exactly one production API runtime exists on the host."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any


API_CONTAINER_NAME = "/telescan_api"
API_COMPOSE_SERVICE = "telescan-api"
API_EXECUTABLE = "/app/.venv/bin/python"
API_ARGUMENTS = ["main.py"]
API_WORKING_DIRECTORY = "/app"


def _is_running(container: dict[str, Any]) -> bool:
    return container.get("State", {}).get("Running") is True


def _labels(container: dict[str, Any]) -> dict[str, str]:
    labels = container.get("Config", {}).get("Labels")
    return labels if isinstance(labels, dict) else {}


def _is_api_like(container: dict[str, Any], expected_image_id: str) -> bool:
    labels = _labels(container)
    configured_command = container.get("Config", {}).get("Cmd")
    runtime_path = container.get("Path")
    runtime_arguments = container.get("Args")
    runtime_signature = (
        isinstance(runtime_path, str)
        and isinstance(runtime_arguments, list)
        and all(isinstance(argument, str) for argument in runtime_arguments)
        and is_api_process([runtime_path, *runtime_arguments])
    )
    configured_signature = (
        isinstance(configured_command, list)
        and all(isinstance(argument, str) for argument in configured_command)
        and is_api_process(configured_command)
    )
    return any(
        (
            container.get("Name") == API_CONTAINER_NAME,
            container.get("Image") == expected_image_id,
            labels.get("com.docker.compose.service") == API_COMPOSE_SERVICE,
            labels.get("com.docker.compose.project.working_dir", "").endswith(
                "/Telescan-api"
            ),
            runtime_signature,
            configured_signature,
        )
    )


def validate_container_inventory(
    containers: list[dict[str, Any]],
    expected_container_id: str,
    expected_image_id: str,
) -> None:
    running = [container for container in containers if _is_running(container)]
    expected = next(
        (
            container
            for container in running
            if container.get("Id") == expected_container_id
        ),
        None,
    )
    api_like = [
        container for container in running if _is_api_like(container, expected_image_id)
    ]
    if expected is None or len(api_like) != 1 or api_like[0] is not expected:
        raise RuntimeError("host must have exactly one expected API container")
    labels = _labels(expected)
    if (
        expected.get("Image") != expected_image_id
        or expected.get("Name") != API_CONTAINER_NAME
        or labels.get("com.docker.compose.service") != API_COMPOSE_SERVICE
        or expected.get("Path") != API_EXECUTABLE
        or expected.get("Args") != API_ARGUMENTS
        or expected.get("Config", {}).get("WorkingDir") != API_WORKING_DIRECTORY
    ):
        raise RuntimeError("expected API container has an unsafe runtime shape")


def is_api_process(argv: Sequence[str]) -> bool:
    arguments = list(argv)
    if len(arguments) < 2:
        return False
    executable = os.path.basename(arguments[0]).lower()
    python_runtime = executable.startswith("python")
    if python_runtime and arguments[1] == "main.py":
        return True
    if python_runtime and len(arguments) >= 4 and arguments[1:3] == ["-m", "uvicorn"]:
        return arguments[3].split("?", maxsplit=1)[0] == "src.app:app"
    if executable in {"uvicorn", "gunicorn"}:
        return any(argument == "src.app:app" for argument in arguments[1:])
    return False


def count_host_api_processes(proc_root: Path = Path("/proc")) -> int:
    process_arguments: list[list[str]] = []
    try:
        entries: Iterable[Path] = proc_root.iterdir()
    except OSError as error:
        raise RuntimeError("host process inventory is unavailable") from error
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except (OSError, PermissionError):
            continue
        argv = [part.decode(errors="replace") for part in raw.split(b"\0") if part]
        if argv:
            process_arguments.append(argv)
    return sum(is_api_process(argv) for argv in process_arguments)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-container-id", required=True)
    parser.add_argument("--expected-image-id", required=True)
    parser.add_argument("--check-host-processes", action="store_true")
    args = parser.parse_args()
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, list) or not all(
            isinstance(container, dict) for container in payload
        ):
            raise RuntimeError("Docker inventory must be a JSON array")
        validate_container_inventory(
            payload,
            args.expected_container_id,
            args.expected_image_id,
        )
        if args.check_host_processes and count_host_api_processes() != 1:
            raise RuntimeError("host must have exactly one API server process")
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(f"API topology verification failed: {error}", file=sys.stderr)
        return 1
    print("API topology verification passed: one container, one process")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
