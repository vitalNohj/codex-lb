from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.core.config.settings_cache import get_settings_cache
from app.db.models import DashboardSettings
from app.db.session import SessionLocal
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeyCreateData, ApiKeysService

pytestmark = pytest.mark.integration

# Both registered variants of the endpoint. The trailing-slash route is a
# distinct registration (``include_in_schema=False``), not a redirect, so its
# authentication is enforced independently and must be asserted independently.
_OAUTH_USAGE_PATHS = ["/api/oauth/usage", "/api/oauth/usage/"]
_ANTHROPIC_PAYLOAD_KEYS = {
    "five_hour",
    "seven_day",
    "seven_day_opus",
    "seven_day_sonnet",
    "extra_usage",
}


async def _create_api_key(name: str, **kwargs: Any) -> str:
    async with SessionLocal() as session:
        created = await ApiKeysService(ApiKeysRepository(session)).create_key(
            ApiKeyCreateData(name=name, allowed_models=None, limits=[], **kwargs)
        )
    return created.key


async def _set_api_key_auth_enabled(enabled: bool) -> None:
    settings_cache = get_settings_cache()
    await settings_cache.get()
    async with SessionLocal() as session:
        settings = await session.get(DashboardSettings, 1)
        assert settings is not None
        settings.api_key_auth_enabled = enabled
        await session.commit()
    await settings_cache.invalidate()
    assert (await settings_cache.get()).api_key_auth_enabled is enabled


@pytest.mark.asyncio
async def test_anthropic_oauth_usage_requires_api_key(async_client) -> None:
    response = await async_client.get("/api/oauth/usage")
    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("path", _OAUTH_USAGE_PATHS)
@pytest.mark.parametrize("auth_state", ["missing", "invalid", "expired"])
async def test_anthropic_oauth_usage_denies_unusable_credentials(async_client, path: str, auth_state: str) -> None:
    """Pooled Claude quota is never served to a caller without a usable key."""
    headers: dict[str, str] = {}
    if auth_state == "invalid":
        headers["Authorization"] = "Bearer sk-clb-not-a-real-key"
    elif auth_state == "expired":
        expired = await _create_api_key(
            f"oauth-usage-expired-{path}",
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        headers["Authorization"] = f"Bearer {expired}"

    response = await async_client.get(path, headers=headers)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_api_key"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", _OAUTH_USAGE_PATHS)
async def test_anthropic_oauth_usage_requires_key_even_when_global_auth_is_disabled(async_client, path: str) -> None:
    """The documented contract: always-required auth, same as ``GET /v1/usage``.

    ``api_key_auth_enabled`` defaults to ``False``, under which ordinary proxy
    routes serve anonymous local callers. Binding this route to the ordinary
    proxy dependency instead of the always-required usage dependency would
    therefore publish pooled Claude quota to any caller that reaches the port.
    This asserts the toggle explicitly rather than relying on the ambient
    default, so the contract stays pinned if that default ever flips.
    """
    await _set_api_key_auth_enabled(False)

    anonymous = await async_client.get(path)

    assert anonymous.status_code == 401
    assert anonymous.json()["error"]["code"] == "invalid_api_key"

    plain_key = await _create_api_key(f"oauth-usage-global-auth-off-{path}")
    authorized = await async_client.get(path, headers={"Authorization": f"Bearer {plain_key}"})

    assert authorized.status_code == 200
    assert set(authorized.json()) == _ANTHROPIC_PAYLOAD_KEYS


@pytest.mark.asyncio
@pytest.mark.parametrize("path", _OAUTH_USAGE_PATHS)
async def test_anthropic_oauth_usage_serves_authorized_callers_on_both_variants(async_client, path: str) -> None:
    plain_key = await _create_api_key(f"oauth-usage-authorized-{path}")

    response = await async_client.get(path, headers={"Authorization": f"Bearer {plain_key}"})

    assert response.status_code == 200
    assert set(response.json()) == _ANTHROPIC_PAYLOAD_KEYS


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
