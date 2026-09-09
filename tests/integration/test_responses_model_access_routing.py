"""Routing-identity enforcement on the Responses entry points.

The chat handler resolves sidecar routing entries before calling
``validate_model_access``, so a grant scoped to one integration cannot be spent
on another. The Responses handlers must enforce the same contract: permission
is checked against the routing identity that will actually be dispatched,
before quota reservation or upstream dispatch.

Isolation contract for this module
----------------------------------
1. **No application lifespan.** The shared ``async_client`` fixture enters the
   real lifespan (``tests/conftest.py:242``), which calls ``init_http_client()``
   and starts fifteen schedulers plus the live-usage ingestor. None of that is
   needed for an admission check, so this module builds its own client over
   ``create_app()`` with no lifespan context, following the existing pattern in
   ``tests/unit/test_request_id_middleware.py:32-35``. All twenty-one startup
   call sites live inside ``lifespan`` (``app/main.py:327-811``); none appear in
   ``create_app`` (812-1072) or at module scope.

2. **Every reachable outbound dispatch boundary is replaced**, including the
   default native path, *before* any real client or transport is constructed.
   ``_fail_on_outbound_dispatch`` substitutes each one with an explicit test
   failure, so a regression that wrongly admits a request fails loudly at the
   dispatch boundary instead of attempting egress. Correctness of the permission
   denial is what these tests measure; it is deliberately **not** relied on to
   prevent egress.

3. **Environment.** Ambient ``CODEX_LB_*`` sanitation belongs to the parent
   invocation (``env -i``), not to this module, because ``tests/conftest.py``
   already pins the suite's synthetic settings at *import* time - notably
   ``CODEX_LB_DATABASE_URL`` (conftest.py:17-19), which the shared ``engine``
   (conftest.py:43) is built from. This module therefore must **not** repoint
   the database: doing so would aim ``Settings`` at a different SQLite file
   from the engine ``_reset_db_state`` initialises. ``_module_env`` below only
   adds settings conftest does not already fix, and clears the settings cache
   on entry and exit to keep the cache lifecycle consistent.

What is excluded, stated plainly: lifespan-time startup behaviour - schema
init, the bootstrap-token banner, bridge session purges and scheduler startup -
is not covered here. Those are exercised by suites using the shared fixture and
are irrelevant to admission control. ``ProxyService`` remains real, created
lazily by ``get_proxy_service_for_app`` (``app/dependencies.py:293-299``), so
the route, permission and dependency logic under test is genuine.

Run under an OS parent policy that denies all network, including loopback and
Unix sockets; the in-process ASGI transport and file-backed SQLite need none.
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.clients.claude_sidecar import SidecarPrefix
from app.core.config.settings import get_settings
from app.modules.proxy.sidecar_routing import SidecarRoutingEntry
from tests.integration.test_claude_sidecar_routing import (  # noqa: F401
    _create_api_key,
    _enable_api_key_auth,
    fake_sidecar,
    sidecar_enabled,  # noqa: F811
)

pytestmark = pytest.mark.integration

# app/modules/proxy/api.py:450 mounts v1_router at prefix "/v1" (handler
# v1_responses) and api.py:431 mounts router at "/backend-api/codex" (handler
# responses). Both call validate_model_access without routing entries.
CODEX_RESPONSES = "/backend-api/codex/responses"
RESPONSES_PATHS = ["/v1/responses", CODEX_RESPONSES]
ALL_PATHS = ["/v1/chat/completions", *RESPONSES_PATHS]

# Outbound dispatch boundaries reachable from the handlers under test. Each is
# replaced before any real client or transport can be constructed. Sidecar
# client symbols are imported into the proxy module at app/modules/proxy/api.py
# lines 50-53 and constructed at their own call sites.
_OUTBOUND_BOUNDARIES = (
    # Default native (non-sidecar) dispatch - the path a wrongly-admitted
    # request would otherwise take.
    "_stream_responses",
    "_source_responses_response",
    "_source_chat_completion_response",
    "_probe_chat_stream_startup_error",
    # Per-provider sidecar clients.
    "ClaudeSidecarClient",
    "OpenRouterSidecarClient",
    "OrcaRouterSidecarClient",
    "OmniRouteSidecarClient",
    "OllamaSidecarClient",
    "get_orcarouter_sidecar_client",
)


class _SyntheticDispatch(Exception):
    """Raised in place of a real upstream call, carrying the observed boundary.

    ``ASGITransport`` propagates application exceptions to the caller rather
    than turning them into responses, so tests catch this directly instead of
    expecting a status code from it.
    """

    def __init__(self, boundary: str, model: object, provider: object = None) -> None:
        super().__init__(f"synthetic dispatch at {boundary}")
        self.boundary = boundary
        self.model = model
        self.provider = provider


@pytest.fixture(autouse=True)
def dispatch_calls(monkeypatch):
    """Replace every reachable dispatch boundary with a typed synthetic result.

    Recorded before any real client or transport can be constructed, so a
    wrongly-admitted request is observed here rather than attempting egress.
    Applied with ``raising=True``: a renamed symbol fails loudly.
    """
    calls: list[_SyntheticDispatch] = []

    def _boundary(name):
        def _record(*args, **kwargs):
            model = kwargs.get("model")
            if model is None:
                payload = kwargs.get("payload")
                model = getattr(payload, "model", None)
                if model is None:
                    for arg in args:
                        if getattr(arg, "model", None) is not None:
                            model = arg.model
                            break
            config = kwargs.get("config")
            provider = kwargs.get("provider") or getattr(config, "provider", None)
            if args and provider is None:
                provider = getattr(args[0], "provider", None)
            call = _SyntheticDispatch(name, model, provider)
            calls.append(call)
            raise call

        return _record

    for name in _OUTBOUND_BOUNDARIES:
        monkeypatch.setattr(f"app.modules.proxy.api.{name}", _boundary(name), raising=True)
    return calls


@pytest.fixture(autouse=True)
def _module_env(monkeypatch, tmp_path):
    """Settings this module needs beyond what conftest already pins.

    Deliberately does NOT touch ``CODEX_LB_DATABASE_URL``: conftest sets it at
    import time (conftest.py:17-19) and the shared ``engine`` is built from it,
    so repointing it here would desynchronise settings from the initialised
    database. Ambient ``CODEX_LB_*`` sanitation is the parent's job via
    ``env -i``.
    """
    home = tmp_path / "home"
    state = tmp_path / "state"
    cache = tmp_path / "cache"
    tmp = tmp_path / "tmp"
    for path in (home, state, cache, tmp):
        path.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    monkeypatch.setenv("TMPDIR", str(tmp))
    monkeypatch.setenv("CODEX_LB_OTEL_ENABLED", "false")
    monkeypatch.setenv("CODEX_LB_METRICS_ENABLED", "false")

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def lifespan_free_client(_reset_db_state):
    """Real routers over the synthetic DB, without the application lifespan."""
    del _reset_db_state
    from app.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.fixture
def no_reservation(monkeypatch):
    """Observe whether admission reached quota reservation without taking one."""
    reserve = AsyncMock(return_value=None)
    monkeypatch.setattr("app.modules.proxy.api._enforce_request_limits", reserve)
    return reserve


@pytest.fixture
def two_integrations(monkeypatch, dispatch_calls, fake_sidecar):  # noqa: F811
    """Claude on ``cc/`` plus a synthetic OpenRouter integration on ``or/``.

    Declaring ``dispatch_calls`` and ``fake_sidecar`` as parameters fixes the
    ordering: both run before this fixture, so ``fake_sidecar``'s replacement
    of ``ClaudeSidecarClient`` cannot silently undo the dispatch guard. The
    guard is re-applied over that symbol below for the same reason.

    A real second provider entry is registered so cross-provider identity is
    actually measured. Without it, ``cc/slug`` versus ``or/slug`` would differ
    only as raw strings and a denial would prove nothing.
    """
    config = replace(
        fake_sidecar.config,
        prefixes=(
            SidecarPrefix(prefix="claude", strip=False),
            SidecarPrefix(prefix="cp-", strip=True),
            SidecarPrefix(prefix="cc/", strip=True),
        ),
    )
    monkeypatch.setattr("app.modules.proxy.api.load_sidecar_config", AsyncMock(return_value=config))

    openrouter_config = SimpleNamespace(
        enabled=True,
        provider="openrouter",
        prefixes=(SidecarPrefix(prefix="or/", strip=True),),
        full_models=(),
    )
    monkeypatch.setattr(
        "app.modules.proxy.api.load_openrouter_sidecar_config",
        AsyncMock(return_value=openrouter_config),
    )
    monkeypatch.setattr(
        "app.modules.proxy.api.openrouter_routing_entry",
        lambda _config: SidecarRoutingEntry(
            provider="openrouter",
            prefixes=(SidecarPrefix(prefix="or/", strip=True),),
            full_models=(),
        ),
    )

    def _claude_client_guard(*args, **kwargs):
        call = _SyntheticDispatch("ClaudeSidecarClient", None, "claude")
        dispatch_calls.append(call)
        raise call

    monkeypatch.setattr("app.modules.proxy.api.ClaudeSidecarClient", _claude_client_guard)
    return config


def _denied(response) -> bool:
    return response.status_code == 403 and response.json()["error"]["code"] == "model_not_allowed"


def _body(path: str, model: str) -> dict:
    if path.endswith("chat/completions"):
        return {"model": model, "messages": [{"role": "user", "content": "hi"}]}
    return {"model": model, "input": [], "instructions": ""}


async def _post(client, path: str, key, model: str):
    return await client.post(
        path,
        json=_body(path, model),
        headers={"Authorization": f"Bearer {key.key}"},
    )


async def _post_expecting_dispatch(client, path: str, key, model: str) -> _SyntheticDispatch:
    """Assert the request was admitted and reached a dispatch boundary.

    Any other outcome - a 401, a 403, a 500, or a normal response - means the
    request did not reach dispatch, so the permitted case is not proven.
    """
    try:
        response = await _post(client, path, key, model)
    except _SyntheticDispatch as dispatched:
        return dispatched
    raise AssertionError(
        f"{path} did not reach a dispatch boundary for {model!r}: "
        f"status={response.status_code} body={response.text[:200]!r}"
    )


# The route each entry point actually selects for a permitted Claude-owned
# model. Naming the exact boundary per path proves the selected route rather
# than accepting any exception from the boundary list.
#
# Only the chat handler dispatches Claude models through the sidecar client.
# The Responses handlers have no Claude sidecar dispatch, so a permitted
# Claude-owned model there continues down the default Codex path and stops at
# account selection (503 no_accounts) before reaching a dispatch boundary.
# Seeding upstream accounts is outside this module's scope, so those paths
# assert admission past the permission check instead - see
# ``_assert_admitted_past_permission``.
CLAUDE_DISPATCH_BOUNDARY = {
    "/v1/chat/completions": "ClaudeSidecarClient",
    CODEX_RESPONSES: "_stream_responses",
}

# Native (non-sidecar) models: the chat path probes stream startup, and the
# /backend-api/codex Responses path streams directly. /v1/responses stops at
# account selection before any dispatch boundary.
NATIVE_DISPATCH_BOUNDARY = {
    "/v1/chat/completions": "_probe_chat_stream_startup_error",
    CODEX_RESPONSES: "_stream_responses",
}

NO_ACCOUNTS = "no_accounts"


def _admitted_without_account(response) -> bool:
    """Admission succeeded and the request stopped at account selection.

    A 503 ``no_accounts`` is reached only *after* ``validate_model_access``
    allowed the request, so it proves admission without requiring a seeded
    upstream account. It is a specific expected outcome, not a blanket
    "anything that is not a denial".
    """
    if response.status_code != 503:
        return False
    return response.json().get("error", {}).get("code") == NO_ACCOUNTS


async def _assert_admitted_past_permission(client, path: str, key, model: str, calls: list[_SyntheticDispatch]) -> None:
    """Assert admission succeeded on a path with no synthetic dispatch target."""
    try:
        response = await _post(client, path, key, model)
    except _SyntheticDispatch as dispatched:  # pragma: no cover - defensive
        raise AssertionError(
            f"{path} unexpectedly reached dispatch boundary {dispatched.boundary!r}; "
            "update the expected route for this path"
        ) from dispatched
    assert not _denied(response), f"{path} wrongly denied a permitted model {model!r}"
    assert _admitted_without_account(response), (
        f"{path} did not reach account selection for {model!r}: "
        f"status={response.status_code} body={response.text[:200]!r}"
    )
    assert calls == [], f"expected no upstream dispatch, got {[c.boundary for c in calls]}"


def _assert_dispatch(
    dispatched: _SyntheticDispatch,
    calls: list[_SyntheticDispatch],
    *,
    expected_boundary: str,
    expected_provider: str | None,
    expected_model: str | None,
) -> None:
    """Pin the exact synthetic dispatch target, provider and model."""
    assert dispatched.boundary == expected_boundary, (
        f"expected dispatch via {expected_boundary!r}, got {dispatched.boundary!r} "
        f"(provider={dispatched.provider!r} model={dispatched.model!r})"
    )
    if expected_provider is not None:
        assert dispatched.provider == expected_provider, (
            f"expected provider {expected_provider!r}, got {dispatched.provider!r}"
        )
    if expected_model is not None:
        assert dispatched.model == expected_model, (
            f"expected dispatched model {expected_model!r}, got {dispatched.model!r}"
        )
    assert calls == [dispatched], f"expected exactly one dispatch, got {[c.boundary for c in calls]}"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ALL_PATHS)
async def test_grant_on_one_integration_is_not_spent_on_another(
    lifespan_free_client,
    sidecar_enabled,  # noqa: F811
    two_integrations,
    no_reservation,
    dispatch_calls,
    path,  # noqa: F811
):
    """A key scoped to cc/ must not reach the same slug on another integration.

    Both prefixes resolve to real, distinct routing entries here, so this
    measures provider identity rather than a raw string mismatch.
    """
    await _enable_api_key_auth(lifespan_free_client)
    key = await _create_api_key(f"cross-{path.replace('/', '-')}", allowed_models=["cc/custom-slug"])

    response = await _post(lifespan_free_client, path, key, "or/custom-slug")

    assert _denied(response), f"{path} admitted a cross-integration request"
    no_reservation.assert_not_awaited()
    assert dispatch_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ALL_PATHS)
async def test_integration_bound_grant_denies_unrouted_request(
    lifespan_free_client,
    sidecar_enabled,  # noqa: F811
    two_integrations,
    no_reservation,
    dispatch_calls,
    path,  # noqa: F811
):
    """A cc/-bound grant must not admit a bare slug that resolves no route.

    An unrouted request reaches the default dispatch path, which is not the
    integration the operator granted.
    """
    await _enable_api_key_auth(lifespan_free_client)
    key = await _create_api_key(f"unrouted-{path.replace('/', '-')}", allowed_models=["cc/custom-slug"])

    response = await _post(lifespan_free_client, path, key, "custom-slug")

    assert _denied(response), f"{path} admitted an unrouted request against an integration-bound grant"
    no_reservation.assert_not_awaited()
    assert dispatch_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ALL_PATHS)
async def test_bare_claude_grant_is_not_spent_on_another_integration(
    lifespan_free_client,
    sidecar_enabled,  # noqa: F811
    two_integrations,
    no_reservation,
    dispatch_calls,
    path,  # noqa: F811
):
    """The routing-identity gap: a bare Claude-owned grant on another provider.

    With the shipped non-stripping ``claude`` prefix, ``claude-opus-4-7``
    resolves to provider ``claude``, while ``or/claude-opus-4-7`` resolves to
    ``openrouter`` with the same wire model. Provider identity is the only
    thing separating them: the canonical strings are equal, so a handler that
    omits ``routing_entries`` cannot tell them apart and admits the request.
    """
    await _enable_api_key_auth(lifespan_free_client)
    key = await _create_api_key(f"bare-cross-{path.replace('/', '-')}", allowed_models=["claude-opus-4-7"])

    response = await _post(lifespan_free_client, path, key, "or/claude-opus-4-7")

    assert _denied(response), (
        f"{path} admitted a request for another integration's copy of a granted wire model: "
        f"status={response.status_code} body={response.text[:200]!r}"
    )
    no_reservation.assert_not_awaited()
    assert dispatch_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ALL_PATHS)
async def test_separately_versioned_model_is_not_admitted_by_its_family(
    lifespan_free_client,
    sidecar_enabled,  # noqa: F811
    two_integrations,
    no_reservation,
    dispatch_calls,
    path,  # noqa: F811
):
    """A `claude-fable-5` grant must not reach the separately priced 5.1."""
    await _enable_api_key_auth(lifespan_free_client)
    key = await _create_api_key(f"version-{path.replace('/', '-')}", allowed_models=["claude-fable-5"])

    response = await _post(lifespan_free_client, path, key, "cc/claude-fable-5-1")

    assert _denied(response), f"{path} admitted a separately versioned model"
    no_reservation.assert_not_awaited()
    assert dispatch_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ALL_PATHS)
async def test_permitted_same_integration_alias_reaches_dispatch(
    lifespan_free_client,
    sidecar_enabled,  # noqa: F811
    two_integrations,
    no_reservation,
    dispatch_calls,
    path,  # noqa: F811
):
    """Tightening must not revoke a grant: cp- and cc/ share the Claude owner."""
    await _enable_api_key_auth(lifespan_free_client)
    key = await _create_api_key(f"alias-{path.replace('/', '-')}", allowed_models=["cc/claude-fable-5"])

    if path in CLAUDE_DISPATCH_BOUNDARY:
        dispatched = await _post_expecting_dispatch(lifespan_free_client, path, key, "cp-claude-fable-5")
        _assert_dispatch(
            dispatched,
            dispatch_calls,
            expected_boundary=CLAUDE_DISPATCH_BOUNDARY[path],
            expected_provider=None,
            expected_model=None,
        )
    else:
        await _assert_admitted_past_permission(lifespan_free_client, path, key, "cp-claude-fable-5", dispatch_calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ALL_PATHS)
async def test_unprefixed_grant_still_admits_prefixed_request(
    lifespan_free_client,
    sidecar_enabled,  # noqa: F811
    two_integrations,
    no_reservation,
    dispatch_calls,
    path,  # noqa: F811
):
    """An allowlist naming the bare wire model still admits its prefixed form."""
    await _enable_api_key_auth(lifespan_free_client)
    key = await _create_api_key(f"bare-{path.replace('/', '-')}", allowed_models=["claude-fable-5"])

    if path in CLAUDE_DISPATCH_BOUNDARY:
        dispatched = await _post_expecting_dispatch(lifespan_free_client, path, key, "cc/claude-fable-5")
        _assert_dispatch(
            dispatched,
            dispatch_calls,
            expected_boundary=CLAUDE_DISPATCH_BOUNDARY[path],
            expected_provider=None,
            expected_model=None,
        )
    else:
        await _assert_admitted_past_permission(lifespan_free_client, path, key, "cc/claude-fable-5", dispatch_calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ALL_PATHS)
async def test_native_model_request_is_unaffected(
    lifespan_free_client,
    sidecar_enabled,  # noqa: F811
    two_integrations,
    no_reservation,
    dispatch_calls,
    path,  # noqa: F811
):
    """A native (non-sidecar) grant reaches the default dispatch path."""
    await _enable_api_key_auth(lifespan_free_client)
    key = await _create_api_key(f"native-{path.replace('/', '-')}", allowed_models=["gpt-5"])

    if path in NATIVE_DISPATCH_BOUNDARY:
        dispatched = await _post_expecting_dispatch(lifespan_free_client, path, key, "gpt-5")
        _assert_dispatch(
            dispatched,
            dispatch_calls,
            expected_boundary=NATIVE_DISPATCH_BOUNDARY[path],
            expected_provider=None,
            expected_model=None,
        )
    else:
        await _assert_admitted_past_permission(lifespan_free_client, path, key, "gpt-5", dispatch_calls)
