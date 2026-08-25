import asyncio
import hashlib
import secrets
from dataclasses import dataclass
from time import monotonic
from typing import Any

import aiohttp
import jwt
from jwt.algorithms import RSAAlgorithm

from src.domain.entities import AppleIdentityClaims
from src.domain.errors import ExternalServiceUnavailable, InvalidAppleCredential


@dataclass(slots=True)
class _CachedKeys:
    values: dict[str, Any]
    expires_at: float


class AppleIdentityVerifier:
    _issuer = "https://appleid.apple.com"
    _keys_url = "https://appleid.apple.com/auth/keys"

    def __init__(
        self,
        audience: str,
        timeout_seconds: float = 5.0,
        cache_ttl_seconds: int = 3600,
    ) -> None:
        self._audience = audience
        self._timeout_seconds = timeout_seconds
        self._cache_ttl_seconds = cache_ttl_seconds
        self._cache: _CachedKeys | None = None
        self._lock = asyncio.Lock()

    async def verify(self, identity_token: str, raw_nonce: str) -> AppleIdentityClaims:
        if not identity_token or not raw_nonce:
            raise InvalidAppleCredential()
        try:
            header = jwt.get_unverified_header(identity_token)
            key_id = str(header["kid"])
            algorithm = str(header["alg"])
        except (jwt.PyJWTError, KeyError, TypeError) as error:
            raise InvalidAppleCredential() from error
        if algorithm != "RS256":
            raise InvalidAppleCredential()

        keys = await self._keys()
        key = keys.get(key_id)
        if key is None:
            keys = await self._keys(force_refresh=True)
            key = keys.get(key_id)
        if key is None:
            raise InvalidAppleCredential()

        try:
            claims = jwt.decode(
                identity_token,
                key,
                algorithms=["RS256"],
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["sub", "iss", "aud", "exp", "iat", "nonce"]},
            )
        except jwt.PyJWTError as error:
            raise InvalidAppleCredential() from error

        expected_nonce = hashlib.sha256(raw_nonce.encode("utf-8")).hexdigest()
        received_nonce = claims.get("nonce")
        if not isinstance(received_nonce, str) or not secrets.compare_digest(
            received_nonce, expected_nonce
        ):
            raise InvalidAppleCredential()
        email = claims.get("email")
        return AppleIdentityClaims(
            subject=str(claims["sub"]),
            email=email if isinstance(email, str) else None,
        )

    async def _keys(self, force_refresh: bool = False) -> dict[str, Any]:
        if (
            not force_refresh
            and self._cache is not None
            and self._cache.expires_at > monotonic()
        ):
            return self._cache.values
        async with self._lock:
            if (
                not force_refresh
                and self._cache is not None
                and self._cache.expires_at > monotonic()
            ):
                return self._cache.values
            try:
                timeout = aiohttp.ClientTimeout(total=self._timeout_seconds)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(self._keys_url) as response:
                        response.raise_for_status()
                        payload = await response.json()
                values = {
                    str(item["kid"]): RSAAlgorithm.from_jwk(item)
                    for item in payload.get("keys", [])
                    if item.get("kid") and item.get("kty") == "RSA"
                }
            except (aiohttp.ClientError, TimeoutError, ValueError, TypeError) as error:
                if self._cache is not None:
                    return self._cache.values
                raise ExternalServiceUnavailable() from error
            if not values:
                raise ExternalServiceUnavailable()
            self._cache = _CachedKeys(
                values=values,
                expires_at=monotonic() + self._cache_ttl_seconds,
            )
            return values
