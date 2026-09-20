from __future__ import annotations

import math

import pytest

from app.core.clients.claude_sidecar import SidecarPrefix
from app.core.clients.openai_compat_sidecar import (
    OpenAICompatSidecarClient,
    OpenAICompatSidecarConfig,
    OpenAICompatSidecarError,
    OpenAICompatSidecarUnavailableError,
    get_openai_compat_sidecar_client,
    reset_openai_compat_sidecar_client_cache,
    retain_openai_compat_sidecar_clients,
)
from app.core.usage.external_pricing.catalogs import catalog_from_sidecar_models
from app.core.usage.external_pricing.resolution import UnpricedReason
from app.core.usage.pricing import ModelPrice
from app.core.usage.runtime_pricing import get_runtime_pricing_registry
from app.modules.proxy.claude_sidecar_dispatch import SidecarUsage, reference_cost_from_sidecar_usage

pytestmark = pytest.mark.unit

ENDPOINT_ID = "2c9b8f3a-1e4d-4b7a-9c11-7a0e4d2b1c0a"
PROVIDER_ID = f"openai_compat:{ENDPOINT_ID}"


def _config(**overrides) -> OpenAICompatSidecarConfig:
    values = {
        "endpoint_id": ENDPOINT_ID,
        "name": "Vast",
        "enabled": True,
        "base_url": "https://openai.vast.ai/demo/v1",
        "api_key": None,
        "prefixes": (SidecarPrefix(prefix="vast/", strip=True),),
        "connect_timeout_seconds": 8.0,
        "request_timeout_seconds": 600.0,
        "models_cache_ttl_seconds": 60.0,
    }
    values.update(overrides)
    return OpenAICompatSidecarConfig(**values)


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
async def test_list_models_omits_authorization_when_no_key(monkeypatch) -> None:
    session = _FakeSession(
        get_response=_FakeResponse(
            200,
            '{"object":"list","data":[{"id":"Qwen/Qwen2.5-7B","created":123,"owned_by":"vast"}]}',
        )
    )
    monkeypatch.setattr("app.core.clients.openai_compat_sidecar.lease_http_session", lambda: _Lease(session))
    client = OpenAICompatSidecarClient(_config())

    models = await client.list_models()

    assert session.last_url == "https://openai.vast.ai/demo/v1/models"
    assert "Authorization" not in session.last_headers
    assert session.last_headers["User-Agent"] == "codex-lb/openai-compat"
    assert [model.id for model in models] == ["Qwen/Qwen2.5-7B"]
    assert models[0].owned_by == "vast"


@pytest.mark.asyncio
async def test_list_models_sends_bearer_key_when_present(monkeypatch) -> None:
    session = _FakeSession(
        get_response=_FakeResponse(200, '{"object":"list","data":[{"id":"Qwen/Qwen2.5-7B"}]}')
    )
    monkeypatch.setattr("app.core.clients.openai_compat_sidecar.lease_http_session", lambda: _Lease(session))
    client = OpenAICompatSidecarClient(_config(api_key="vast-key"))

    await client.list_models()

    assert session.last_headers["Authorization"] == "Bearer vast-key"


