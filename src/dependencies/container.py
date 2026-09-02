from dataclasses import dataclass

from fastapi import Request

from src.core.config import Settings
from src.infrastructure.apple import AppleIdentityVerifier
from src.infrastructure.bot import BotInternalClient
from src.infrastructure.jwt import TokenService
from src.infrastructure.rate_limit import MongoRateLimiter, RateLimiter
from src.infrastructure.s3 import S3PhotoStorage
from src.repositories import (
    AccountDeletionRepository,
    AccountMergeRepository,
    AccountOperationFenceRepository,
    AppleIdentityRepository,
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
    AccountDeletionService,
    AccountMergeService,
    AccountOperationGuard,
    LegacyCodePublisher,
    LinkCodeService,
    PhotoService,
    ReportEvidenceService,
    SessionService,
)
from src.services.report_evidence import EVIDENCE_WORKER_MARKER
from src.services.account_operation_intents import (
    FileAccountOperationIntentStore,
    InMemoryAccountOperationIntentStore,
)
from src.use_cases.auth import (
    LinkDevice,
    LinkTelegramAccount,
    RefreshSession,
    SignInWithApple,
)
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
    apple_identities: AppleIdentityRepository
    account_merges: AccountMergeRepository
    account_deletions: AccountDeletionRepository
    account_operation_fences: AccountOperationFenceRepository
    account_operation_guard: AccountOperationGuard
    account_merge_service: AccountMergeService
    account_deletion_service: AccountDeletionService
    report_evidence: ReportEvidenceService
    sessions: SessionRepository
    tokens: TokenService
    rate_limiter: RateLimiter
    issue_link_code: IssueLinkCode
    sign_in_with_apple: SignInWithApple
    link_device: LinkDevice
    link_telegram: LinkTelegramAccount
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
    apple_identities = AppleIdentityRepository()
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
    account_operation_fences = AccountOperationFenceRepository()
    account_operation_intents = (
        FileAccountOperationIntentStore()
        if settings.environment.lower() == "production"
        else InMemoryAccountOperationIntentStore()
    )
    account_operation_guard = AccountOperationGuard(
        account_operation_fences,
        account_operation_intents,
    )
    account_merges = AccountMergeRepository(account_operation_fences)
    account_merge_service = AccountMergeService(
        account_merges, users, photos, account_operation_guard
    )
    account_deletions = AccountDeletionRepository(account_operation_fences)
    account_deletion_service = AccountDeletionService(
        account_deletions, users, photos, account_operation_guard
    )
    report_evidence = ReportEvidenceService(
        reports,
        photos,
        EVIDENCE_WORKER_MARKER
        if settings.environment.lower() == "production"
        else None,
    )
    session_service = SessionService(sessions, token_service, account_operation_guard)
    apple_verifier = AppleIdentityVerifier(
        settings.apple_bundle_id, settings.apple_keys_timeout_seconds
    )
    bot = BotInternalClient(
        settings.bot_internal_base_url,
        settings.bot_service_secret,
        settings.internal_request_timeout_seconds,
    )
    update_own_photo = UpdateOwnPhoto(users, photos, account_operation_guard)
    delete_account = DeleteAccount(account_deletion_service)
    return Container(
        settings=settings,
        users=users,
        apple_identities=apple_identities,
        account_merges=account_merges,
        account_deletions=account_deletions,
        account_operation_fences=account_operation_fences,
        account_operation_guard=account_operation_guard,
        account_merge_service=account_merge_service,
        account_deletion_service=account_deletion_service,
        report_evidence=report_evidence,
        sessions=sessions,
        tokens=token_service,
        rate_limiter=MongoRateLimiter(),
        issue_link_code=IssueLinkCode(
            users,
            link_codes,
            code_service,
            photos,
            settings.link_code_ttl_seconds,
            LegacyCodePublisher(
                legacy_repository,
                settings.legacy_api_active,
                production=settings.environment.lower() == "production",
            ),
            account_operation_guard,
        ),
        sign_in_with_apple=SignInWithApple(
            users,
            apple_identities,
            apple_verifier,
            sessions,
            session_service,
            settings.refresh_token_ttl_seconds,
            account_operation_guard,
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
            account_operation_guard,
        ),
        link_telegram=LinkTelegramAccount(
            users,
            apple_identities,
            link_codes,
            sessions,
            session_service,
            code_service,
            review_codes,
            review_code_service,
            account_merge_service,
            account_operation_guard,
        ),
        refresh_session=RefreshSession(session_service),
        request_logout_all=RequestLogoutAll(
            users,
            confirmations,
            bot,
            settings.confirmation_ttl_seconds,
            account_operation_guard,
        ),
        get_confirmation_status=GetConfirmationStatus(
            confirmations, account_operation_guard
        ),
        decide_confirmation=DecideConfirmation(
            users,
            confirmations,
            sessions,
            account_operation_guard,
        ),
        list_pending_confirmations=ListPendingConfirmations(confirmations),
        register_confirmation_message=RegisterConfirmationMessage(confirmations),
        get_own_profile=GetOwnProfile(users),
        get_public_profile=GetPublicProfile(
            users,
            blocks,
            None if settings.telegram_first_auth_active else apple_identities,
        ),
        update_own_bio=UpdateOwnBio(users, account_operation_guard),
        update_own_photo=update_own_photo,
        delete_account=delete_account,
        submit_report=SubmitReport(
            users, reports, report_evidence, account_operation_guard
        ),
        block_user=BlockUser(users, blocks, account_operation_guard),
        unblock_user=UnblockUser(users, blocks, account_operation_guard),
        list_blocked_users=ListBlockedUsers(blocks),
        list_reports=ListReports(reports),
        get_report=GetReport(reports),
        update_report_status=UpdateReportStatus(
            reports,
            revision_required=settings.require_moderation_revision,
        ),
        legacy=LegacyCompatibility(
            legacy_repository, users, update_own_photo, delete_account
        ),
    )


def get_container(request: Request) -> Container:
    return request.app.state.container
