import hashlib
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from src.domain.errors import InvalidAppleCredential
from src.infrastructure.apple import AppleIdentityVerifier


def signed_identity_token(
    private_key,
    *,
    audience: str = "hiTeam.TelescaniOS",
    nonce: str = "raw-nonce-value",
) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": "000123.apple-user",
            "iss": "https://appleid.apple.com",
            "aud": audience,
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "nonce": hashlib.sha256(nonce.encode("utf-8")).hexdigest(),
            "email": "private-relay@privaterelay.appleid.com",
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "apple-test-key"},
    )


@pytest.mark.asyncio
async def test_apple_identity_verifies_signature_audience_and_nonce(
    monkeypatch,
) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verifier = AppleIdentityVerifier("hiTeam.TelescaniOS")

    async def keys(force_refresh=False):
        return {"apple-test-key": private_key.public_key()}

    monkeypatch.setattr(verifier, "_keys", keys)
    claims = await verifier.verify(
        signed_identity_token(private_key), "raw-nonce-value"
    )

    assert claims.subject == "000123.apple-user"
    assert claims.email == "private-relay@privaterelay.appleid.com"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("audience", "nonce"),
    [
        ("another.bundle", "raw-nonce-value"),
        ("hiTeam.TelescaniOS", "different-nonce"),
    ],
)
async def test_apple_identity_rejects_wrong_audience_or_nonce(
    monkeypatch, audience, nonce
) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verifier = AppleIdentityVerifier("hiTeam.TelescaniOS")

    async def keys(force_refresh=False):
        return {"apple-test-key": private_key.public_key()}

    monkeypatch.setattr(verifier, "_keys", keys)

    with pytest.raises(InvalidAppleCredential):
        await verifier.verify(
            signed_identity_token(private_key, audience=audience), nonce
        )