@pytest.mark.asyncio
async def test_list_models_parses_pricing_under_the_endpoint_provider(monkeypatch) -> None:
    get_runtime_pricing_registry().clear()
    session = _FakeSession(
        get_response=_FakeResponse(
            200,
            '{"object":"list","data":['
            '{"id":"vendor/model-x","pricing":{"prompt":"0.0000008","completion":"0.000004",'
            '"input_cache_read":"0.0000002"}},'
            '{"id":"vendor/model-y","pricing":{"prompt":"bad","completion":"0.000004"}},'
            f'{{"id":"vendor/model-overflow","pricing":{{"prompt":{10**400},"completion":"0.000004"}}}},'
            '{"id":"vendor/model-z"}'
            "]}",
        )
    )
    monkeypatch.setattr("app.core.clients.openai_compat_sidecar.lease_http_session", lambda: _Lease(session))
    client = OpenAICompatSidecarClient(_config())

    models = await client.list_models()

    by_id = {model.id: model for model in models}
    assert by_id["vendor/model-x"].pricing is not None
    assert by_id["vendor/model-x"].pricing.input_per_1m == pytest.approx(0.8)
    assert by_id["vendor/model-y"].pricing is None
    overflow = by_id["vendor/model-overflow"]
    catalog = catalog_from_sidecar_models(
        PROVIDER_ID,
        [(overflow.id, overflow.pricing, overflow.raw.get("pricing") if overflow.raw else None)],
    )
    entry = catalog.exact("vendor/model-overflow")
    assert entry is not None
    assert entry.unpriced_reason is UnpricedReason.UNPARSEABLE

    registry = get_runtime_pricing_registry()
    assert registry.runtime_pricing_for_model("vendor/model-x", provider=PROVIDER_ID) is not None
    assert registry.runtime_pricing_for_model("vendor/model-y", provider=PROVIDER_ID) is None


