from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from src.infrastructure.s3.client import S3PhotoStorage


def test_s3_uses_system_ca_bundle_by_default(monkeypatch) -> None:
    monkeypatch.delenv("AWS_CA_BUNDLE", raising=False)
    monkeypatch.setattr(
        "src.infrastructure.s3.client.ssl.get_default_verify_paths",
        lambda: SimpleNamespace(cafile="/system/ca-certificates.crt"),
    )

    storage = S3PhotoStorage("access", "secret", "endpoint", "public", "bucket")

    assert storage._client_config["verify"] == "/system/ca-certificates.crt"


def test_s3_respects_explicit_aws_ca_bundle(monkeypatch) -> None:
    monkeypatch.setenv("AWS_CA_BUNDLE", "/custom/ca-bundle.pem")

    storage = S3PhotoStorage("access", "secret", "endpoint", "public", "bucket")

    assert storage._client_config["verify"] == "/custom/ca-bundle.pem"


@pytest.mark.asyncio
async def test_prefix_delete_rejects_s3_per_object_errors(monkeypatch) -> None:
    class PartialDeleteClient:
        async def list_objects_v2(self, **kwargs):
            return {
                "Contents": [{"Key": "moderation/reports/report-id/evidence.jpg"}],
                "IsTruncated": False,
            }

        async def delete_objects(self, **kwargs):
            return {
                "Errors": [
                    {
                        "Key": "moderation/reports/report-id/evidence.jpg",
                        "Code": "InternalError",
                    }
                ]
            }

    client = PartialDeleteClient()

    @asynccontextmanager
    async def fake_client():
        yield client

    storage = S3PhotoStorage("access", "secret", "endpoint", "public", "bucket")
    monkeypatch.setattr(storage, "_client", fake_client)

    with pytest.raises(RuntimeError, match="per-object failures"):
        await storage._delete_prefix("moderation/reports/report-id/")
