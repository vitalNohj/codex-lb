from __future__ import annotations

import pytest

from app.db.session import SessionLocal
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeyCreateData, ApiKeysService

pytestmark = pytest.mark.integration


async def _create_api_key(name: str) -> str:
    async with SessionLocal() as session:
        created = await ApiKeysService(ApiKeysRepository(session)).create_key(
            ApiKeyCreateData(name=name, allowed_models=None, limits=[])
        )
    return created.key


@pytest.mark.asyncio
async def test_anthropic_oauth_usage_requires_api_key(async_client) -> None:
    response = await async_client.get("/api/oauth/usage")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_anthropic_oauth_usage_returns_anthropic_shape(async_client) -> None:
    plain_key = await _create_api_key("oauth-usage-shape")
    response = await async_client.get("/api/oauth/usage", headers={"Authorization": f"Bearer {plain_key}"})
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {
        "five_hour",
        "seven_day",
        "seven_day_opus",
        "seven_day_sonnet",
        "extra_usage",
    }
    # No Claude snapshot in default integration DB → null buckets.
    assert body["five_hour"] is None
    assert body["seven_day"] is None
    assert body["seven_day_opus"] is None
    assert body["seven_day_sonnet"] is None
    assert body["extra_usage"] is None
    assert "accounts" not in body
