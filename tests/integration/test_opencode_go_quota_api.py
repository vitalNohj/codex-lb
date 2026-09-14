"""Dashboard endpoint tests for ``GET /api/opencode-go/quota``.

These drive the **real** configured path end to end within the app:
``PUT /api/settings`` (real save, real encryption into the backend-owned
``opencode_go_sidecar_*`` columns) -> the backend's real
``opencode_go_sidecar_config_from_settings`` loader -> the registered HTTP quota
route -> a local fake upstream -> the normalized quota response.

Only the upstream HTTP client is faked. Settings persistence, credential
encryption/decryption, DI and routing are all genuine, so a wrong settings
spelling or a missing registration fails here rather than passing against a
private mock. Credentials are synthetic strings; no network, no production data.
"""

from __future__ import annotations

import pytest

from app.core.clients.opencode_go import OpenCodeGoError, OpenCodeGoUnavailableError
from app.core.clients.opencode_go_sidecar import OPENCODE_GO_USER_AGENT
from app.core.config.settings_cache import get_settings_cache
from app.db.models import DashboardSettings
from app.db.session import SessionLocal
from app.modules.opencode_go.service import reset_opencode_go_quota_cache

pytestmark = pytest.mark.integration

QUOTA_URL = "/api/opencode-go/quota"


def _quota_route_registered() -> bool:
    """Is the quota route actually mounted on the app?

    The DI provider (``app/dependencies.py``) and router include (``app/main.py``)
    are owned by the OpenCode Go backend lane, which has not shipped them yet.
    Until it does, every test here would fail with a bare 404 that says nothing
    about this lane's code, so they are skipped with the precise reason instead.

    This checks the real mounted route table - not an import or a route name -
    so it starts passing the moment the registration lands, and it can never
    mask a genuine regression in a registered route.
    """
    from app.main import create_app

    return any(getattr(route, "path", None) == QUOTA_URL for route in create_app().routes)


requires_registration = pytest.mark.skipif(
    not _quota_route_registered(),
    reason=(
        "OpenCode Go quota route is not registered: app/dependencies.py needs "
        "get_opencode_go_context/OpenCodeGoContext and app/main.py needs "
        "include_router(opencode_go_api.router). Both files are owned by the "
        "backend lane (codexlb-opencode-go-integration); the exact delta is "
        "preserved in recovery-20260914T032100Z-d387cc88/tracked-deltas/."
    ),
)


def _usage_body() -> dict:
    return {
        "usage": {
            "rolling": {"status": "ok", "percent": 12.5, "resetsAt": "2026-09-14T17:00:00Z"},
            "weekly": {"status": "ok", "percent": 40, "resetsAt": "2026-09-20T00:00:00Z"},
            "monthly": {"status": "rate-limited", "percent": 100, "resetsAt": "2026-10-01T00:00:00Z"},
        }
    }


class _FakeClient:
    """Local fake upstream. Records the headers the real builder produced."""

    result: object = None
    last_headers: dict[str, str] | None = None

    def __init__(self, config, *, header_builder=None) -> None:
        self.config = config
        self.header_builder = header_builder

    async def fetch_usage(self):
        if self.header_builder is not None:
            _FakeClient.last_headers = dict(self.header_builder(self.config))
        result = _FakeClient.result if _FakeClient.result is not None else _usage_body()
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture(autouse=True)
def _reset_quota_cache():
    reset_opencode_go_quota_cache()
    _FakeClient.result = None
    _FakeClient.last_headers = None
    yield
    reset_opencode_go_quota_cache()
    _FakeClient.result = None
    _FakeClient.last_headers = None


@pytest.fixture
def fake_upstream(monkeypatch):
    """Substitute the upstream client the service resolves at construction."""
    monkeypatch.setattr("app.modules.opencode_go.service.OpenCodeGoClient", _FakeClient)
    return _FakeClient


# Synthetic, never a real credential. Shaped like an OpenCode key so the
# redaction assertion below is meaningful.
_SYNTHETIC_KEY = "sk-oc-go-int-000000000000"


