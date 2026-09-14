"""Dashboard endpoint tests for ``GET /api/opencode-go/quota``.

The upstream client is a local fake throughout: no network, no real credential,
no production data. These cover the wire contract (camelCase names, HTTP 200 for
upstream failures) and the endpoint's authorization, which the unit tests cannot.
"""

from __future__ import annotations

import pytest

from app.core.clients.opencode_go import OpenCodeGoError, OpenCodeGoUnavailableError
from app.core.config.settings_cache import get_settings_cache
from app.db.models import DashboardSettings
from app.db.session import SessionLocal
from app.modules.opencode_go.service import reset_opencode_go_quota_cache

pytestmark = pytest.mark.integration

QUOTA_URL = "/api/opencode-go/quota"


def _usage_body() -> dict:
    return {
        "usage": {
            "rolling": {"status": "ok", "percent": 12.5, "resetsAt": "2026-09-14T17:00:00Z"},
            "weekly": {"status": "ok", "percent": 40, "resetsAt": "2026-09-20T00:00:00Z"},
            "monthly": {"status": "rate-limited", "percent": 100, "resetsAt": "2026-10-01T00:00:00Z"},
        }
    }


class _FakeClient:
    result: object = None

    def __init__(self, config) -> None:
        self.config = config

    async def fetch_usage(self):
        result = _FakeClient.result if _FakeClient.result is not None else _usage_body()
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture(autouse=True)
def _reset_quota_cache():
    reset_opencode_go_quota_cache()
    _FakeClient.result = None
    yield
    reset_opencode_go_quota_cache()
    _FakeClient.result = None


@pytest.fixture
def fake_upstream(monkeypatch):
    """Substitute the upstream client the service resolves at construction."""
    monkeypatch.setattr("app.modules.opencode_go.service.OpenCodeGoClient", _FakeClient)
    return _FakeClient


@pytest.fixture
def identity_encryptor(monkeypatch):
    class _Encryptor:
        def decrypt(self, blob: bytes) -> str:
            return blob.decode()

    monkeypatch.setattr("app.modules.opencode_go.config.TokenEncryptor", _Encryptor)


@pytest.fixture
def configured_settings(monkeypatch, identity_encryptor):
    """Give the settings row the columns the provider-integration task owns.

    Patched onto the repository read rather than added as a migration here:
    ``opencode_go_*`` belongs to codexlb-opencode-go-integration, and a second
    migration for the same columns would collide with the owner's schema.
    """

    def _apply(*, enabled: bool = True, api_key: str | None = "sk-oc-go-int-000000000000"):
        class _Row:
            opencode_go_enabled = enabled
            opencode_go_api_key_encrypted = api_key.encode() if api_key else None
            opencode_go_base_url = "https://opencode.ai/zen/go/v1"

        async def _get_or_create(self):
            return _Row()

        monkeypatch.setattr(
            "app.modules.settings.repository.SettingsRepository.get_or_create",
            _get_or_create,
        )

    return _apply


async def _require_dashboard_password() -> None:
    """Turn on dashboard password auth so unauthenticated reads are rejected."""
    async with SessionLocal() as session:
        settings = await session.get(DashboardSettings, 1)
        assert settings is not None
        settings.password_hash = "$2b$12$" + "x" * 53
        await session.commit()
    await get_settings_cache().invalidate()


@pytest.mark.asyncio
async def test_quota_requires_a_dashboard_session(async_client, fake_upstream):
    """The endpoint must sit behind the same auth as every other dashboard route.

    This response is derived from a subscription credential, so it is operator
    data and must never be readable without a session. Settings are left
    unpatched here so the real auth dependency reads the real row.
    """
    await _require_dashboard_password()

    response = await async_client.get(QUOTA_URL)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"
    # An authenticated route on the same app still answers, proving the 401 is
    # this endpoint's auth and not a broken fixture.
    assert (await async_client.get("/api/settings")).status_code == 401


