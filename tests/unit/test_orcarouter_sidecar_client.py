from __future__ import annotations

import pytest

from app.core.clients.claude_sidecar import SidecarPrefix
from app.core.clients.orcarouter_sidecar import (
    OrcaRouterSidecarClient,
    OrcaRouterSidecarConfig,
    OrcaRouterSidecarError,
    OrcaRouterSidecarUnavailableError,
    get_orcarouter_sidecar_client,
    reset_orcarouter_sidecar_client_cache,
)

pytestmark = pytest.mark.unit


def _config(**overrides) -> OrcaRouterSidecarConfig:
    values = {
        "enabled": True,
        "base_url": "https://api.orcarouter.ai/v1",
        "api_key": None,
        "prefixes": (SidecarPrefix(prefix="orcarouter/", strip=False),),
        "connect_timeout_seconds": 8.0,
        "request_timeout_seconds": 600.0,
        "models_cache_ttl_seconds": 60.0,
    }
    values.update(overrides)
    return OrcaRouterSidecarConfig(**values)


class _FakeContent:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def iter_chunked(self, _size: int):
        for chunk in self._chunks:
            yield chunk


class _FakeResponse:
    def __init__(self, status: int, text: str, chunks: list[bytes] | None = None) -> None:
        self.status = status
        self._text = text
        self.content = _FakeContent(chunks or [])

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def text(self) -> str:
        return self._text


class _FakeSession:
    def __init__(
        self,
        *,
        get_response: _FakeResponse | Exception | None = None,
        post_response: _FakeResponse | Exception | None = None,
    ) -> None:
        self.get_response = get_response
        self.post_response = post_response
        self.last_url = None
        self.last_headers = None
        self.last_json = None

    def get(self, url: str, *, headers, timeout):
        self.last_url = url
        self.last_headers = headers
        if isinstance(self.get_response, Exception):
            raise self.get_response
        assert self.get_response is not None
        return self.get_response

    def post(self, url: str, *, headers, json, timeout):
        self.last_url = url
        self.last_headers = headers
        self.last_json = json
        if isinstance(self.post_response, Exception):
            raise self.post_response
        assert self.post_response is not None
        return self.post_response


class _Lease:
    def __init__(self, session: _FakeSession) -> None:
        self.session = session

    async def __aenter__(self) -> _FakeSession:
        return self.session

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


@pytest.mark.asyncio
async def test_list_models_sends_bearer_key_and_parses_models(monkeypatch) -> None:
    session = _FakeSession(
        get_response=_FakeResponse(
            200,
            '{"object":"list","data":[{"id":"orcarouter/auto","created":123,"owned_by":"deepseek"}]}',
        )
    )
    monkeypatch.setattr("app.core.clients.orcarouter_sidecar.lease_http_session", lambda: _Lease(session))
    client = OrcaRouterSidecarClient(_config(api_key="orcarouter-key"))

    models = await client.list_models()

    assert session.last_url == "https://api.orcarouter.ai/v1/models"
    assert session.last_headers["Authorization"] == "Bearer orcarouter-key"
    assert session.last_headers["User-Agent"] == "codex-lb/orcarouter-sidecar"
    assert session.last_headers["HTTP-Referer"] == "https://github.com/vitalNohj/codex-lb"
    assert session.last_headers["X-Title"] == "codex-lb"
    assert [model.id for model in models] == ["orcarouter/auto"]
    assert models[0].created == 123
    assert models[0].owned_by == "deepseek" or models[0].owned_by == "orcarouter"


@pytest.mark.asyncio
async def test_list_models_parses_pricing_and_updates_registry(monkeypatch) -> None:
    from app.core.usage.runtime_pricing import get_runtime_pricing_registry

    get_runtime_pricing_registry().clear()
    session = _FakeSession(
        get_response=_FakeResponse(
            200,
            '{"object":"list","data":['
            '{"id":"vendor/model-x","pricing":{"prompt":"0.0000008","completion":"0.000004",'
            '"input_cache_read":"0.0000002"}},'
            '{"id":"vendor/model-y","pricing":{"prompt":"bad","completion":"0.000004"}},'
            '{"id":"vendor/model-z"}'
            "]}",
        )
    )
    monkeypatch.setattr("app.core.clients.orcarouter_sidecar.lease_http_session", lambda: _Lease(session))
    client = OrcaRouterSidecarClient(_config(api_key="key"))

    models = await client.list_models()

    by_id = {model.id: model for model in models}
    assert by_id["vendor/model-x"].pricing is not None
    assert by_id["vendor/model-x"].pricing.input_per_1m == pytest.approx(0.8)
    assert by_id["vendor/model-x"].pricing.output_per_1m == pytest.approx(4.0)
    assert by_id["vendor/model-x"].pricing.cached_input_per_1m == pytest.approx(0.2)
    # Unparseable / missing pricing -> no runtime price, fetch still succeeds.
    assert by_id["vendor/model-y"].pricing is None
    assert by_id["vendor/model-z"].pricing is None

    registry = get_runtime_pricing_registry()
    assert registry.runtime_pricing_for_model("vendor/model-x") is not None
    assert registry.runtime_pricing_for_model("vendor/model-y") is None


