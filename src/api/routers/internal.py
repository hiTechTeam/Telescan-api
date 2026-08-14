from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile

from src.dependencies.container import Container, get_container
from src.dependencies.internal import require_internal_service
from src.schemas.internal import (
    ConfirmationDecisionRequest,
    ConfirmationMessageRequest,
    ConfirmationResponse,
    InternalLinkCodeResponse,
    PendingConfirmationResponse,
)

router = APIRouter(
    prefix="/internal/v1",
    tags=["internal"],
    dependencies=[Depends(require_internal_service)],
)


@router.post("/link-codes", response_model=InternalLinkCodeResponse)
async def issue_link_code(
    tg_id: Annotated[int, Form()],
    container: Annotated[Container, Depends(get_container)],
    tg_name: Annotated[str | None, Form()] = None,
    tg_username: Annotated[str | None, Form()] = None,
    photo: Annotated[UploadFile | None, File()] = None,
) -> InternalLinkCodeResponse:
    await container.rate_limiter.check(
        f"issue-code:{tg_id}", limit=6, window_seconds=300
    )
    photo_data = (
        await photo.read(container.settings.max_photo_bytes + 1) if photo else None
    )
    result = await container.issue_link_code.execute(
        tg_id, tg_name, tg_username, photo_data
    )
    return InternalLinkCodeResponse(
        code=result.code,
        expires_at=result.expires_at,
        telescan_id=result.telescan_id,
    )


@router.put(
    "/confirmations/{confirmation_id}/message",
    response_model=ConfirmationResponse,
)
async def register_confirmation_message(
    confirmation_id: UUID,
    payload: ConfirmationMessageRequest,
    container: Annotated[Container, Depends(get_container)],
) -> ConfirmationResponse:
    confirmation = await container.register_confirmation_message.execute(
        confirmation_id, payload.telegram_chat_id, payload.telegram_message_id
    )
    return ConfirmationResponse(
        confirmation_id=getattr(confirmation, "public_id"),
        status=getattr(confirmation, "status"),
        telegram_chat_id=getattr(confirmation, "telegram_chat_id", None),
        telegram_message_id=getattr(confirmation, "telegram_message_id", None),
    )


@router.get("/confirmations/pending", response_model=list[PendingConfirmationResponse])
async def pending_confirmations(
    container: Annotated[Container, Depends(get_container)],
) -> list[PendingConfirmationResponse]:
    confirmations = await container.list_pending_confirmations.execute()
    return [
        PendingConfirmationResponse(
            confirmation_id=getattr(item, "public_id"),
            expires_at=getattr(item, "expires_at"),
            telegram_chat_id=getattr(item, "telegram_chat_id", None),
            telegram_message_id=getattr(item, "telegram_message_id", None),
        )
        for item in confirmations
    ]


@router.post(
    "/confirmations/{confirmation_id}/decision",
    response_model=ConfirmationResponse,
)
async def decide_confirmation(
    confirmation_id: UUID,
    payload: ConfirmationDecisionRequest,
    container: Annotated[Container, Depends(get_container)],
) -> ConfirmationResponse:
    result = await container.decide_confirmation.execute(
        confirmation_id, payload.telegram_id, payload.decision
    )
    return ConfirmationResponse(
        confirmation_id=result.confirmation_id,
        status=result.status,
        telegram_chat_id=result.telegram_chat_id,
        telegram_message_id=result.telegram_message_id,
    )
