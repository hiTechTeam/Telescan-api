import hashlib
import hmac
import secrets
import string

from src.domain.errors import InvalidLinkCode
from src.domain.ports import LegacyCodeRepositoryPort


class LinkCodeService:
    ALPHABET = string.ascii_uppercase + string.digits

    def __init__(self, secret: str, length: int) -> None:
        self._secret = secret.encode("utf-8")
        self._length = length

    @staticmethod
    def normalize(code: str) -> str:
        return "".join(code.split()).upper()

    def generate(self) -> str:
        return "".join(secrets.choice(self.ALPHABET) for _ in range(self._length))

    def hash(self, code: str) -> str:
        normalized = self.normalize(code)
        if len(normalized) != self._length or any(
            character not in self.ALPHABET for character in normalized
        ):
            raise InvalidLinkCode()
        return hmac.new(
            self._secret, normalized.encode("utf-8"), hashlib.sha256
        ).hexdigest()


class LegacyCodePublisher:
    """Narrow, feature-flagged bridge for the already released pre-token app."""

    def __init__(
        self,
        repository: LegacyCodeRepositoryPort,
        enabled: bool,
        production: bool = False,
    ) -> None:
        self._repository = repository
        self._enabled = enabled and not production

    async def publish(self, user_id: str, clear_code: str) -> None:
        if not self._enabled:
            return
        normalized = LinkCodeService.normalize(clear_code)
        legacy_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        await self._repository.set_code_hash(user_id, legacy_hash)
