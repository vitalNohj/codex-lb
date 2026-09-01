from __future__ import annotations

import math

import pytest

from app.core.clients.claude_sidecar import SidecarPrefix
from app.core.clients.openrouter_sidecar import (
    OpenRouterSidecarClient,
    OpenRouterSidecarConfig,
    OpenRouterSidecarError,
    OpenRouterSidecarUnavailableError,
)
from app.core.usage.pricing import ModelPrice
from app.core.usage.runtime_pricing import get_runtime_pricing_registry
from app.modules.proxy.claude_sidecar_dispatch import SidecarUsage, reference_cost_from_sidecar_usage

pytestmark = pytest.mark.unit


def _config(**overrides) -> OpenRouterSidecarConfig:
    values = {
        "enabled": True,
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": None,
        "prefixes": (SidecarPrefix(prefix="deepseek/", strip=False),),
        "connect_timeout_seconds": 8.0,
        "request_timeout_seconds": 600.0,
        "models_cache_ttl_seconds": 60.0,
    }
    values.update(overrides)
    return OpenRouterSidecarConfig(**values)


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
            '{"object":"list","data":[{"id":"deepseek/deepseek-chat","created":123,"owned_by":"deepseek"}]}',
        )
    )
    monkeypatch.setattr("app.core.clients.openrouter_sidecar.lease_http_session", lambda: _Lease(session))
    client = OpenRouterSidecarClient(_config(api_key="openrouter-key"))

    models = await client.list_models()

    assert session.last_url == "https://openrouter.ai/api/v1/models"
    assert session.last_headers["Authorization"] == "Bearer openrouter-key"
    assert [model.id for model in models] == ["deepseek/deepseek-chat"]
    assert models[0].created == 123


@pytest.mark.asyncio
async def test_list_models_parses_pricing_and_updates_registry(monkeypatch) -> None:
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
    monkeypatch.setattr("app.core.clients.openrouter_sidecar.lease_http_session", lambda: _Lease(session))
    client = OpenRouterSidecarClient(_config(api_key="key"))

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
async def test_invalid_published_rates_preserve_finite_runtime_reference_cost(monkeypatch) -> None:
    registry = get_runtime_pricing_registry()
    registry.clear()
    model_ids = ("vendor/nan", "vendor/infinity", "vendor/scaled-overflow")
    registry.update_models(
        [(model_id, ModelPrice(input_per_1m=1.0, output_per_1m=2.0)) for model_id in model_ids],
        provider="openrouter",
    )
    session = _FakeSession(
        get_response=_FakeResponse(
            200,
            '{"object":"list","data":['
            '{"id":"vendor/nan","pricing":{"prompt":"NaN","completion":"0.000002"}},'
            '{"id":"vendor/infinity","pricing":{"prompt":"0.000001","completion":"Infinity"}},'
            '{"id":"vendor/scaled-overflow","pricing":{"prompt":"1e308","completion":"0.000002"}}'
            "]}",
        )
    )
    monkeypatch.setattr("app.core.clients.openrouter_sidecar.lease_http_session", lambda: _Lease(session))

    await OpenRouterSidecarClient(_config(api_key="key")).list_models()

    usage = SidecarUsage(input_tokens=1_000_000, output_tokens=1_000_000)
    for model_id in model_ids:
        price = registry.runtime_pricing_for_model(model_id, provider="openrouter")
        assert price == ModelPrice(input_per_1m=1.0, output_per_1m=2.0)
        reference_cost = reference_cost_from_sidecar_usage(model_id, usage, provider="openrouter")
        assert reference_cost == pytest.approx(3.0)
        assert math.isfinite(reference_cost)


@pytest.mark.asyncio
async def test_chat_completion_relays_error_envelope(monkeypatch) -> None:
    session = _FakeSession(
        post_response=_FakeResponse(401, '{"error":{"message":"expired","type":"authentication_error"}}')
    )
    monkeypatch.setattr("app.core.clients.openrouter_sidecar.lease_http_session", lambda: _Lease(session))
    client = OpenRouterSidecarClient(_config(api_key="key"))

    with pytest.raises(OpenRouterSidecarError) as exc_info:
        await client.chat_completion({"model": "deepseek/deepseek-chat", "messages": []})

    assert exc_info.value.status_code == 401
    assert exc_info.value.message == "expired"


@pytest.mark.asyncio
async def test_transport_error_becomes_unavailable(monkeypatch) -> None:
    session = _FakeSession(get_response=OSError("boom"))
    monkeypatch.setattr("app.core.clients.openrouter_sidecar.lease_http_session", lambda: _Lease(session))
    client = OpenRouterSidecarClient(_config(api_key="key"))

    with pytest.raises(OpenRouterSidecarUnavailableError):
        await client.list_models()
