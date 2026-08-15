from unittest.mock import AsyncMock

import pytest

from src.api.routers import health


@pytest.mark.asyncio
async def test_liveness_does_not_depend_on_external_services() -> None:
    assert await health.liveness() == {"status": "ok"}


@pytest.mark.asyncio
async def test_readiness_reflects_database_state(monkeypatch) -> None:
    ready = AsyncMock(return_value=True)
    monkeypatch.setattr(health, "database_ready", ready)

    assert await health.readiness() == {"status": "ok"}

    ready.return_value = False
    response = await health.readiness()

    assert response.status_code == 503
    assert response.body == b'{"status":"unavailable"}'
