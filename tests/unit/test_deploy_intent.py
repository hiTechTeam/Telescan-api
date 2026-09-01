from pathlib import Path

import pytest

from scripts.deploy_intent import DeployIntentStore


def payload() -> dict[str, object]:
    return {
        "version": 1,
        "deploy_id": "42-1",
        "phase": "rollback",
        "release_dir": "/home/ubuntu/telescan/.releases/Telescan-api/release-42",
        "snapshot_dir": "/home/ubuntu/telescan/.rollback/Telescan-api/42-1",
        "previous_image_ref": "telescan-api:previous",
        "rollback_image_ref": "telescan-api:rollback-42-1",
        "candidate_image_ref": "telescan-api:candidate-42-1",
        "candidate_image_id": "sha256:0123456789abcdef",
    }


def test_deploy_intent_publish_phase_and_clear_are_durable(tmp_path: Path) -> None:
    store = DeployIntentStore(tmp_path / "transactions")
    store.publish(payload())

    assert store.load()["phase"] == "rollback"
    assert store.path.stat().st_mode & 0o777 == 0o600
    store.set_phase("rollback", "candidate_commit")
    assert store.load()["phase"] == "candidate_commit"
    store.clear("candidate_commit")
    assert store.path.exists() is False


def test_deploy_intent_rejects_overwrite_wrong_phase_and_foreign_paths(
    tmp_path: Path,
) -> None:
    store = DeployIntentStore(tmp_path / "transactions")
    store.publish(payload())
    with pytest.raises(RuntimeError, match="already active"):
        store.publish(payload())
    with pytest.raises(RuntimeError, match="changed concurrently"):
        store.set_phase("candidate_commit", "manual")

    foreign = payload()
    foreign["release_dir"] = "/tmp/attacker"
    another = DeployIntentStore(tmp_path / "other")
    with pytest.raises(RuntimeError, match="approved prefix"):
        another.publish(foreign)
