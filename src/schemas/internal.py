from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.domain.enums import ConfirmationStatus


class InternalLinkCodeResponse(BaseModel):
    code: str
    expires_at: Annotated[datetime, Field(alias="expiresAt")]
    telescan_id: Annotated[UUID, Field(alias="telescanId")]
    model_config = ConfigDict(populate_by_name=True)


class ConfirmationMessageRequest(BaseModel):
    telegram_chat_id: Annotated[int, Field(alias="telegramChatId")]
    telegram_message_id: Annotated[int, Field(alias="telegramMessageId")]
    model_config = ConfigDict(populate_by_name=True)


class ConfirmationDecisionRequest(BaseModel):
    telegram_id: Annotated[int, Field(alias="telegramId")]
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
    confirmation_id: Annotated[UUID, Field(alias="confirmationId")]
    status: ConfirmationStatus
    telegram_chat_id: Annotated[int | None, Field(alias="telegramChatId")] = None
    telegram_message_id: Annotated[int | None, Field(alias="telegramMessageId")] = None
    model_config = ConfigDict(populate_by_name=True)


class PendingConfirmationResponse(BaseModel):
    confirmation_id: Annotated[UUID, Field(alias="confirmationId")]
    expires_at: Annotated[datetime, Field(alias="expiresAt")]
    telegram_chat_id: Annotated[int | None, Field(alias="telegramChatId")] = None
    telegram_message_id: Annotated[int | None, Field(alias="telegramMessageId")] = None
    model_config = ConfigDict(populate_by_name=True)
