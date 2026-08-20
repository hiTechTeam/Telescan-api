import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from fastapi.staticfiles import StaticFiles

from src.api.routers import router as api_router
from src.core.config import Settings, settings as default_settings
from src.dependencies.container import Container, build_container
from src.domain.errors import (
    ConfirmationNotFound,
    ExternalServiceUnavailable,
    ForbiddenConfirmation,
    InvalidLinkCode,
    InvalidModerationAction,
    InvalidPhoto,
    InvalidToken,
    ModerationItemNotFound,
    RateLimitExceeded,
    RefreshTokenReused,
    SessionRevoked,
    TelegramUsernameRequired,
    UserNotFound,
)
from src.infrastructure.mongodb import close_database, init_database


def create_app(
    settings: Settings | None = None,
    container: Container | None = None,
) -> FastAPI:
    active_settings = settings or default_settings

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if container is None:
            await init_database(active_settings)
            app.state.container = build_container(active_settings)
        else:
            app.state.container = container
        logging.basicConfig(level=logging.INFO)
        yield
        if container is None:
            await close_database()

    application = FastAPI(
        title="Telescan API",
        description="Authenticated profile discovery API",
        version="2.0.0",
        default_response_class=ORJSONResponse,
        lifespan=lifespan,
    )
    application.include_router(api_router)

    public_directory = Path(__file__).resolve().parents[1] / "public"
    application.mount("/public", StaticFiles(directory=public_directory), name="public")

    if active_settings.cors_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=active_settings.cors_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
        )

    @application.exception_handler(InvalidLinkCode)
    async def invalid_link_code(_: Request, __: InvalidLinkCode) -> ORJSONResponse:
        return ORJSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Invalid or expired link code"},
        )

    @application.exception_handler(TelegramUsernameRequired)
    async def telegram_username_required(
        _: Request, __: TelegramUsernameRequired
    ) -> ORJSONResponse:
        return ORJSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "detail": "Public Telegram username is required",
                "code": "telegram_username_required",
            },
        )

    @application.exception_handler(InvalidToken)
    @application.exception_handler(SessionRevoked)
    @application.exception_handler(RefreshTokenReused)
    async def invalid_auth(_: Request, __: Exception) -> ORJSONResponse:
        return ORJSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Authentication required"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    @application.exception_handler(UserNotFound)
    @application.exception_handler(ConfirmationNotFound)
    @application.exception_handler(ModerationItemNotFound)
    async def not_found(_: Request, __: Exception) -> ORJSONResponse:
        return ORJSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": "Not found"},
        )

    @application.exception_handler(ForbiddenConfirmation)
    async def forbidden(_: Request, __: ForbiddenConfirmation) -> ORJSONResponse:
        return ORJSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"detail": "Confirmation does not belong to this user"},
        )

    @application.exception_handler(InvalidPhoto)
    async def invalid_photo(_: Request, error: InvalidPhoto) -> ORJSONResponse:
        return ORJSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": str(error)},
        )

    @application.exception_handler(InvalidModerationAction)
    async def invalid_moderation_action(
        _: Request, error: InvalidModerationAction
    ) -> ORJSONResponse:
        return ORJSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": str(error)},
        )

    @application.exception_handler(RateLimitExceeded)
    async def rate_limited(_: Request, error: RateLimitExceeded) -> ORJSONResponse:
        return ORJSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"detail": "Too many requests"},
            headers={"Retry-After": str(error.retry_after_seconds)},
        )

    @application.exception_handler(ExternalServiceUnavailable)
    async def unavailable(_: Request, __: ExternalServiceUnavailable) -> ORJSONResponse:
        return ORJSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "Telegram confirmation service is unavailable"},
        )

    return application


app = create_app()

__all__ = ["app", "create_app"]
