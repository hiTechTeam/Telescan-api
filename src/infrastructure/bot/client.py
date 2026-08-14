from datetime import datetime
from uuid import UUID

import aiohttp

from src.domain.errors import ExternalServiceUnavailable


class BotInternalClient:
    def __init__(self, base_url: str, service_secret: str, timeout: float) -> None:
        self._url = f"{base_url.rstrip('/')}/internal/v1/confirmation-notifications"
        self._secret = service_secret
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    async def request_logout_all_confirmation(
        self, confirmation_id: UUID, chat_id: int, expires_at: datetime
    ) -> None:
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.post(
                    self._url,
                    headers={"Authorization": f"Bearer {self._secret}"},
                    json={
                        "confirmationId": str(confirmation_id),
                        "chatId": chat_id,
                        "expiresAt": expires_at.isoformat(),
                    },
                ) as response:
                    if response.status not in range(200, 300):
                        raise ExternalServiceUnavailable("bot rejected confirmation")
        except (aiohttp.ClientError, TimeoutError) as error:
            raise ExternalServiceUnavailable("bot is unavailable") from error
