from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.domain.enums import ConfirmationStatus


class InternalLinkCodeResponse(BaseModel):
    code: str
    expires_at: datetime = Field(alias="expiresAt")
    telescan_id: UUID = Field(alias="telescanId")
    model_config = ConfigDict(populate_by_name=True)


class ConfirmationMessageRequest(BaseModel):
    telegram_chat_id: int = Field(alias="telegramChatId")
    telegram_message_id: int = Field(alias="telegramMessageId")
    model_config = ConfigDict(populate_by_name=True)


class ConfirmationDecisionRequest(BaseModel):
    telegram_id: int = Field(alias="telegramId")
    decision: ConfirmationStatus
    model_config = ConfigDict(populate_by_name=True)

    @field_validator("decision")
    @classmethod
    def validate_decision(cls, value: ConfirmationStatus) -> ConfirmationStatus:
        if value not in {
            ConfirmationStatus.CONFIRMED,
            ConfirmationStatus.CANCELLED,
            ConfirmationStatus.EXPIRED,
        }:
            raise ValueError("unsupported confirmation decision")
        return value


class ConfirmationResponse(BaseModel):
    confirmation_id: UUID = Field(alias="confirmationId")
    status: ConfirmationStatus
    telegram_chat_id: int | None = Field(default=None, alias="telegramChatId")
    telegram_message_id: int | None = Field(default=None, alias="telegramMessageId")
    model_config = ConfigDict(populate_by_name=True)


class PendingConfirmationResponse(BaseModel):
    confirmation_id: UUID = Field(alias="confirmationId")
    expires_at: datetime = Field(alias="expiresAt")
    telegram_chat_id: int | None = Field(default=None, alias="telegramChatId")
    telegram_message_id: int | None = Field(default=None, alias="telegramMessageId")
    model_config = ConfigDict(populate_by_name=True)
