from __future__ import annotations

import json
from dataclasses import dataclass, replace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.clients.claude_sidecar import ClaudeSidecarConfig, ClaudeSidecarError, SidecarPrefix
from app.core.config.settings import get_settings
from app.core.openai.model_registry import ReasoningLevel, UpstreamModel, get_model_registry
from app.db.models import ApiKeyLimit, ApiKeyUsageReservation, RequestLog
from app.db.session import SessionLocal
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeyCreateData, ApiKeysService, LimitRuleInput
from app.modules.proxy.claude_sidecar_dispatch import reset_claude_sidecar_cooldown_gate
from app.modules.proxy.cursor_chat_compat import CURSOR_CONTEXT_LIMIT_SYNTHETIC_USAGE_TOKENS

pytestmark = pytest.mark.integration


# Tests that intentionally exercise the default native path. They assert the
# sidecar is bypassed, so the native boundaries must stay reachable for them;
# every provider boundary still raises.
_NATIVE_PATH_TESTS = frozenset({"test_gpt_request_does_not_hit_sidecar"})

# Outbound boundaries that must never be reached from this file. The Claude
# sidecar is deliberately absent: these tests assert real round-trips through
# ``_FakeSidecarClient`` (wire model, reservations, request logs), so that
# symbol stays bound to the fully synthetic fake that records payloads rather
# than to a raising guard. Every other provider and the default native path
# raise before any real client or transport is constructed.
_FORBIDDEN_DISPATCH = (
    "_stream_responses",
    "_source_responses_response",
    "_source_chat_completion_response",
    "_probe_chat_stream_startup_error",
    "OpenRouterSidecarClient",
    "OrcaRouterSidecarClient",
    "OmniRouteSidecarClient",
    "OllamaSidecarClient",
    "get_orcarouter_sidecar_client",
)


@pytest.fixture(autouse=True)
def _block_unexpected_dispatch(monkeypatch, request):
    """Fail before any unexpected provider or native transport is created.

    A test that legitimately exercises the default native path marks itself
    with ``@pytest.mark.allows_native_dispatch``; the native boundaries are
    then stubbed to a synthetic upstream failure instead of an assertion, so
    the test's own status-code and payload assertions still decide the result.
    Provider boundaries always raise.
    """
    allows_native = request.node.name.split("[")[0] in _NATIVE_PATH_TESTS
    native = {
        "_stream_responses",
        "_source_responses_response",
        "_source_chat_completion_response",
        "_probe_chat_stream_startup_error",
    }

    def _boundary(name):
        def _explode(*args, **kwargs):
            raise AssertionError(f"unexpected outbound dispatch boundary reached: {name}")

        return _explode

    for name in _FORBIDDEN_DISPATCH:
        if allows_native and name in native:
            # Left as real product code: no upstream account is configured in
            # this suite, so the request fails at account selection and never
            # constructs a client or transport. The test's own assertions
            # (502/503 and empty sidecar payloads) decide the result.
            continue
        monkeypatch.setattr(f"app.modules.proxy.api.{name}", _boundary(name), raising=True)


@pytest_asyncio.fixture
async def async_client(_reset_db_state, _block_unexpected_dispatch):
    """Module-local client that never enters the application lifespan.

    Shadows the shared ``async_client`` (tests/conftest.py:230) so this file
    does not start ``init_http_client``, the live-usage ingestor, or the
    schedulers that no fixture replaces. The per-response persistence drain is
    retained because these tests assert on reservations and request logs right
    after a response.

    Depends on ``_block_unexpected_dispatch`` explicitly so the tripwires are
    installed before any request is issued.
    """
    del _reset_db_state, _block_unexpected_dispatch
    from app.main import create_app

    app = create_app()

    async def _drain_proxy_persistence(response) -> None:
        del response
        service = getattr(app.state, "proxy_service", None)
        if service is not None and hasattr(service, "drain_persistence_tasks"):
            await service.drain_persistence_tasks(timeout_seconds=5)

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        event_hooks={"response": [_drain_proxy_persistence]},
    ) as client:
        yield client


