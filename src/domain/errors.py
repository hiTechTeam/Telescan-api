class TelescanError(Exception):
    """Base error safe to translate at the presentation boundary."""


class InvalidLinkCode(TelescanError):
    pass


class LinkCodeCollision(TelescanError):
    """Generated code hash already exists and must be regenerated."""


class TelegramUsernameRequired(TelescanError):
    """A public Telegram username is required for Telescan discovery."""


class InvalidToken(TelescanError):
    pass


class SessionRevoked(TelescanError):
    pass


class RefreshTokenReused(TelescanError):
    pass


class UserNotFound(TelescanError):
    pass


class ConfirmationNotFound(TelescanError):
    pass


class ForbiddenConfirmation(TelescanError):
    pass


class InvalidPhoto(TelescanError):
    pass


class ExternalServiceUnavailable(TelescanError):
    pass


class RateLimitExceeded(TelescanError):
    def __init__(self, retry_after_seconds: int = 60) -> None:
        self.retry_after_seconds = max(1, retry_after_seconds)
        super().__init__("Too many requests")


class InvalidModerationAction(TelescanError):
    pass


class ModerationItemNotFound(TelescanError):
    pass
