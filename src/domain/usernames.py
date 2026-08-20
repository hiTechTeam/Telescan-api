from src.domain.errors import TelegramUsernameRequired


def require_telegram_username(value: str | None) -> str:
    username = (value or "").strip()
    if not username:
        raise TelegramUsernameRequired()
    return username


__all__ = ["require_telegram_username"]