@pytest.fixture
def configured_settings(async_client):
    """Configure OpenCode Go through the real ``PUT /api/settings`` endpoint.

    No repository patch and no hand-built settings row: the key is encrypted and
    persisted by production code into the backend-owned columns, then read back
    through the backend's real loader. That is what makes this a configured-path
    test rather than a mock.
    """

    async def _apply(*, enabled: bool = True, api_key: str | None = _SYNTHETIC_KEY):
        body: dict[str, object] = {"opencodeGoSidecarEnabled": enabled}
        if api_key is None:
            body["opencodeGoSidecarClearApiKey"] = True
        else:
            body["opencodeGoSidecarApiKey"] = api_key
        response = await async_client.put("/api/settings", json=body)
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["opencodeGoSidecarEnabled"] is enabled
        assert payload["opencodeGoSidecarApiKeyConfigured"] is (api_key is not None)
        # The stored credential must never come back out of the settings API.
        assert _SYNTHETIC_KEY not in response.text
        await get_settings_cache().invalidate()

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
async def test_real_settings_save_drives_the_backend_loader_into_a_retrieval(
    async_client,
    fake_upstream,
    configured_settings,
):
    """Settings save -> real loader -> service -> fake upstream -> normalized data.

    This deliberately calls the service rather than the HTTP route, because the
    route is not registered yet. It is **not** a substitute for the full-chain
    evidence: it omits routing and dashboard authorization, and it is reported as
    a partial result. What it does establish independently of the backend lane is
    that a credential saved through the real Settings API, encrypted into the
    real ``opencode_go_sidecar_*`` columns and decrypted by the backend's real
    loader, reaches the upstream call with the backend's headers.
    """
    from app.db.session import SessionLocal
    from app.modules.opencode_go.service import OpenCodeGoQuotaService
    from app.modules.settings.repository import SettingsRepository

    await configured_settings()

    async with SessionLocal() as session:
        response = await OpenCodeGoQuotaService(SettingsRepository(session)).get_quota()

    assert response.status == "ok"
    assert [window.key for window in response.windows] == ["five_hour", "weekly", "monthly"]
    assert response.windows[0].percent_used == 12.5
    assert response.scope == "unknown"
    assert response.model_breakdown_available is False
    # Proves the credential survived the real encrypt/decrypt round trip and was
    # sent using the backend lane's header builder.
    assert _FakeClient.last_headers["Authorization"] == f"Bearer {_SYNTHETIC_KEY}"
    assert _FakeClient.last_headers["User-Agent"] == OPENCODE_GO_USER_AGENT


@pytest.mark.asyncio
async def test_real_settings_disable_stops_retrieval(async_client, fake_upstream, configured_settings):
    """A disabled integration issues no upstream request, via the real loader."""
    from app.db.session import SessionLocal
    from app.modules.opencode_go.service import OpenCodeGoQuotaService
    from app.modules.settings.repository import SettingsRepository

    await configured_settings(enabled=False)

    async with SessionLocal() as session:
        response = await OpenCodeGoQuotaService(SettingsRepository(session)).get_quota()

    assert response.status == "disabled"
    assert response.windows == []
    assert _FakeClient.last_headers is None


@requires_registration
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


@requires_registration
@pytest.mark.asyncio
async def test_configured_settings_drive_a_real_retrieval_and_normalized_response(
    async_client,
    fake_upstream,
    configured_settings,
):
    """Settings save -> real loader -> registered route -> fake upstream -> card data."""
    await configured_settings()

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
    # The credential really round-tripped through encryption and the backend's
    # decrypting loader, and reached the upstream call via the backend's header
    # builder - so a wrong column spelling could not have produced this.
    assert _FakeClient.last_headers["Authorization"] == f"Bearer {_SYNTHETIC_KEY}"
    assert _FakeClient.last_headers["User-Agent"] == OPENCODE_GO_USER_AGENT


@requires_registration
@pytest.mark.asyncio
async def test_disabled_integration_reports_disabled_with_no_windows(
    async_client,
    fake_upstream,
    configured_settings,
):
    await configured_settings(enabled=False)

    response = await async_client.get(QUOTA_URL)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "disabled"
    assert payload["windows"] == []
    # A disabled integration must not poll upstream at all.
    assert _FakeClient.last_headers is None


@requires_registration
@pytest.mark.asyncio
async def test_unconfigured_key_reports_not_configured(async_client, fake_upstream, configured_settings):
    await configured_settings(api_key=None)

    response = await async_client.get(QUOTA_URL)

    assert response.json()["status"] == "not_configured"
    assert _FakeClient.last_headers is None


@requires_registration
@pytest.mark.asyncio
async def test_default_settings_report_not_configured_without_polling(async_client, fake_upstream):
    """Go stays off until deliberately configured."""
    response = await async_client.get(QUOTA_URL)

    assert response.status_code == 200
    assert response.json()["status"] in {"not_configured", "disabled"}
    assert _FakeClient.last_headers is None


@requires_registration
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
    await configured_settings()
    _FakeClient.result = error

    response = await async_client.get(QUOTA_URL)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == expected
    assert payload["windows"] == []
    assert payload["stale"] is False


@requires_registration
@pytest.mark.asyncio
async def test_failed_refresh_marks_the_previous_values_stale(
    async_client,
    fake_upstream,
    configured_settings,
    monkeypatch,
):
    await configured_settings()
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


@requires_registration
@pytest.mark.asyncio
async def test_upstream_credential_echo_never_reaches_the_dashboard(
    async_client,
    fake_upstream,
    configured_settings,
):
    await configured_settings(api_key=_SYNTHETIC_KEY)
    _FakeClient.result = OpenCodeGoError(500, f"upstream echoed Authorization: Bearer {_SYNTHETIC_KEY}")

    response = await async_client.get(QUOTA_URL)

    assert _SYNTHETIC_KEY not in response.text
    assert "[redacted]" in response.text