@dataclass(frozen=True, slots=True)
class _FakeModel:
    id: str
    created: int | None = 123


class _FakeSidecarClient:
    def __init__(self, config: ClaudeSidecarConfig) -> None:
        self.config = config
        self.chat_payloads: list[dict] = []
        self.stream_payloads: list[dict] = []
        self.models = [_FakeModel("claude-sonnet-4-5-20250929")]
        self.chat_error: Exception | None = None
        self.chat_errors: list[Exception] = []
        self.stream_error: Exception | None = None
        self.stream_errors: list[Exception] = []
        self.stream_include_usage = True
        self.stream_context_error = False
        # CLIProxyAPI proxies other vendors and can echo their ``usage.cost``
        # straight back. It debits nothing of its own, so this is not spend.
        self.echoed_cost_usd: float | None = None

    async def list_models_cached(self):
        return self.models

    async def chat_completion(self, payload):
        self.chat_payloads.append(dict(payload))
        if self.chat_errors:
            raise self.chat_errors.pop(0)
        if self.chat_error is not None:
            raise self.chat_error
        usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        if self.echoed_cost_usd is not None:
            usage["cost"] = self.echoed_cost_usd
        return {
            "id": "chatcmpl-sidecar",
            "object": "chat.completion",
            "model": payload["model"],
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
            "usage": usage,
        }

    def stream_chat_completion(self, payload):
        self.stream_payloads.append(dict(payload))
        error = self.stream_errors.pop(0) if self.stream_errors else self.stream_error
        return _FakeStreamContext(
            error,
            include_usage=self.stream_include_usage,
            context_error=self.stream_context_error,
        )


class _FakeStreamContext:
    def __init__(
        self,
        error: Exception | None,
        *,
        include_usage: bool = True,
        context_error: bool = False,
    ) -> None:
        self.error = error
        self.include_usage = include_usage
        self.context_error = context_error

    async def __aenter__(self):
        if self.error is not None:
            raise self.error

        async def chunks():
            yield b'data: {"id":"chunk-1","object":"chat.completion.chunk","choices":[{"delta":{"content":"hi"}}]}\n\n'
            if self.context_error:
                yield (b'data: {"error":{"code":"context_length_exceeded","message":"Input token limit exceeded"}}\n\n')
                yield b"data: [DONE]\n\n"
                return
            if self.include_usage:
                yield (
                    b'data: {"id":"chunk-2","object":"chat.completion.chunk","choices":[],'
                    b'"usage":{"prompt_tokens":10,"completion_tokens":5}}\n\n'
                )
            yield b"data: [DONE]\n\n"

        return chunks()

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


def _make_upstream_model(slug: str) -> UpstreamModel:
    return UpstreamModel(
        slug=slug,
        display_name=slug,
        description=slug,
        context_window=128000,
        input_modalities=("text",),
        supported_reasoning_levels=(ReasoningLevel(effort="medium", description="medium"),),
        default_reasoning_level="medium",
        supports_reasoning_summaries=False,
        support_verbosity=False,
        default_verbosity=None,
        prefer_websockets=False,
        supports_parallel_tool_calls=True,
        supported_in_api=True,
        minimal_client_version=None,
        priority=0,
        available_in_plans=frozenset({"plus"}),
        raw={},
    )


