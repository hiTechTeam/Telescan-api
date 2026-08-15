import asyncio

from beanie import init_beanie
from pymongo import AsyncMongoClient
from pymongo.errors import PyMongoError

from src.core.config import Settings

from .documents import DOCUMENT_MODELS

_client: AsyncMongoClient | None = None


async def init_database(settings: Settings) -> AsyncMongoClient:
    global _client
    # MongoDB stores UTC datetimes. Request aware values on reads so domain
    # timestamps never silently become naive after a database round-trip.
    _client = AsyncMongoClient(settings.mongo_url, tz_aware=True)
    await init_beanie(
        database=_client[settings.mongo_dbname],
        document_models=DOCUMENT_MODELS,
    )
    return _client


async def close_database() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None


async def database_ready(timeout_seconds: float = 2.0) -> bool:
    if _client is None:
        return False
    try:
        await asyncio.wait_for(
            _client.admin.command("ping"),
            timeout=timeout_seconds,
        )
    except (PyMongoError, TimeoutError):
        return False
    return True
