"""CLIProxyAPI's Codex-client catalog supplies each listed model's real limits.

The fixtures are CLIProxyAPI v8.0.36 output: ``GET /v1/models`` and
``GET /v1/models?client_version=0.163.0`` for a registry with one xAI login
(prefix ``lb5dc882f41e``) and one Claude login (prefix ``lb0881c9d437``). The
catalog fixture keeps only the fields that matter here.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from app.core.clients.claude_sidecar import (
    ClaudeSidecarClient,
    ClaudeSidecarConfig,
    ClaudeSidecarUnavailableError,
    PublishedModelLimits,
    SidecarPrefix,
)

pytestmark = pytest.mark.unit

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
_PLAIN = (_FIXTURES / "cliproxy_v8_0_36_models.json").read_text()
_CATALOG = (_FIXTURES / "cliproxy_v8_0_36_codex_client_models.json").read_text()


def _config(**overrides) -> ClaudeSidecarConfig:
    values = {
        "enabled": True,
        "base_url": "http://127.0.0.1:8317",
        "api_key": "sidecar-key",
        "prefixes": (SidecarPrefix(prefix="claude", strip=False), SidecarPrefix(prefix="cc/", strip=True)),
        "connect_timeout_seconds": 8.0,
        "request_timeout_seconds": 600.0,
        "models_cache_ttl_seconds": 60.0,
    }
    values.update(overrides)
    return ClaudeSidecarConfig(**values)


class _FakeResponse:
    def __init__(self, status: int, text: str) -> None:
        self.status = status
        self._text = text

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def text(self) -> str:
        return self._text


class _RoutedSession:
    """Answers the plain listing and the catalog separately."""

    def __init__(
        self,
        *,
        plain: _FakeResponse | Exception,
        catalog: _FakeResponse | Exception,
    ) -> None:
        self.plain = plain
        self.catalog = catalog
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.catalog_timeouts: list[float | None] = []

    def get(self, url: str, *, headers, timeout):
        self.calls.append((url, dict(headers)))
        parts = urlsplit(url)
        assert parts.path == "/v1/models", url
        if "client_version" in parse_qs(parts.query):
            self.catalog_timeouts.append(timeout.total)
            response = self.catalog
        else:
            response = self.plain
        if isinstance(response, Exception):
            raise response
        return response


class _Lease:
    def __init__(self, session: _RoutedSession) -> None:
        self.session = session

    async def __aenter__(self) -> _RoutedSession:
        return self.session

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


def _install(monkeypatch, session: _RoutedSession) -> None:
    monkeypatch.setattr("app.core.clients.claude_sidecar.lease_http_session", lambda: _Lease(session))


def _catalog_calls(session: _RoutedSession) -> int:
    return sum(1 for url, _ in session.calls if "client_version=" in url)


@pytest.mark.asyncio
async def test_catalog_limits_are_keyed_by_the_listed_id(monkeypatch) -> None:
    session = _RoutedSession(plain=_FakeResponse(200, _PLAIN), catalog=_FakeResponse(200, _CATALOG))
    _install(monkeypatch, session)

    limits = await ClaudeSidecarClient(_config()).list_published_model_limits()

    url, headers = session.calls[-1]
    assert url == "http://127.0.0.1:8317/v1/models?client_version=0.163.0"
    assert headers["Authorization"] == "Bearer sidecar-key"
    assert "/v0/management" not in url
    # Bare and per-login ``lb<hash>/`` ids are separate catalog rows.
    assert limits["grok-4.7"] == PublishedModelLimits(context_window=500_000, max_output_tokens=500_000)
    assert limits["lb5dc882f41e/grok-4.7"] == limits["grok-4.7"]
    assert limits["grok-4.7-build-fast"] == PublishedModelLimits(500_000, 500_000)
    assert limits["lb5dc882f41e/grok-4.7-build-fast"] == limits["grok-4.7-build-fast"]
    assert limits["grok-4.20-0309-reasoning"] == PublishedModelLimits(2_000_000, 65_536)
    assert limits["claude-opus-5-5"] == PublishedModelLimits(1_000_000, 128_000)
    assert limits["lb0881c9d437/claude-sonnet-4-5-20250929"] == PublishedModelLimits(200_000, 64_000)


@pytest.mark.asyncio
async def test_catalog_placeholder_window_is_not_a_published_limit(monkeypatch) -> None:
    """Image, video and TTS rows carry the template's 272000 with no ``max_tokens``.

    CLIProxyAPI knows no window for them, so they publish nothing and keep the
    listing's existing fallback.
    """

    session = _RoutedSession(plain=_FakeResponse(200, _PLAIN), catalog=_FakeResponse(200, _CATALOG))
    _install(monkeypatch, session)

    limits = await ClaudeSidecarClient(_config()).list_published_model_limits()

    catalog = {entry["slug"]: entry for entry in json.loads(_CATALOG)["models"]}
    for media_id in ("grok-imagine-image", "lb5dc882f41e/grok-imagine-video-1.5", "grok-voice-tts-1.0"):
        assert catalog[media_id]["context_window"] == 272_000
        assert "max_tokens" not in catalog[media_id]
        assert media_id not in limits


@pytest.mark.asyncio
async def test_cached_listing_carries_published_limits(monkeypatch) -> None:
    session = _RoutedSession(plain=_FakeResponse(200, _PLAIN), catalog=_FakeResponse(200, _CATALOG))
    _install(monkeypatch, session)

    models = {model.id: model for model in await ClaudeSidecarClient(_config()).list_models_cached()}

    # The catalog never changes which models are listed.
    assert sorted(models) == sorted(entry["id"] for entry in json.loads(_PLAIN)["data"])
    assert models["lb5dc882f41e/grok-4.7"].context_window == 500_000
    assert models["lb5dc882f41e/grok-4.7"].max_output_tokens == 500_000
    assert models["grok-3-mini"].context_window == 131_072
    assert models["grok-3-mini"].max_output_tokens == 32_768
    assert models["grok-imagine-image"].context_window is None
    assert models["grok-imagine-image"].max_output_tokens is None
    assert models["claude-opus-5-5"].owned_by == "anthropic"
    assert models["claude-opus-5-5"].raw == next(
        entry for entry in json.loads(_PLAIN)["data"] if entry["id"] == "claude-opus-5-5"
    )


@pytest.mark.parametrize(
    "catalog",
    [
        _FakeResponse(500, '{"error":{"message":"boom"}}'),
        _FakeResponse(200, '{"data":[]}'),
        _FakeResponse(200, "not json"),
        _FakeResponse(200, '{"models":null}'),
        asyncio.TimeoutError(),
        OSError("connection refused"),
    ],
    ids=["http-500", "no-models-key", "not-json", "models-null", "timeout", "transport"],
)
@pytest.mark.asyncio
async def test_catalog_failure_keeps_the_listing(monkeypatch, catalog) -> None:
    session = _RoutedSession(plain=_FakeResponse(200, _PLAIN), catalog=catalog)
    _install(monkeypatch, session)

    models = await ClaudeSidecarClient(_config()).list_models_cached()

    assert len(models) == len(json.loads(_PLAIN)["data"])
    assert all(model.context_window is None and model.max_output_tokens is None for model in models)


@pytest.mark.asyncio
async def test_catalog_crash_keeps_the_listing(monkeypatch) -> None:
    """Even an unexpected error from the enrichment step leaves the listing whole."""

    session = _RoutedSession(plain=_FakeResponse(200, _PLAIN), catalog=_FakeResponse(200, _CATALOG))
    _install(monkeypatch, session)
    client = ClaudeSidecarClient(_config())

    async def crash():
        raise RuntimeError("unexpected")

    monkeypatch.setattr(client, "_published_model_limits_cached", crash)

    models = await client.list_models_cached()

    assert len(models) == len(json.loads(_PLAIN)["data"])
    assert all(model.context_window is None for model in models)


@pytest.mark.asyncio
async def test_listing_failure_still_returns_nothing(monkeypatch) -> None:
    session = _RoutedSession(plain=OSError("down"), catalog=_FakeResponse(200, _CATALOG))
    _install(monkeypatch, session)

    assert await ClaudeSidecarClient(_config()).list_models_cached() == []


@pytest.mark.asyncio
async def test_catalog_is_cached_across_clients_for_the_ttl(monkeypatch) -> None:
    """A client is built per request, so the catalog cache must outlive one."""

    session = _RoutedSession(plain=_FakeResponse(200, _PLAIN), catalog=_FakeResponse(200, _CATALOG))
    _install(monkeypatch, session)

    await ClaudeSidecarClient(_config()).list_models_cached()
    await ClaudeSidecarClient(_config()).list_models_cached()

    assert _catalog_calls(session) == 1


@pytest.mark.asyncio
async def test_catalog_cache_is_per_endpoint(monkeypatch) -> None:
    session = _RoutedSession(plain=_FakeResponse(200, _PLAIN), catalog=_FakeResponse(200, _CATALOG))
    _install(monkeypatch, session)

    await ClaudeSidecarClient(_config()).list_models_cached()
    await ClaudeSidecarClient(_config(api_key="rotated-key")).list_models_cached()

    assert _catalog_calls(session) == 2


@pytest.mark.asyncio
async def test_catalog_refresh_failure_serves_last_good_limits(monkeypatch) -> None:
    session = _RoutedSession(plain=_FakeResponse(200, _PLAIN), catalog=_FakeResponse(200, _CATALOG))
    _install(monkeypatch, session)
    config = _config(models_cache_ttl_seconds=0)

    await ClaudeSidecarClient(config).list_models_cached()
    session.catalog = OSError("down")
    models = {model.id: model for model in await ClaudeSidecarClient(config).list_models_cached()}

    assert _catalog_calls(session) == 2
    assert models["grok-4.7"].context_window == 500_000


@pytest.mark.asyncio
async def test_failed_catalog_is_not_retried_within_the_ttl(monkeypatch) -> None:
    """A catalog that stays down costs one attempt per TTL, not one per listing."""

    session = _RoutedSession(plain=_FakeResponse(200, _PLAIN), catalog=asyncio.TimeoutError())
    _install(monkeypatch, session)

    for _ in range(3):
        models = await ClaudeSidecarClient(_config()).list_models_cached()
        assert all(model.context_window is None for model in models)

    assert _catalog_calls(session) == 1


@pytest.mark.asyncio
async def test_failed_refresh_keeps_last_good_limits_for_the_ttl(monkeypatch) -> None:
    session = _RoutedSession(plain=_FakeResponse(200, _PLAIN), catalog=_FakeResponse(200, _CATALOG))
    _install(monkeypatch, session)
    clock = [1_000.0]
    monkeypatch.setattr("app.core.clients.claude_sidecar.time.monotonic", lambda: clock[0])

    await ClaudeSidecarClient(_config()).list_models_cached()
    session.catalog = OSError("down")
    clock[0] += 61
    await ClaudeSidecarClient(_config()).list_models_cached()
    clock[0] += 30
    models = {model.id: model for model in await ClaudeSidecarClient(_config()).list_models_cached()}

    assert _catalog_calls(session) == 2
    assert models["grok-4.7"].context_window == 500_000


@pytest.mark.asyncio
async def test_concurrent_failure_does_not_overwrite_a_fresh_refresh(monkeypatch) -> None:
    """A slow failed refresh must not replace limits a concurrent refresh just stored."""

    client = ClaudeSidecarClient(_config())
    success_stored = asyncio.Event()
    calls = 0

    async def fetch():
        nonlocal calls
        calls += 1
        if calls == 1:
            await success_stored.wait()
            raise ClaudeSidecarUnavailableError("timed out")
        return {"grok-4.7": PublishedModelLimits(500_000, 500_000)}

    monkeypatch.setattr(client, "list_published_model_limits", fetch)

    async def succeed():
        limits = await client._published_model_limits_cached()
        success_stored.set()
        return limits

    failed_view, fresh = await asyncio.gather(client._published_model_limits_cached(), succeed())

    assert fresh == {"grok-4.7": PublishedModelLimits(500_000, 500_000)}
    assert failed_view == fresh
    assert await client._published_model_limits_cached() == fresh
    assert calls == 2


@pytest.mark.asyncio
async def test_catalog_timeout_is_bounded(monkeypatch) -> None:
    """The enrichment call never holds ``/v1/models`` for the 600 s request timeout."""

    session = _RoutedSession(plain=_FakeResponse(200, _PLAIN), catalog=_FakeResponse(200, _CATALOG))
    _install(monkeypatch, session)

    await ClaudeSidecarClient(_config()).list_published_model_limits()
    await ClaudeSidecarClient(_config(request_timeout_seconds=3.0)).list_published_model_limits()

    assert session.catalog_timeouts == [10.0, 3.0]
