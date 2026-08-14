import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import jwt

from src.domain.errors import InvalidToken


class TokenService:
    def __init__(self, secret: str, issuer: str, access_ttl_seconds: int) -> None:
        self._secret = secret
        self._issuer = issuer
        self.access_ttl_seconds = access_ttl_seconds

    def issue_access(self, user_id: str, session_id: str, now: datetime) -> str:
        return jwt.encode(
            {
                "sub": user_id,
                "sid": session_id,
                "iss": self._issuer,
                "iat": now,
                "exp": now + timedelta(seconds=self.access_ttl_seconds),
                "type": "access",
            },
            self._secret,
            algorithm="HS256",
        )

    def decode_access(self, token: str) -> tuple[str, str]:
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=["HS256"],
                issuer=self._issuer,
                options={"require": ["sub", "sid", "exp", "type"]},
            )
            if payload["type"] != "access":
                raise InvalidToken()
            return str(payload["sub"]), str(payload["sid"])
        except (jwt.PyJWTError, KeyError, TypeError) as error:
            raise InvalidToken() from error

    @staticmethod
    def issue_refresh(session_id: str) -> str:
        return f"{session_id}.{secrets.token_urlsafe(48)}"

    @staticmethod
    def refresh_session_id(token: str) -> str:
        parts = token.split(".", maxsplit=1)
        if len(parts) != 2 or not parts[0] or len(parts[1]) < 40:
            raise InvalidToken()
        return parts[0]

    @staticmethod
    def hash_refresh(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()
