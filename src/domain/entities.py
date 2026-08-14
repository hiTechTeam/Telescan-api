from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from .enums import ConfirmationStatus


@dataclass(frozen=True, slots=True)
class AuthTokens:
    access_token: str
    refresh_token: str
    expires_in: int


@dataclass(frozen=True, slots=True)
class AuthContext:
    user_id: str
    session_id: str


@dataclass(frozen=True, slots=True)
class IssuedLinkCode:
    code: str
    expires_at: datetime
    telescan_id: UUID


@dataclass(frozen=True, slots=True)
class ConfirmationResult:
    status: ConfirmationStatus
    confirmation_id: UUID
    telegram_chat_id: int | None = None
    telegram_message_id: int | None = None
