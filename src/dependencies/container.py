from dataclasses import dataclass

from fastapi import Request

from src.core.config import Settings
from src.infrastructure.bot import BotInternalClient
from src.infrastructure.jwt import TokenService
from src.infrastructure.rate_limit import InMemoryRateLimiter
from src.infrastructure.s3 import S3PhotoStorage
from src.repositories import (
    ConfirmationRepository,
    LinkCodeRepository,
    SessionRepository,
    UserRepository,
)
from src.repositories.legacy import LegacyRepository
from src.services import (
    LegacyCodePublisher,
    LinkCodeService,
    PhotoService,
    SessionService,
)
from src.use_cases.auth import LinkDevice, RefreshSession
from src.use_cases.confirmations import (
    DecideConfirmation,
    ListPendingConfirmations,
    RegisterConfirmationMessage,
    RequestLogoutAll,
)
from src.use_cases.issue_link_code import IssueLinkCode
from src.use_cases.legacy import LegacyCompatibility
from src.use_cases.profiles import DeleteAccount, GetOwnProfile, GetPublicProfile, UpdateOwnPhoto


@dataclass(slots=True)
class Container:
    settings: Settings
    users: UserRepository
    sessions: SessionRepository
    tokens: TokenService
    rate_limiter: InMemoryRateLimiter
    issue_link_code: IssueLinkCode
    link_device: LinkDevice
    refresh_session: RefreshSession
    request_logout_all: RequestLogoutAll
    decide_confirmation: DecideConfirmation
    list_pending_confirmations: ListPendingConfirmations
    register_confirmation_message: RegisterConfirmationMessage
    get_own_profile: GetOwnProfile
    get_public_profile: GetPublicProfile
    update_own_photo: UpdateOwnPhoto
    delete_account: DeleteAccount
    legacy: LegacyCompatibility


def build_container(settings: Settings) -> Container:
    users = UserRepository()
    link_codes = LinkCodeRepository()
    sessions = SessionRepository()
    confirmations = ConfirmationRepository()
    legacy_repository = LegacyRepository()
    code_service = LinkCodeService(
        settings.link_code_hmac_secret, settings.link_code_length
    )
    token_service = TokenService(
        settings.jwt_secret, settings.jwt_issuer, settings.access_token_ttl_seconds
    )
    storage = S3PhotoStorage(
        settings.s3_access_key,
        settings.s3_secret_key,
        settings.s3_endpoint_url,
        settings.s3_public_base_url,
        settings.s3_bucket_name,
    )
    photos = PhotoService(storage, settings.max_photo_bytes)
    session_service = SessionService(sessions, token_service)
    bot = BotInternalClient(
        settings.bot_internal_base_url,
        settings.bot_service_secret,
        settings.internal_request_timeout_seconds,
    )
    update_own_photo = UpdateOwnPhoto(users, photos)
    delete_account = DeleteAccount(
        users, link_codes, sessions, confirmations, photos
    )
    return Container(
        settings=settings,
        users=users,
        sessions=sessions,
        tokens=token_service,
        rate_limiter=InMemoryRateLimiter(),
        issue_link_code=IssueLinkCode(
            users,
            link_codes,
            code_service,
            photos,
            settings.link_code_ttl_seconds,
            LegacyCodePublisher(legacy_repository, settings.enable_legacy_api),
        ),
        link_device=LinkDevice(
            users,
            link_codes,
            sessions,
            session_service,
            code_service,
            settings.refresh_token_ttl_seconds,
        ),
        refresh_session=RefreshSession(session_service),
        request_logout_all=RequestLogoutAll(
            users, confirmations, bot, settings.confirmation_ttl_seconds
        ),
        decide_confirmation=DecideConfirmation(users, confirmations, sessions),
        list_pending_confirmations=ListPendingConfirmations(confirmations),
        register_confirmation_message=RegisterConfirmationMessage(confirmations),
        get_own_profile=GetOwnProfile(users),
        get_public_profile=GetPublicProfile(users),
        update_own_photo=update_own_photo,
        delete_account=delete_account,
        legacy=LegacyCompatibility(
            legacy_repository, users, update_own_photo, delete_account
        ),
    )


def get_container(request: Request) -> Container:
    return request.app.state.container