@pytest.fixture
async def sidecar_enabled(monkeypatch):
    monkeypatch.setenv("CODEX_LB_CLAUDE_SIDECAR_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def fake_sidecar(monkeypatch):
    config = ClaudeSidecarConfig(
        enabled=True,
        base_url="http://127.0.0.1:8317",
        api_key="sidecar-key",
        prefixes=(
            SidecarPrefix(prefix="claude", strip=False),
            SidecarPrefix(prefix="cp-", strip=True),
            SidecarPrefix(prefix="cc/", strip=True),
        ),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
        full_models=("claude-sonnet-4-5-20250929",),
    )
    client = _FakeSidecarClient(config)

    async def load_config():
        return config

    monkeypatch.setattr("app.modules.proxy.api.load_sidecar_config", load_config)
    monkeypatch.setattr("app.modules.proxy.api.ClaudeSidecarClient", lambda _config: client)

    # The Claude symbol must resolve to this recording fake before any request,
    # and must never be left bound to a raising guard in this file.
    import app.modules.proxy.api as proxy_api

    assert proxy_api.ClaudeSidecarClient(config) is client
    return client


async def _enable_api_key_auth(async_client) -> None:
    response = await async_client.put("/api/settings", json={"apiKeyAuthEnabled": True})
    assert response.status_code == 200


async def _create_api_key(
    name: str,
    *,
    allowed_models: list[str] | None = None,
    limits: list[LimitRuleInput] | None = None,
):
    async with SessionLocal() as session:
        service = ApiKeysService(ApiKeysRepository(session))
        return await service.create_key(ApiKeyCreateData(name=name, allowed_models=allowed_models, limits=limits or []))


async def _reservation_statuses() -> list[str]:
    async with SessionLocal() as session:
        result = await session.execute(select(ApiKeyUsageReservation.status))
        return list(result.scalars().all())


def _chat_sse_payloads(body: bytes | str) -> list[dict]:
    text = body.decode("utf-8") if isinstance(body, bytes) else body
    return [
        json.loads(line.removeprefix("data: "))
        for line in text.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    ]


def _usage_chunks(payloads: list[dict]) -> list[dict]:
    return [payload for payload in payloads if payload.get("choices") == [] and "usage" in payload]


@pytest.mark.asyncio
async def test_claude_non_stream_routes_to_sidecar_and_finalizes_reservation(
    async_client,
    sidecar_enabled,
    fake_sidecar,
):
    await _enable_api_key_auth(async_client)
    key = await _create_api_key(
        "sidecar-key",
        limits=[LimitRuleInput(limit_type="total_tokens", limit_window="weekly", max_value=1000)],
    )

    response = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}"},
        json={"model": "claude-sonnet-4-5-20250929", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "hi"
    assert fake_sidecar.chat_payloads[0]["model"] == "claude-sonnet-4-5-20250929"
    assert await _reservation_statuses() == ["finalized"]
    async with SessionLocal() as session:
        logs = list((await session.execute(select(RequestLog))).scalars().all())
    sidecar_logs = [log for log in logs if log.source == "claude_sidecar"]
    assert len(sidecar_logs) == 1
    assert sidecar_logs[0].model == "claude-sonnet-4-5-20250929"


@pytest.mark.asyncio
async def test_custom_prefixed_claude_alias_routes_to_sidecar_with_unprefixed_wire_model(
    async_client,
    sidecar_enabled,
    fake_sidecar,
):
    response = await async_client.post(
        "/v1/chat/completions",
        json={"model": "cp_claude-fable-5", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert fake_sidecar.chat_payloads[0]["model"] == "claude-fable-5"
    async with SessionLocal() as session:
        logs = list((await session.execute(select(RequestLog))).scalars().all())
    sidecar_logs = [log for log in logs if log.source == "claude_sidecar"]
    assert len(sidecar_logs) == 1
    assert sidecar_logs[0].model == "cp_claude-fable-5"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("model", "wire_model", "effort"),
    [
        ("cc/claude-fable-5-1", "claude-fable-5-1", None),
        ("cc/claude-fable-5-1-thinking-max", "claude-fable-5-1", "max"),
        ("cp_claude-fable-5-1", "claude-fable-5-1", None),
        ("claude-fable-5.1", "claude-fable-5-1", None),
        ("claude-fable-5-1-thinking-max", "claude-fable-5-1", "max"),
        ("cp_claude-fable-5.1-thinking-max", "claude-fable-5-1", "max"),
        ("claude-fable-5", "claude-fable-5", None),
    ],
)
async def test_fable_version_survives_chat_forwarding(
    async_client, sidecar_enabled, fake_sidecar, model, wire_model, effort
):
    response = await async_client.post(
        "/v1/chat/completions",
        json={"model": model, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 4096},
    )

    assert response.status_code == 200
    payload = fake_sidecar.chat_payloads[0]
    assert payload["model"] == wire_model
    assert payload["max_tokens"] == 32_768
    if effort is not None:
        assert payload["reasoning_effort"] == effort


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("input_tokens", "requested_output", "expected_output"),
    [(10, 200_000, 128_000), (170_000, 4096, 32_768), (980_000, 4096, None)],
)
async def test_fable_5_1_output_and_context_bounds(
    async_client, sidecar_enabled, fake_sidecar, input_tokens, requested_output, expected_output
):
    response = await async_client.post(
        "/v1/chat/completions",
        json={
            "model": "cc/claude-fable-5-1",
            "messages": [{"role": "user", "content": "x" * (input_tokens * 4)}],
            "max_tokens": requested_output,
        },
    )
    assert response.status_code == 200
    payload = fake_sidecar.chat_payloads[0]
    assert payload["model"] == "claude-fable-5-1"
    if expected_output is None:
        assert 4096 <= payload["max_tokens"] < 32_768
    else:
        assert payload["max_tokens"] == expected_output


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("requested_model", "catalog_model"),
    [
        ("claude-sonnet-4-5-20250929", "anthropic/claude-sonnet-4.5"),
        ("claude-fable-5-1", "anthropic/claude-fable-5.1"),
        ("cp_claude-fable-5.1", "anthropic/claude-fable-5.1"),
    ],
)
async def test_a_dated_claude_id_is_priced_from_the_anthropic_reference_rate(
    async_client,
    sidecar_enabled,
    fake_sidecar,
    monkeypatch,
    requested_model,
    catalog_model,
):
    """CLIProxyAPI serves date-stamped ids; the catalog publishes undated ones.

    Without recognising the trailing ``-YYYYMMDD`` release stamp every CLIProxyAPI
    row rendered ``!!`` and accrued no cost quota at all, for exactly the ids whose
    real Anthropic rate the pricing reference does publish.
    """

    from app.core.usage.external_pricing import service as pricing_service
    from app.core.usage.external_pricing.catalogs import Catalog, CatalogEntry
    from app.core.usage.external_pricing.service import get_lookup_coordinator, reset_serving_context_loaders
    from app.core.usage.pricing import ModelPrice
    from app.db.models import CostSource, ExternalPriceStatus

    async def _reference():
        return Catalog.from_entries(
            "openrouter",
            [CatalogEntry(model_id=catalog_model, price=ModelPrice(3.0, 15.0))],
        )

    monkeypatch.setattr(pricing_service, "_load_reference_catalog", _reference)
    reset_serving_context_loaders()
    try:
        from app.modules.proxy.external_pricing_sources import register_external_pricing_sources

        register_external_pricing_sources()
        monkeypatch.setattr(
            "app.modules.proxy.claude_sidecar_dispatch.load_sidecar_config",
            lambda: _resolved(fake_sidecar.config),
        )

        await _enable_api_key_auth(async_client)
        key = await _create_api_key(
            "dated-claude-key",
            limits=[LimitRuleInput(limit_type="cost_usd", limit_window="weekly", max_value=1_000_000_000)],
        )

        for _ in range(2):
            response = await async_client.post(
                "/v1/chat/completions",
                headers={"Authorization": f"Bearer {key.key}"},
                json={"model": requested_model, "messages": [{"role": "user", "content": "hi"}]},
            )
            assert response.status_code == 200
            await get_lookup_coordinator().drain()

        async with SessionLocal() as session:
            logs = list((await session.execute(select(RequestLog))).scalars().all())
        sidecar_logs = sorted((log for log in logs if log.source == "claude_sidecar"), key=lambda log: log.id)
        priced = [log for log in sidecar_logs if log.cost_usd is not None]
        assert priced, "a dated Claude id must resolve against the Anthropic reference rate"
        # 10 input tokens at $3/M + 5 output at $15/M.
        assert priced[-1].cost_usd == pytest.approx(10 * 3.0 / 1e6 + 5 * 15.0 / 1e6)
        assert priced[-1].cost_source == CostSource.CATALOG_CALCULATED.value
        assert priced[-1].price_status == ExternalPriceStatus.RESOLVED.value
        assert not [log for log in sidecar_logs if log.price_status == ExternalPriceStatus.UNRESOLVED.value], (
            "a model that resolved must never render the unresolved marker"
        )

        async with SessionLocal() as session:
            rows = (await session.execute(select(ApiKeyLimit).where(ApiKeyLimit.api_key_id == key.id))).scalars().all()
        charged = {row.limit_type.value: row.current_value for row in rows}
        assert charged["cost_usd"] == int(priced[-1].cost_usd * 1_000_000), (
            "a resolved model must resume accruing cost quota, and at the price it recorded"
        )
    finally:
        reset_serving_context_loaders()