@pytest.mark.asyncio
async def test_quota_returns_camel_case_windows(async_client, fake_upstream, configured_settings):
    configured_settings()

    response = await async_client.get(QUOTA_URL)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["scope"] == "unknown"
    assert payload["modelBreakdownAvailable"] is False
    assert payload["models"] == []
    assert payload["stale"] is False
    assert [window["key"] for window in payload["windows"]] == ["five_hour", "weekly", "monthly"]
    assert payload["windows"][0]["upstreamKey"] == "rolling"
    assert payload["windows"][0]["percentUsed"] == 12.5
    assert payload["windows"][0]["resetsAt"].endswith("Z")
    assert payload["windows"][2]["limitReached"] is True
    # No remaining figure is published: the used direction is a single-source
    # inference and must not gain a false second confirmation.
    assert "percentRemaining" not in payload["windows"][0]


@pytest.mark.asyncio
async def test_disabled_integration_reports_disabled_with_no_windows(
    async_client,
    fake_upstream,
    configured_settings,
):
    configured_settings(enabled=False)

    response = await async_client.get(QUOTA_URL)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "disabled"
    assert payload["windows"] == []


@pytest.mark.asyncio
async def test_unconfigured_key_reports_not_configured(async_client, fake_upstream, configured_settings):
    configured_settings(api_key=None)

    response = await async_client.get(QUOTA_URL)

    assert response.json()["status"] == "not_configured"


@pytest.mark.asyncio
async def test_missing_backend_columns_degrade_instead_of_erroring(async_client, fake_upstream):
    """Before the provider-integration task ships its schema."""
    response = await async_client.get(QUOTA_URL)

    assert response.status_code == 200
    assert response.json()["status"] == "not_configured"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (OpenCodeGoError(401, "bad key"), "unauthorized"),
        (OpenCodeGoError(429, "slow down"), "rate_limited"),
        (OpenCodeGoUnavailableError("connection refused"), "unavailable"),
    ],
)
async def test_upstream_failure_is_http_200_with_an_honest_status(
    async_client,
    fake_upstream,
    configured_settings,
    error,
    expected,
):
    """An upstream outage must not surface as a dashboard 502."""
    configured_settings()
    _FakeClient.result = error

    response = await async_client.get(QUOTA_URL)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == expected
    assert payload["windows"] == []
    assert payload["stale"] is False


@pytest.mark.asyncio
async def test_failed_refresh_marks_the_previous_values_stale(
    async_client,
    fake_upstream,
    configured_settings,
    monkeypatch,
):
    configured_settings()
    from app.modules.opencode_go.service import OpenCodeGoQuotaCache

    cache = OpenCodeGoQuotaCache(ttl_seconds=0.0, failure_ttl_seconds=0.0)
    monkeypatch.setattr("app.modules.opencode_go.service.get_opencode_go_quota_cache", lambda: cache)

    fresh = await async_client.get(QUOTA_URL)
    assert fresh.json()["status"] == "ok"

    _FakeClient.result = OpenCodeGoUnavailableError("connection refused")
    degraded = await async_client.get(QUOTA_URL)

    payload = degraded.json()
    assert degraded.status_code == 200
    assert payload["status"] == "stale"
    assert payload["stale"] is True
    assert payload["staleReason"] == "connection refused"
    # Values survive with a visible marker rather than vanishing or zeroing.
    assert payload["windows"][0]["percentUsed"] == 12.5
    assert payload["checkedAt"] == fresh.json()["checkedAt"]


@pytest.mark.asyncio
async def test_upstream_credential_echo_never_reaches_the_dashboard(
    async_client,
    fake_upstream,
    configured_settings,
):
    key = "sk-oc-go-int-000000000000"
    configured_settings(api_key=key)
    _FakeClient.result = OpenCodeGoError(500, f"upstream echoed Authorization: Bearer {key}")

    response = await async_client.get(QUOTA_URL)

    assert key not in response.text