@pytest.mark.asyncio
async def test_chat_completion_relays_error_envelope(monkeypatch) -> None:
    session = _FakeSession(
        post_response=_FakeResponse(401, '{"error":{"message":"expired","type":"authentication_error"}}')
    )
    monkeypatch.setattr("app.core.clients.orcarouter_sidecar.lease_http_session", lambda: _Lease(session))
    client = OrcaRouterSidecarClient(_config(api_key="key"))

    with pytest.raises(OrcaRouterSidecarError) as exc_info:
        await client.chat_completion({"model": "orcarouter/auto", "messages": []})

    assert exc_info.value.status_code == 401
    assert exc_info.value.message == "expired"


@pytest.mark.asyncio
async def test_transport_error_becomes_unavailable(monkeypatch) -> None:
    session = _FakeSession(get_response=OSError("boom"))
    monkeypatch.setattr("app.core.clients.orcarouter_sidecar.lease_http_session", lambda: _Lease(session))
    client = OrcaRouterSidecarClient(_config(api_key="key"))

    with pytest.raises(OrcaRouterSidecarUnavailableError):
        await client.list_models()


@pytest.fixture(autouse=True)
def _clear_orcarouter_client_cache():
    reset_orcarouter_sidecar_client_cache()
    yield
    reset_orcarouter_sidecar_client_cache()


def test_client_cache_returns_the_same_instance_for_an_unchanged_config() -> None:
    config = _config(api_key="key")

    first = get_orcarouter_sidecar_client(config)
    second = get_orcarouter_sidecar_client(_config(api_key="key"))

    # Same instance means ``list_models_cached`` keeps its TTL state, so a
    # second ``GET /v1/models`` inside the TTL costs no upstream round trip.
    assert first is second


@pytest.mark.parametrize(
    "changed",
    [
        {"api_key": "rotated-key"},
        {"base_url": "https://orca.internal/v1"},
        {"models_cache_ttl_seconds": 5.0},
        {"prefixes": (SidecarPrefix(prefix="orca-", strip=True),)},
        {"enabled": False},
    ],
)
def test_client_cache_evicts_on_any_config_change(changed) -> None:
    first = get_orcarouter_sidecar_client(_config(api_key="key"))

    second = get_orcarouter_sidecar_client(_config(**{"api_key": "key", **changed}))

    # A settings change must never be served by a client holding the old
    # credential, base URL, or cached model list.
    assert second is not first
    assert get_orcarouter_sidecar_client(_config(**{"api_key": "key", **changed})) is second


@pytest.mark.asyncio
async def test_client_cache_eviction_drops_the_previous_credential_and_models(monkeypatch) -> None:
    session = _FakeSession(get_response=_FakeResponse(200, '{"data":[{"id":"orcarouter/auto"}]}'))
    monkeypatch.setattr("app.core.clients.orcarouter_sidecar.lease_http_session", lambda: _Lease(session))

    stale = get_orcarouter_sidecar_client(_config(api_key="old-key"))
    assert await stale.list_models_cached() != []

    rotated = get_orcarouter_sidecar_client(_config(api_key="new-key"))

    assert rotated.config.api_key == "new-key"
    assert rotated._models_cache is None
    reset_orcarouter_sidecar_client_cache()
    assert get_orcarouter_sidecar_client(_config(api_key="new-key")) is not rotated


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_chat_requests_opt_into_the_orcarouter_billed_cost(monkeypatch, stream) -> None:
    """Both chat paths must send ``X-OrcaRouter-Include-Cost``.

    Absent the header OrcaRouter omits ``usage.cost_usd`` entirely, and absence
    means "not requested" rather than "free"
    (docs.orcarouter.ai/operations/per-request-cost).
    """

    session = _FakeSession(post_response=_FakeResponse(200, "{}", chunks=[b"data: [DONE]\n\n"]))
    monkeypatch.setattr("app.core.clients.orcarouter_sidecar.lease_http_session", lambda: _Lease(session))
    client = OrcaRouterSidecarClient(_config(api_key="orcarouter-key"))
    payload = {"model": "orcarouter/auto", "messages": []}

    if stream:
        async with client.stream_chat_completion(payload) as chunks:
            async for _chunk in chunks:
                pass
    else:
        await client.chat_completion(payload)

    assert session.last_headers["X-OrcaRouter-Include-Cost"] == "true"


@pytest.mark.asyncio
async def test_model_listing_also_opts_into_cost_without_changing_other_headers(monkeypatch) -> None:
    session = _FakeSession(get_response=_FakeResponse(200, '{"data":[]}'))
    monkeypatch.setattr("app.core.clients.orcarouter_sidecar.lease_http_session", lambda: _Lease(session))

    await OrcaRouterSidecarClient(_config(api_key="orcarouter-key")).list_models()

    assert session.last_headers["X-OrcaRouter-Include-Cost"] == "true"
    assert session.last_headers["Authorization"] == "Bearer orcarouter-key"
    assert session.last_headers["X-Title"] == "codex-lb"