async def _resolved(value):
    return value


@pytest.mark.asyncio
async def test_an_echoed_upstream_cost_is_not_recorded_as_cliproxy_spend(
    async_client,
    sidecar_enabled,
    fake_sidecar,
):
    """CLIProxyAPI debits nothing, so an echoed ``usage.cost`` is not actual spend.

    ``extract_usage`` reads ``usage.cost`` for the OpenRouter path, and a
    CLIProxyAPI response can carry the same field verbatim from whichever upstream
    it fronted. Forwarding it as a billed amount would label another party's debit
    as this request's authoritative spend, which the mapper and the savings
    arithmetic then treat as final.
    """

    from app.db.models import CostSource

    fake_sidecar.echoed_cost_usd = 4.2

    response = await async_client.post(
        "/v1/chat/completions",
        json={"model": "claude-sonnet-4-5-20250929", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 200

    async with SessionLocal() as session:
        logs = list((await session.execute(select(RequestLog))).scalars().all())
    sidecar_logs = [log for log in logs if log.source == "claude_sidecar"]
    assert sidecar_logs
    for log in sidecar_logs:
        assert log.cost_source != CostSource.UPSTREAM_BILLED.value
        assert log.cost_usd != pytest.approx(4.2)


@pytest.mark.asyncio
async def test_bare_claude_opus_routes_to_sidecar_with_wire_model(
    async_client,
    sidecar_enabled,
    fake_sidecar,
):
    response = await async_client.post(
        "/v1/chat/completions",
        json={"model": "claude-opus-4-7", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert fake_sidecar.chat_payloads[-1]["model"] == "claude-opus-4-7"


@pytest.mark.asyncio
async def test_custom_prefixed_opus_alias_routes_to_sidecar_with_unprefixed_wire_model(
    async_client,
    sidecar_enabled,
    fake_sidecar,
):
    response = await async_client.post(
        "/v1/chat/completions",
        json={"model": "cp-claude-opus-4-7", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert fake_sidecar.chat_payloads[-1]["model"] == "claude-opus-4-7"


@pytest.mark.asyncio
async def test_claude_stream_routes_to_sidecar_and_requests_usage(async_client, sidecar_enabled, fake_sidecar):
    await _enable_api_key_auth(async_client)
    key = await _create_api_key(
        "sidecar-stream-key",
        limits=[LimitRuleInput(limit_type="total_tokens", limit_window="weekly", max_value=1000)],
    )

    async with async_client.stream(
        "POST",
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}"},
        json={
            "model": "claude-sonnet-4-5-20250929",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    ) as response:
        body = await response.aread()

    assert response.status_code == 200
    assert b"data: [DONE]" in body
    assert fake_sidecar.stream_payloads[0]["stream_options"]["include_usage"] is True
    assert await _reservation_statuses() == ["finalized"]


@pytest.mark.asyncio
async def test_sidecar_model_list_merges_and_filters(async_client, sidecar_enabled, fake_sidecar):
    await async_client.put(
        "/api/settings",
        json={
            "claudeSidecarEnabled": True,
            "claudeSidecarFullModels": ["claude-sonnet-4-5-20250929"],
        },
    )
    await _enable_api_key_auth(async_client)
    registry = get_model_registry()
    await registry.update({"plus": [_make_upstream_model("gpt-5.4")]})
    key = await _create_api_key("models-key", allowed_models=["claude-sonnet-4-5-20250929"])

    response = await async_client.get("/v1/models", headers={"Authorization": f"Bearer {key.key}"})

    assert response.status_code == 200
    data = response.json()["data"]
    ids = [item["id"] for item in data]
    assert "claude-sonnet-4-5-20250929" in ids
    assert "gpt-5.4" not in ids

    sidecar_entry = next(item for item in data if item["id"] == "claude-sonnet-4-5-20250929")
    # Cursor's local-provider discovery reads the advertised context window to
    # decide when to auto-summarize/compact; sidecar models must expose it.
    assert sidecar_entry["context_length"] == 200_000
    assert sidecar_entry["contextLength"] == 200_000
    assert sidecar_entry["capabilities"]["context_length"] == 200_000


@pytest.mark.asyncio
async def test_gpt_request_does_not_hit_sidecar(async_client, sidecar_enabled, fake_sidecar):
    response = await async_client.post(
        "/v1/chat/completions",
        json={"model": "gpt-5.4", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code in {502, 503}
    assert fake_sidecar.chat_payloads == []
    assert fake_sidecar.stream_payloads == []


@pytest.mark.asyncio
async def test_sidecar_model_not_allowed_rejects_before_sidecar(async_client, sidecar_enabled, fake_sidecar):
    await _enable_api_key_auth(async_client)
    key = await _create_api_key("restricted-key", allowed_models=["gpt-5.4"])

    response = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}"},
        json={"model": "claude-sonnet-4-5-20250929", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "model_not_allowed"
    assert fake_sidecar.chat_payloads == []


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    ("allowed_model", "requested_model", "wire_model"),
    [
        ("claude-fable-5", "team.claude-fable-5-1", None),
        ("claude-fable-5", "team.claude-fable-5-1-thinking-max", None),
        ("team.claude-fable-5", "team.claude-fable-5-1", None),
        ("claude-fable-5", "team.claude-fable-5.1", None),
        ("claude-fable-5", "team.claude-fable-5", "claude-fable-5"),
        ("claude-fable-5-1", "team.claude-fable-5-1", "claude-fable-5-1"),
        ("team.claude-fable-5-1", "team.claude-fable-5-1", "claude-fable-5-1"),
    ],
)
async def test_custom_prefix_model_access_before_reservation(
    async_client, sidecar_enabled, fake_sidecar, monkeypatch, stream, allowed_model, requested_model, wire_model
):
    config = replace(fake_sidecar.config, prefixes=(SidecarPrefix(prefix="team.", strip=True),))
    monkeypatch.setattr("app.modules.proxy.api.load_sidecar_config", AsyncMock(return_value=config))
    reserve = AsyncMock(return_value=None)
    monkeypatch.setattr("app.modules.proxy.api._enforce_request_limits", reserve)
    await _enable_api_key_auth(async_client)
    key = await _create_api_key("custom-prefix-key", allowed_models=[allowed_model])

    response = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}"},
        json={"model": requested_model, "messages": [{"role": "user", "content": "hi"}], "stream": stream},
    )

    if wire_model is None:
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "model_not_allowed"
        reserve.assert_not_awaited()
        assert fake_sidecar.chat_payloads == []
        assert fake_sidecar.stream_payloads == []
    else:
        assert response.status_code == 200
        reserve.assert_awaited_once()
        forwarded = fake_sidecar.stream_payloads if stream else fake_sidecar.chat_payloads
        assert forwarded[0]["model"] == wire_model


@pytest.mark.asyncio
async def test_claude_sidecar_cursor_context_limit_returns_synthetic_usage(
    async_client,
    sidecar_enabled,
    fake_sidecar,
):
    fake_sidecar.chat_error = ClaudeSidecarError(
        400,
        "Input token limit exceeded",
        body={"error": {"code": "context_length_exceeded", "message": "Input token limit exceeded"}},
    )

    response = await async_client.post(
        "/v1/chat/completions",
        headers={"User-Agent": "Cursor/1.0"},
        json={"model": "claude-sonnet-4-5-20250929", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert response.json()["usage"] == {
        "prompt_tokens": CURSOR_CONTEXT_LIMIT_SYNTHETIC_USAGE_TOKENS,
        "completion_tokens": 0,
        "total_tokens": CURSOR_CONTEXT_LIMIT_SYNTHETIC_USAGE_TOKENS,
    }


@pytest.mark.asyncio
async def test_claude_sidecar_cursor_stream_applies_usage_fallback(
    async_client,
    sidecar_enabled,
    fake_sidecar,
):
    fake_sidecar.stream_include_usage = False

    async with async_client.stream(
        "POST",
        "/v1/chat/completions",
        headers={"User-Agent": "Cursor/1.0"},
        json={
            "model": "claude-sonnet-4-5-20250929",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    ) as response:
        body = await response.aread()

    assert response.status_code == 200
    payloads = _chat_sse_payloads(body)
    usage_chunks = _usage_chunks(payloads)
    assert len(usage_chunks) == 1
    usage = usage_chunks[0]["usage"]
    assert usage["prompt_tokens"] > 0
    assert usage["completion_tokens"] > 0
    assert usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]
    assert body.rstrip().endswith(b"data: [DONE]")


@pytest.mark.asyncio
async def test_claude_sidecar_cursor_stream_forwards_valid_usage_unchanged(
    async_client,
    sidecar_enabled,
    fake_sidecar,
):
    async with async_client.stream(
        "POST",
        "/v1/chat/completions",
        headers={"User-Agent": "Cursor/1.0"},
        json={
            "model": "claude-sonnet-4-5-20250929",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    ) as response:
        body = await response.aread()

    assert response.status_code == 200
    usage_chunks = _usage_chunks(_chat_sse_payloads(body))
    assert len(usage_chunks) == 1
    assert usage_chunks[0]["usage"] == {"prompt_tokens": 10, "completion_tokens": 5}


@pytest.mark.asyncio
async def test_claude_sidecar_cursor_stream_context_limit_returns_synthetic_usage(
    async_client,
    sidecar_enabled,
    fake_sidecar,
):
    fake_sidecar.stream_context_error = True

    async with async_client.stream(
        "POST",
        "/v1/chat/completions",
        headers={"User-Agent": "Cursor/1.0"},
        json={
            "model": "claude-sonnet-4-5-20250929",
            "messages": [{"role": "user", "content": "too much context"}],
            "stream": True,
        },
    ) as response:
        body = await response.aread()

    assert response.status_code == 200
    assert b'"error"' not in body
    usage_chunks = _usage_chunks(_chat_sse_payloads(body))
    assert len(usage_chunks) == 1
    assert usage_chunks[0]["usage"] == {
        "prompt_tokens": CURSOR_CONTEXT_LIMIT_SYNTHETIC_USAGE_TOKENS,
        "completion_tokens": 0,
        "total_tokens": CURSOR_CONTEXT_LIMIT_SYNTHETIC_USAGE_TOKENS,
    }
    assert body.rstrip().endswith(b"data: [DONE]")


@pytest.mark.asyncio
async def test_claude_sidecar_non_cursor_stream_does_not_apply_usage_fallback(
    async_client,
    sidecar_enabled,
    fake_sidecar,
):
    fake_sidecar.stream_include_usage = False

    async with async_client.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": "claude-sonnet-4-5-20250929",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    ) as response:
        body = await response.aread()

    assert response.status_code == 200
    assert _usage_chunks(_chat_sse_payloads(body)) == []
    assert body.rstrip().endswith(b"data: [DONE]")


_AUTH_UNAVAILABLE_MESSAGE = (
    "auth_unavailable: no auth available (providers=claude, model=claude-opus-5); "
    "check Claude auth/key session and cooldown state via /v0/management/auth-files"
)


async def _sidecar_logs() -> list[RequestLog]:
    async with SessionLocal() as session:
        logs = list((await session.execute(select(RequestLog))).scalars().all())
    return [log for log in logs if log.source == "claude_sidecar"]


@pytest.fixture
def fail_fast_sidecar_cooldown(monkeypatch):
    monkeypatch.setattr(
        "app.modules.proxy.claude_sidecar_dispatch.CLAUDE_SIDECAR_COOLDOWN_WAIT_SECONDS",
        0.0,
    )
    monkeypatch.setattr(
        "app.modules.proxy.claude_sidecar_dispatch.CLAUDE_SIDECAR_COOLDOWN_RETRY_SLEEP_SECONDS",
        0.0,
    )
    reset_claude_sidecar_cooldown_gate()


@pytest.fixture
def short_sidecar_cooldown_wait(monkeypatch):
    monkeypatch.setattr(
        "app.modules.proxy.claude_sidecar_dispatch.CLAUDE_SIDECAR_COOLDOWN_WAIT_SECONDS",
        1.0,
    )
    monkeypatch.setattr(
        "app.modules.proxy.claude_sidecar_dispatch.CLAUDE_SIDECAR_COOLDOWN_RETRY_SLEEP_SECONDS",
        0.0,
    )
    reset_claude_sidecar_cooldown_gate()


@pytest.mark.asyncio
async def test_claude_sidecar_auth_unavailable_logs_cooldown_and_keeps_client_message(
    async_client,
    sidecar_enabled,
    fake_sidecar,
    fail_fast_sidecar_cooldown,
):
    fake_sidecar.chat_error = ClaudeSidecarError(503, _AUTH_UNAVAILABLE_MESSAGE)

    response = await async_client.post(
        "/v1/chat/completions",
        json={"model": "claude-sonnet-4-5-20250929", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 503
    assert "auth_unavailable" in response.json()["error"]["message"]
    logs = await _sidecar_logs()
    assert len(logs) == 1
    assert logs[0].error_code == "claude_sidecar_cooldown"
    assert logs[0].error_message == "Claude sidecar cooldown for claude-sonnet-4-5-20250929"
    assert logs[0].failure_detail == _AUTH_UNAVAILABLE_MESSAGE


@pytest.mark.asyncio
async def test_claude_sidecar_stream_auth_unavailable_logs_cooldown_and_keeps_client_message(
    async_client,
    sidecar_enabled,
    fake_sidecar,
    fail_fast_sidecar_cooldown,
):
    fake_sidecar.stream_error = ClaudeSidecarError(503, _AUTH_UNAVAILABLE_MESSAGE)

    async with async_client.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": "claude-sonnet-4-5-20250929",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    ) as response:
        body = await response.aread()

    payloads = _chat_sse_payloads(body)
    error_payloads = [payload for payload in payloads if "error" in payload]
    assert error_payloads
    assert "no auth available" in error_payloads[0]["error"]["message"]
    logs = await _sidecar_logs()
    assert len(logs) == 1
    assert logs[0].error_code == "claude_sidecar_cooldown"
    assert logs[0].error_message == "Claude sidecar cooldown for claude-sonnet-4-5-20250929"
    assert logs[0].failure_detail == _AUTH_UNAVAILABLE_MESSAGE


@pytest.mark.asyncio
async def test_claude_sidecar_auth_unavailable_retries_until_cooldown_clears(
    async_client,
    sidecar_enabled,
    fake_sidecar,
    short_sidecar_cooldown_wait,
):
    fake_sidecar.chat_errors = [ClaudeSidecarError(503, _AUTH_UNAVAILABLE_MESSAGE)]

    response = await async_client.post(
        "/v1/chat/completions",
        json={"model": "claude-sonnet-4-5-20250929", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert "auth_unavailable" not in response.text
    assert len(fake_sidecar.chat_payloads) == 2
    logs = await _sidecar_logs()
    assert len(logs) == 1
    assert logs[0].status == "success"
    assert logs[0].error_code is None


@pytest.mark.asyncio
async def test_claude_sidecar_stream_auth_unavailable_retries_until_cooldown_clears(
    async_client,
    sidecar_enabled,
    fake_sidecar,
    short_sidecar_cooldown_wait,
):
    fake_sidecar.stream_errors = [ClaudeSidecarError(503, _AUTH_UNAVAILABLE_MESSAGE)]

    async with async_client.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": "claude-sonnet-4-5-20250929",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    ) as response:
        body = await response.aread()

    payloads = _chat_sse_payloads(body)
    assert all("error" not in payload for payload in payloads)
    assert len(fake_sidecar.stream_payloads) == 2
    logs = await _sidecar_logs()
    assert len(logs) == 1
    assert logs[0].status == "success"