@pytest.mark.asyncio
async def test_invalid_published_rates_preserve_finite_runtime_reference_cost(monkeypatch) -> None:
    registry = get_runtime_pricing_registry()
    registry.clear()
    model_ids = ("vendor/nan", "vendor/infinity", "vendor/scaled-overflow")
    registry.update_models(
        [(model_id, ModelPrice(input_per_1m=1.0, output_per_1m=2.0)) for model_id in model_ids],
        provider=PROVIDER_ID,
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
    monkeypatch.setattr("app.core.clients.openai_compat_sidecar.lease_http_session", lambda: _Lease(session))

    await OpenAICompatSidecarClient(_config()).list_models()

    usage = SidecarUsage(input_tokens=1_000_000, output_tokens=1_000_000)
    for model_id in model_ids:
        price = registry.runtime_pricing_for_model(model_id, provider=PROVIDER_ID)
        assert price == ModelPrice(input_per_1m=1.0, output_per_1m=2.0)
        reference_cost = reference_cost_from_sidecar_usage(model_id, usage, provider=PROVIDER_ID)
        assert reference_cost == pytest.approx(3.0)
        assert math.isfinite(reference_cost)


@pytest.mark.asyncio
async def test_chat_completion_relays_error_envelope(monkeypatch) -> None:
    session = _FakeSession(
        post_response=_FakeResponse(401, '{"error":{"message":"expired","type":"authentication_error"}}')
    )
    monkeypatch.setattr("app.core.clients.openai_compat_sidecar.lease_http_session", lambda: _Lease(session))
    client = OpenAICompatSidecarClient(_config(api_key="key"))

    with pytest.raises(OpenAICompatSidecarError) as exc_info:
        await client.chat_completion({"model": "Qwen/Qwen2.5-7B", "messages": []})

    assert exc_info.value.status_code == 401
    assert exc_info.value.message == "expired"


@pytest.mark.asyncio
async def test_transport_error_becomes_unavailable(monkeypatch) -> None:
    session = _FakeSession(get_response=OSError("boom"))
    monkeypatch.setattr("app.core.clients.openai_compat_sidecar.lease_http_session", lambda: _Lease(session))
    client = OpenAICompatSidecarClient(_config())

    with pytest.raises(OpenAICompatSidecarUnavailableError):
        await client.list_models()


@pytest.fixture(autouse=True)
def _clear_openai_compat_client_cache():
    reset_openai_compat_sidecar_client_cache()
    yield
    reset_openai_compat_sidecar_client_cache()


def test_client_cache_returns_the_same_instance_for_an_unchanged_config() -> None:
    first = get_openai_compat_sidecar_client(_config(api_key="key"))
    second = get_openai_compat_sidecar_client(_config(api_key="key"))

    assert first is second


def test_client_cache_keeps_distinct_endpoints_independent() -> None:
    first = get_openai_compat_sidecar_client(_config(endpoint_id=ENDPOINT_ID, api_key="one"))
    other_id = "3d0c9a4b-2f5e-4c8b-8d22-8b1f5e3c2d1b"
    second = get_openai_compat_sidecar_client(
        _config(endpoint_id=other_id, name="vLLM", api_key="two")
    )

    assert first is not second
    assert get_openai_compat_sidecar_client(_config(endpoint_id=ENDPOINT_ID, api_key="one")) is first
    assert get_openai_compat_sidecar_client(
        _config(endpoint_id=other_id, name="vLLM", api_key="two")
    ) is second


@pytest.mark.parametrize(
    "changed",
    [
        {"api_key": "rotated-key"},
        {"base_url": "https://vllm.internal/v1"},
        {"models_cache_ttl_seconds": 5.0},
        {"prefixes": (SidecarPrefix(prefix="vast-", strip=True),)},
        {"enabled": False},
        {"name": "LM Studio"},
    ],
)
def test_client_cache_evicts_on_any_config_change(changed) -> None:
    first = get_openai_compat_sidecar_client(_config(api_key="key"))

    second = get_openai_compat_sidecar_client(_config(**{"api_key": "key", **changed}))

    assert second is not first
    assert get_openai_compat_sidecar_client(_config(**{"api_key": "key", **changed})) is second


class TestCachedClientRetention:
    """A deleted endpoint must not leave its decrypted API key in the cache.

    Reported on https://github.com/vitalNohj/codex-lb/pull/59: replacing an
    endpoint's config evicts its entry, but *deleting* one produces no config
    again, so the removed endpoint's client - holding its decrypted key - stayed
    alive for the whole process lifetime.
    """

    OTHER_ID = "3d0c9a4b-2f5e-4c8b-8d22-8b1f5e3c2d1b"

    def test_a_removed_endpoint_client_and_its_credential_are_dropped(self) -> None:
        removed = get_openai_compat_sidecar_client(_config(api_key="secret-to-forget"))
        kept = get_openai_compat_sidecar_client(_config(endpoint_id=self.OTHER_ID, name="vLLM", api_key="kept"))

        # The operator deleted the first endpoint; only the second remains.
        retain_openai_compat_sidecar_clients([self.OTHER_ID])

        # The surviving endpoint keeps its cached client (and so its models TTL).
        assert get_openai_compat_sidecar_client(_config(endpoint_id=self.OTHER_ID, name="vLLM", api_key="kept")) is kept
        # The removed one is gone: re-requesting the same config builds a NEW
        # client, proving the old instance - and its credential - was evicted.
        assert get_openai_compat_sidecar_client(_config(api_key="secret-to-forget")) is not removed

    def test_reconciliation_against_the_same_set_is_a_no_op(self) -> None:
        """Running on every settings read must not keep throwing the cache away.

        Evicting a live endpoint's client would silently defeat
        ``models_cache_ttl_seconds``, which is exactly what the config-keyed
        cache exists to make work.
        """

        client = get_openai_compat_sidecar_client(_config(api_key="key"))

        retain_openai_compat_sidecar_clients([ENDPOINT_ID])
        retain_openai_compat_sidecar_clients([ENDPOINT_ID])

        assert get_openai_compat_sidecar_client(_config(api_key="key")) is client

    def test_retaining_nothing_clears_every_entry(self) -> None:
        """Deleting the last endpoint leaves no credential behind."""

        first = get_openai_compat_sidecar_client(_config(api_key="one"))
        second = get_openai_compat_sidecar_client(_config(endpoint_id=self.OTHER_ID, name="vLLM", api_key="two"))

        retain_openai_compat_sidecar_clients([])

        assert get_openai_compat_sidecar_client(_config(api_key="one")) is not first
        assert (
            get_openai_compat_sidecar_client(_config(endpoint_id=self.OTHER_ID, name="vLLM", api_key="two"))
            is not second
        )
