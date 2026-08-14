class TelescanError(Exception):
    """Base error safe to translate at the presentation boundary."""


class InvalidLinkCode(TelescanError):
    pass


class LinkCodeCollision(TelescanError):
    """Generated code hash already exists and must be regenerated."""


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
    pass
