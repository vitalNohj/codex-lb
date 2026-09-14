"""Settings save -> real loader -> registered HTTP quota endpoint -> fake upstream.

MAIN's recovery ruling is explicit that full recovery validation must exercise
this whole chain, and that "a private route fixture, missing-registration skip,
or historical test count" does not count as that evidence. So every test here
issues a real HTTP request against the assembled application and reaches a fake
upstream over a real loopback socket. Nothing imports the router directly or
mounts a private app.

The distinction matters because of what it caught. ``app/modules/opencode_go/``
ships a complete quota surface - parser, service, cache and an ``api.py``
declaring ``GET /quota`` - and its own unit tests pass. But the router is never
included in ``app/main.py``, so the endpoint does not exist on the running
application. An import-level or route-name check would have called that working.

MAIN's ruling anticipated exactly this: "Preservation is not functional
restoration: without dependency injection and router inclusion, the quota
endpoint is unreachable." These tests are the executable form of that sentence.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from app.core.config.settings import get_settings
from tests.fixtures.opencode_go_upstream import FakeOpenCodeGoUpstream

pytestmark = pytest.mark.integration

QUOTA_PATH = "/api/opencode-go/quota"
UPSTREAM_KEY = "sk-go-quota-Zq7SvT2pLm9KdR4xHn8B"


@pytest.fixture
def opencode_go_capability_enabled(monkeypatch):
    monkeypatch.setenv("CODEX_LB_OPENCODE_GO_SIDECAR_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def go_upstream(monkeypatch):
    """A real loopback upstream, reached without weakening the base-URL guard.

    Only the final URL handed to the HTTP client is rewritten from the
    ``opencode.ai`` host to the loopback fake. Everything upstream of that -
    settings persistence, the real config loader, credential decryption, and
    ``opencode_go_request_headers`` - runs exactly as in production, so the
    credential and user-agent assertions are meaningful rather than staged.
    """
    upstream = FakeOpenCodeGoUpstream(
        api_key=UPSTREAM_KEY,
        model_ids=("glm-5.3",),
        strict_auth_by_endpoint=False,
    )
    await upstream.start()

    import app.modules.opencode_go.service as quota_service

    original = quota_service.OpenCodeGoClient

    class _RedirectedClient(original):  # type: ignore[misc, valid-type]
        @property
        def base_url(self) -> str:
            return upstream.base_url

    monkeypatch.setattr(quota_service, "OpenCodeGoClient", _RedirectedClient)
    try:
        yield upstream
    finally:
        await upstream.stop()


def _registered_paths(client) -> list[str]:
    app = client._transport.app  # noqa: SLF001 - the app under test, by design
    return [getattr(route, "path", "") for route in app.routes]


async def _save_settings(client) -> None:
    """Configure through the real settings API, as the Settings page does.

    The production Go base URL is stored deliberately. ``is_opencode_go_base_url``
    pins the host to ``opencode.ai`` so a Go key can never be pointed at the Zen
    path (which would bill pay-as-you-go credits) or at an unrelated host. That
    guard is correct and is **not** relaxed to make testing easier.

    The fake upstream is reached by redirecting the *transport* instead - see
    ``redirect_upstream_to_fake`` - so the stored configuration, the real loader,
    the real credential decryption and the real request headers all stay on the
    production path under test.
    """
    response = await client.put(
        "/api/settings",
        json={
            "opencodeGoSidecarEnabled": True,
            "opencodeGoSidecarBaseUrl": "https://opencode.ai/zen/go/v1",
            "opencodeGoSidecarApiKey": UPSTREAM_KEY,
        },
    )
    assert response.status_code == 200, response.text


def test_the_quota_route_is_registered_on_the_running_application(async_client):
    """Reachability, asserted on the assembled app rather than on an import.

    This is the check MAIN asked for and it currently fails: the quota router
    exists and its unit tests pass, but ``app/main.py`` never includes it, so
    there is no such endpoint on the running application.
    """
    paths = _registered_paths(async_client)
    opencode_paths = sorted(path for path in paths if "opencode" in path)

    assert QUOTA_PATH in paths, (
        f"{QUOTA_PATH} is not registered on the application. The quota module "
        "(app/modules/opencode_go/api.py) declares the route and its unit tests "
        "pass, but app/main.py does not include its router, so the endpoint is "
        f"unreachable. Registered OpenCode paths: {opencode_paths}"
    )


@pytest.mark.asyncio
async def test_a_configured_integration_serves_quota_over_http_from_the_upstream(
    async_client, opencode_go_capability_enabled, go_upstream
):
    """The full chain MAIN specified, end to end.

    Settings save -> the real config loader -> the registered HTTP endpoint ->
    the fake upstream over loopback -> a normalized quota response.
    """
    await _save_settings(async_client)

    response = await async_client.get(QUOTA_PATH)
    assert response.status_code == 200, (
        f"{QUOTA_PATH} did not serve a configured integration: {response.status_code} {response.text}"
    )
    body = response.json()

    # The upstream was really consulted; this is not a cached or synthesized answer.
    assert go_upstream.requests_for("/v1/usage"), (
        "the quota endpoint answered without ever calling the upstream /usage route"
    )

    assert body["status"] == "ok", f"expected a served quota, got {body}"
    # Uncertainty preserved exactly as the quota contract requires.
    assert body["scope"] == "unknown"
    assert body["modelBreakdownAvailable"] is False
    assert body["models"] == []

    windows = {window["key"]: window for window in body["windows"]}
    assert set(windows) == {"five_hour", "weekly", "monthly"}
    assert windows["five_hour"]["upstreamKey"] == "rolling"
    assert windows["five_hour"]["percentUsed"] == 42

    # The credential never appears in a dashboard-facing payload.
    assert UPSTREAM_KEY not in response.text


@pytest.mark.asyncio
async def test_the_upstream_call_carries_the_configured_credential_and_an_honest_agent(
    async_client, opencode_go_capability_enabled, go_upstream
):
    """The background read must authenticate and identify itself truthfully.

    Two third-party projects had their background ``/models`` and ``/usage``
    calls flagged by OpenCode for sending a generic or browser user agent. The
    Go docs ask a client to identify itself with its own.
    """
    await _save_settings(async_client)
    response = await async_client.get(QUOTA_PATH)
    assert response.status_code == 200, response.text

    usage_requests = go_upstream.requests_for("/v1/usage")
    assert usage_requests, "no upstream /usage request was made"
    record = usage_requests[-1]

    assert record.header("authorization") == f"Bearer {UPSTREAM_KEY}"
    user_agent = record.header("user-agent") or ""
    assert user_agent.startswith("codex-lb/")
    assert "Mozilla" not in user_agent, "a browser user agent was copied from the prior art"
    assert "opencode-cli" not in user_agent


@pytest.mark.asyncio
async def test_an_unconfigured_integration_reports_not_configured_without_calling_upstream(
    async_client, opencode_go_capability_enabled, go_upstream
):
    """No credential, no traffic. The status says so rather than inventing zeros."""
    response = await async_client.get(QUOTA_PATH)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["status"] in {"not_configured", "disabled"}
    # Unknown, not zero and not full.
    assert body["windows"] == []
    assert go_upstream.requests == [], "an unconfigured integration contacted the upstream"


@pytest.mark.asyncio
async def test_an_upstream_rejection_is_reported_as_unauthorized_with_no_windows(
    async_client, opencode_go_capability_enabled, go_upstream
):
    """A rejected key must not render as an exhausted subscription."""
    await _save_settings(async_client)
    go_upstream.script("/v1/usage", status=401, repeat=None)

    response = await async_client.get(QUOTA_PATH)
    assert response.status_code == 200, (
        "the dashboard endpoint proxied an upstream failure status; it must "
        "always answer 200 with the failure described in `status`"
    )
    body = response.json()

    assert body["status"] == "unauthorized"
    assert body["windows"] == [], "a rejected key must not produce windows"
    assert UPSTREAM_KEY not in response.text


@pytest.mark.asyncio
async def test_an_empty_usage_body_is_unavailable_rather_than_zero_usage(
    async_client, opencode_go_capability_enabled, go_upstream
):
    """Endpoint reachable, content absent. Distinct from zero, and from a failure."""
    await _save_settings(async_client)
    go_upstream.usage_windows = None  # 200 with `{}`

    response = await async_client.get(QUOTA_PATH)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["status"] != "ok", "an empty body was reported as a good reading"
    assert body["windows"] == []
    assert body["scope"] == "unknown"
