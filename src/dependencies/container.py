from dataclasses import dataclass

from fastapi import Request

from src.core.config import Settings
from src.infrastructure.bot import BotInternalClient
from src.infrastructure.jwt import TokenService
from src.infrastructure.rate_limit import MongoRateLimiter, RateLimiter
from src.infrastructure.s3 import S3PhotoStorage
from src.repositories import (
    BlockRepository,
    ConfirmationRepository,
    LinkCodeRepository,
    ReportRepository,
    ReviewCodeRepository,
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
    GetConfirmationStatus,
    ListPendingConfirmations,
    RegisterConfirmationMessage,
    RequestLogoutAll,
)
from src.use_cases.issue_link_code import IssueLinkCode
from src.use_cases.legacy import LegacyCompatibility
from src.use_cases.moderation import (
    BlockUser,
    GetReport,
    ListBlockedUsers,
    ListReports,
    SubmitReport,
    UnblockUser,
    UpdateReportStatus,
)
from src.use_cases.profiles import (
    DeleteAccount,
    GetOwnProfile,
    GetPublicProfile,
    UpdateOwnBio,
    UpdateOwnPhoto,
)


@dataclass(slots=True)
class Container:
    settings: Settings
    users: UserRepository
    sessions: SessionRepository
    tokens: TokenService
    rate_limiter: RateLimiter
    issue_link_code: IssueLinkCode
    link_device: LinkDevice
    refresh_session: RefreshSession
    request_logout_all: RequestLogoutAll
    get_confirmation_status: GetConfirmationStatus
    decide_confirmation: DecideConfirmation
    list_pending_confirmations: ListPendingConfirmations
    register_confirmation_message: RegisterConfirmationMessage
    get_own_profile: GetOwnProfile
    get_public_profile: GetPublicProfile
    update_own_bio: UpdateOwnBio
    update_own_photo: UpdateOwnPhoto
    delete_account: DeleteAccount
    submit_report: SubmitReport
    block_user: BlockUser
    unblock_user: UnblockUser
    list_blocked_users: ListBlockedUsers
    list_reports: ListReports
    get_report: GetReport
    update_report_status: UpdateReportStatus
    legacy: LegacyCompatibility


def build_container(settings: Settings) -> Container:
    users = UserRepository()
    link_codes = LinkCodeRepository()
    review_codes = ReviewCodeRepository()
    sessions = SessionRepository()
    confirmations = ConfirmationRepository()
    reports = ReportRepository()
    blocks = BlockRepository()
    legacy_repository = LegacyRepository()
    code_service = LinkCodeService(
        settings.link_code_hmac_secret, settings.link_code_length
    )
    review_code_service = LinkCodeService(
        settings.review_code_hmac_secret, settings.link_code_length
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
        users,
        link_codes,
        sessions,
        confirmations,
        reports,
        blocks,
        photos,
        review_codes,
    )
    return Container(
        settings=settings,
        users=users,
        sessions=sessions,
        tokens=token_service,
        rate_limiter=MongoRateLimiter(),
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
            review_codes,
            review_code_service,
        ),
        refresh_session=RefreshSession(session_service),
        request_logout_all=RequestLogoutAll(
            users, confirmations, bot, settings.confirmation_ttl_seconds
        ),
        get_confirmation_status=GetConfirmationStatus(confirmations),
        decide_confirmation=DecideConfirmation(users, confirmations, sessions),
        list_pending_confirmations=ListPendingConfirmations(confirmations),
        register_confirmation_message=RegisterConfirmationMessage(confirmations),
        get_own_profile=GetOwnProfile(users),
        get_public_profile=GetPublicProfile(users, blocks),
        update_own_bio=UpdateOwnBio(users),
        update_own_photo=update_own_photo,
        delete_account=delete_account,
        submit_report=SubmitReport(users, reports),
        block_user=BlockUser(users, blocks),
        unblock_user=UnblockUser(blocks),
        list_blocked_users=ListBlockedUsers(blocks),
        list_reports=ListReports(reports),
        get_report=GetReport(reports),
        update_report_status=UpdateReportStatus(reports),
        legacy=LegacyCompatibility(
            legacy_repository, users, update_own_photo, delete_account
        ),
    )


def get_container(request: Request) -> Container:
    return request.app.state.container
