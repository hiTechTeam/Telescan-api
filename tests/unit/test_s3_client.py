from types import SimpleNamespace

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
