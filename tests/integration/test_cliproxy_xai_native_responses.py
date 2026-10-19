"""xAI Responses go to CLIProxyAPI's native ``/v1/responses``, whole.

The chat bridge drops ``reasoning.encrypted_content`` from earlier turns, which
moves the prompt xAI sees off the prefix it cached, so a long conversation is
re-billed in full after every reasoning turn. These tests pin each risk the
clb-oa-18 scout found: the request reaches CLIProxyAPI unchanged, the cache key
is always present and is the sticky pin key, stateful fields are still refused,
the client's reasoning effort is kept, reservations and service tier match the
chat route, and xAI's exact cost and token detail are recorded.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.clients.claude_sidecar import (
    ClaudeSidecarConfig,
    ClaudeSidecarError,
    ClaudeSidecarUnavailableError,
    SidecarPrefix,
)
from app.core.config.settings import get_settings
from app.db.models import ApiKeyUsageReservation, CostSource, RequestLog
from app.db.session import SessionLocal
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeyCreateData, ApiKeysService, LimitRuleInput
from app.modules.proxy import cliproxy_responses_dispatch
from app.modules.proxy.claude_sidecar_dispatch import reset_claude_sidecar_cooldown_gate

pytestmark = pytest.mark.integration

XAI_MODEL = "grok-4.3"
CLAUDE_MODEL = "claude-sonnet-4-5-20250929"
# High-entropy unpadded base64, the shape CLIProxyAPI's xAI executor accepts.
ENCRYPTED_REASONING = "Q2lwaGVydGV4dDEyMzQ1Njc4OTBhYmNkZWZnaGlqa2xtbm9wcXJzdHV2d3h5ejAxMjM0NTY3ODk" * 4
COST_TICKS = 123_456_789  # 0.0123456789 USD


_FORBIDDEN_DISPATCH = (
    "_stream_responses",
    "_source_responses_response",
    "_source_chat_completion_response",
    "_probe_chat_stream_startup_error",
    "OpenRouterSidecarClient",
    "OpenAICompatSidecarClient",
    "get_openai_compat_sidecar_client",
    "OrcaRouterSidecarClient",
    "OmniRouteSidecarClient",
    "OllamaSidecarClient",
    "get_orcarouter_sidecar_client",
)


@pytest.fixture(autouse=True)
def _block_unexpected_dispatch(monkeypatch):
    def _boundary(name):
        def _explode(*args, **kwargs):
            raise AssertionError(f"unexpected outbound dispatch boundary reached: {name}")

        return _explode

    for name in _FORBIDDEN_DISPATCH:
        monkeypatch.setattr(f"app.modules.proxy.api.{name}", _boundary(name), raising=True)


@pytest.fixture(autouse=True)
def _fast_cooldown(monkeypatch):
    monkeypatch.setattr("app.modules.proxy.claude_sidecar_dispatch.CLAUDE_SIDECAR_COOLDOWN_WAIT_SECONDS", 0.0)
    monkeypatch.setattr("app.modules.proxy.claude_sidecar_dispatch.CLAUDE_SIDECAR_COOLDOWN_RETRY_SLEEP_SECONDS", 0.0)
    reset_claude_sidecar_cooldown_gate()


@pytest_asyncio.fixture
async def async_client(_reset_db_state, _block_unexpected_dispatch):
    del _reset_db_state, _block_unexpected_dispatch
    from app.main import create_app

    app = create_app()

    async def _drain_proxy_persistence(response) -> None:
        del response
        service = getattr(app.state, "proxy_service", None)
        if service is not None and hasattr(service, "drain_persistence_tasks"):
            await service.drain_persistence_tasks(timeout_seconds=5)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        event_hooks={"response": [_drain_proxy_persistence]},
    ) as client:
        yield client


@pytest.fixture
def sidecar_enabled(monkeypatch):
    monkeypatch.setenv("CODEX_LB_CLAUDE_SIDECAR_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def native_disabled(monkeypatch, sidecar_enabled):
    del sidecar_enabled
    monkeypatch.setenv("CODEX_LB_CLIPROXY_XAI_NATIVE_RESPONSES_ENABLED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@dataclass(frozen=True, slots=True)
class _FakeModel:
    id: str
    created: int | None = 123
    owned_by: str | None = None
    raw: dict | None = None


def _response_object(model: str, *, usage: dict | None, status: str = "completed", error: dict | None = None) -> dict:
    body: dict = {
        "id": "resp_xai_1",
        "object": "response",
        "created_at": 1,
        "status": status,
        "model": model,
        "output": [
            {
                "id": "rs_1",
                "type": "reasoning",
                "summary": [],
                "encrypted_content": ENCRYPTED_REASONING,
            },
            {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": "hi", "annotations": []}],
            },
        ],
        "usage": usage,
    }
    if error is not None:
        body["error"] = error
    return body


def _xai_usage(*, cost_ticks: int | None = COST_TICKS) -> dict:
    usage: dict = {
        "input_tokens": 1000,
        "input_tokens_details": {"cached_tokens": 900},
        "output_tokens": 50,
        "output_tokens_details": {"reasoning_tokens": 30},
        "total_tokens": 1050,
    }
    if cost_ticks is not None:
        usage["cost_in_usd_ticks"] = cost_ticks
    return usage


def _sse(event: dict) -> bytes:
    return f"event: {event['type']}\ndata: {json.dumps(event, separators=(',', ':'))}\n\n".encode()


def _stream_events(model: str, *, usage: dict | None, terminal: str = "response.completed") -> list[bytes]:
    final = _response_object(model, usage=usage, status="failed" if terminal == "response.failed" else "completed")
    if terminal == "response.failed":
        final["error"] = {"code": "server_error", "message": "xai broke"}
    return [
        _sse(
            {
                "type": "response.created",
                "sequence_number": 0,
                "response": {"id": "resp_xai_1", "status": "in_progress"},
            }
        ),
        _sse(
            {
                "type": "response.output_item.done",
                "sequence_number": 1,
                "output_index": 0,
                "item": final["output"][0],
            }
        ),
        _sse({"type": "response.output_text.delta", "sequence_number": 2, "delta": "hi"}),
        _sse({"type": terminal, "sequence_number": 3, "response": final}),
    ]


class _FakeCliproxyClient:
    """CLIProxyAPI as codex-lb sees it: chat and native Responses entry points."""

    def __init__(self, config: ClaudeSidecarConfig) -> None:
        self.config = config
        self.models = [_FakeModel(CLAUDE_MODEL), _FakeModel(XAI_MODEL, owned_by="xai")]
        self.chat_payloads: list[dict] = []
        self.stream_chat_payloads: list[dict] = []
        self.responses_payloads: list[dict] = []
        self.stream_responses_payloads: list[dict] = []
        self.responses_errors: list[Exception] = []
        self.response_usage: dict | None = _xai_usage()
        self.response_status = "completed"
        self.response_error: dict | None = None
        self.stream_chunks: list[bytes] | None = None
        self.stream_errors: list[Exception] = []

    async def list_models_cached(self):
        return self.models

    async def chat_completion(self, payload):
        self.chat_payloads.append(json.loads(json.dumps(payload)))
        return {
            "id": "chatcmpl-1",
            "object": "chat.completion",
            "model": payload["model"],
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

    def stream_chat_completion(self, payload):
        self.stream_chat_payloads.append(json.loads(json.dumps(payload)))
        return _ChunkStream(
            [
                b'data: {"id":"c","object":"chat.completion.chunk","choices":[{"delta":{"content":"hi"}}]}\n\n',
                b'data: {"id":"c","object":"chat.completion.chunk","choices":[],'
                b'"usage":{"prompt_tokens":10,"completion_tokens":5}}\n\n',
                b"data: [DONE]\n\n",
            ],
            None,
        )

    async def responses(self, payload):
        self.responses_payloads.append(json.loads(json.dumps(payload)))
        if self.responses_errors:
            raise self.responses_errors.pop(0)
        return _response_object(
            str(payload["model"]),
            usage=self.response_usage,
            status=self.response_status,
            error=self.response_error,
        )

    def stream_responses(self, payload):
        self.stream_responses_payloads.append(json.loads(json.dumps(payload)))
        error = self.stream_errors.pop(0) if self.stream_errors else None
        chunks = (
            self.stream_chunks
            if self.stream_chunks is not None
            else _stream_events(str(payload["model"]), usage=self.response_usage)
        )
        return _ChunkStream(chunks, error)


class _ChunkStream:
    def __init__(self, chunks: list[bytes], error: Exception | None) -> None:
        self.chunks = chunks
        self.error = error

    async def __aenter__(self):
        if self.error is not None:
            raise self.error
        chunks = self.chunks

        async def iterate():
            for chunk in chunks:
                yield chunk

        return iterate()

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


@pytest.fixture
def fake_cliproxy(monkeypatch, sidecar_enabled):
    del sidecar_enabled
    config = ClaudeSidecarConfig(
        enabled=True,
        base_url="http://127.0.0.1:8317",
        api_key="sidecar-key",
        prefixes=(SidecarPrefix(prefix="claude", strip=False),),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
        full_models=(CLAUDE_MODEL, XAI_MODEL, "devin/grok-4-6"),
    )
    client = _FakeCliproxyClient(config)

    async def load_config():
        return config

    monkeypatch.setattr("app.modules.proxy.api.load_sidecar_config", load_config)
    monkeypatch.setattr("app.modules.proxy.api.ClaudeSidecarClient", lambda _config: client)
    return client


def _xai_request(**overrides) -> dict:
    payload: dict = {
        "model": XAI_MODEL,
        "instructions": "You are a careful coding agent.",
        "input": [
            {"role": "user", "content": [{"type": "input_text", "text": "Refactor the billing module."}]},
            {"type": "reasoning", "id": "rs_prev", "summary": [], "encrypted_content": ENCRYPTED_REASONING},
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Plan ready."}],
            },
            {"role": "user", "content": [{"type": "input_text", "text": "continue"}]},
        ],
        "include": ["reasoning.encrypted_content"],
        "reasoning": {"effort": "high"},
        "prompt_cache_key": "thread-xai-1",
    }
    payload.update(overrides)
    return payload


async def _enable_api_key_auth(async_client) -> None:
    response = await async_client.put("/api/settings", json={"apiKeyAuthEnabled": True})
    assert response.status_code == 200


async def _create_api_key(name: str, **kwargs):
    async with SessionLocal() as session:
        service = ApiKeysService(ApiKeysRepository(session))
        return await service.create_key(ApiKeyCreateData(name=name, allowed_models=None, **kwargs))


async def _reservation_statuses() -> list[str]:
    async with SessionLocal() as session:
        result = await session.execute(select(ApiKeyUsageReservation.status))
        return list(result.scalars().all())


async def _sidecar_logs() -> list[RequestLog]:
    async with SessionLocal() as session:
        logs = list((await session.execute(select(RequestLog))).scalars().all())
    return [log for log in logs if log.source == "claude_sidecar"]


def _sse_events(body: bytes) -> list[dict]:
    events = []
    for line in body.decode().splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line.removeprefix("data: ")))
    return events


# --- the request reaches CLIProxyAPI unchanged ------------------------------------


@pytest.mark.asyncio
async def test_encrypted_reasoning_reaches_cliproxy_byte_for_byte(async_client, fake_cliproxy):
    """Scout risk 1: the chat bridge drops encrypted reasoning from history."""

    response = await async_client.post("/v1/responses", json=_xai_request())

    assert response.status_code == 200
    assert fake_cliproxy.chat_payloads == []
    assert len(fake_cliproxy.responses_payloads) == 1
    sent = fake_cliproxy.responses_payloads[0]
    reasoning_items = [item for item in sent["input"] if item.get("type") == "reasoning"]
    assert reasoning_items == [
        {"type": "reasoning", "id": "rs_prev", "summary": [], "encrypted_content": ENCRYPTED_REASONING}
    ]
    assert sent["include"] == ["reasoning.encrypted_content"]
    assert sent["instructions"] == "You are a careful coding agent."
    assert sent["model"] == XAI_MODEL
    # The upstream reasoning item comes back to the client whole.
    output = response.json()["output"]
    assert output[0]["encrypted_content"] == ENCRYPTED_REASONING


@pytest.mark.asyncio
async def test_responses_only_fields_survive(async_client, fake_cliproxy):
    """Scout risk 3: the bridge drops Responses-only request fields."""

    response = await async_client.post(
        "/v1/responses",
        json=_xai_request(
            text={"format": {"type": "text"}, "verbosity": "low"},
            max_output_tokens=2048,
            parallel_tool_calls=False,
            tools=[{"type": "function", "name": "lookup", "parameters": {"type": "object", "properties": {}}}],
            tool_choice="auto",
        ),
    )

    assert response.status_code == 200
    sent = fake_cliproxy.responses_payloads[0]
    assert sent["text"] == {"format": {"type": "text"}, "verbosity": "low"}
    assert sent["max_output_tokens"] == 2048
    assert sent["parallel_tool_calls"] is False
    assert sent["tools"][0]["name"] == "lookup"
    assert sent["tool_choice"] == "auto"
    assert "messages" not in sent


# --- the cache key ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_client_cache_key_is_forwarded_unchanged(async_client, fake_cliproxy):
    await async_client.post("/v1/responses", json=_xai_request())

    assert fake_cliproxy.responses_payloads[0]["prompt_cache_key"] == "thread-xai-1"


@pytest.mark.asyncio
async def test_a_keyless_conversation_gets_a_stable_cache_key(async_client, fake_cliproxy):
    """Without a client key every turn still carries one, and the same one.

    CLIProxyAPI would otherwise derive an id from the opening messages, and
    the pin and xAI's cache could disagree.
    """

    first = _xai_request()
    del first["prompt_cache_key"]
    first["input"] = first["input"][:1]
    later = _xai_request()
    del later["prompt_cache_key"]

    await async_client.post("/v1/responses", json=first)
    await async_client.post("/v1/responses", json=later)

    keys = [payload.get("prompt_cache_key") for payload in fake_cliproxy.responses_payloads]
    assert all(isinstance(key, str) and key for key in keys), keys
    assert keys[0] == keys[1]


@pytest.mark.asyncio
async def test_a_session_header_becomes_the_cache_key(async_client, fake_cliproxy):
    request = _xai_request()
    del request["prompt_cache_key"]

    await async_client.post("/v1/responses", json=request, headers={"X-Session-Id": "sess-xai"})

    assert fake_cliproxy.responses_payloads[0]["prompt_cache_key"] == "sess-xai"


@pytest.mark.asyncio
async def test_a_request_with_nothing_to_key_on_still_sends_a_cache_key(async_client, fake_cliproxy, monkeypatch):
    monkeypatch.setenv("CODEX_LB_OPENAI_PROMPT_CACHE_KEY_DERIVATION_ENABLED", "false")
    get_settings.cache_clear()
    request = _xai_request()
    del request["prompt_cache_key"]

    response = await async_client.post("/v1/responses", json=request)

    assert response.status_code == 200
    key = fake_cliproxy.responses_payloads[0].get("prompt_cache_key")
    assert isinstance(key, str) and key.startswith("codex-lb-")


# --- stateful fields --------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field",
    [{"previous_response_id": "resp_earlier"}, {"store": True}, {"conversation": "conv_1"}],
)
async def test_stateful_fields_are_refused_before_any_reservation(async_client, fake_cliproxy, field):
    """CLIProxyAPI deletes previous_response_id, so the turn would lose its history."""

    await _enable_api_key_auth(async_client)
    key = await _create_api_key(
        "stateful",
        limits=[LimitRuleInput(limit_type="total_tokens", limit_window="weekly", max_value=100000)],
    )

    response = await async_client.post(
        "/v1/responses",
        json=_xai_request(**field),
        headers={"Authorization": f"Bearer {key.key}"},
    )

    assert response.status_code == 400
    assert "native Responses route" in response.json()["error"]["message"]
    assert fake_cliproxy.responses_payloads == []
    assert await _reservation_statuses() == []


# --- reasoning effort ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_client_effort_wins_over_the_operator_default(async_client, fake_cliproxy, monkeypatch):
    """Scout risk 4: the chat route overrides a client effort with the default."""

    from dataclasses import replace

    fake_cliproxy.config = replace(fake_cliproxy.config, default_reasoning_effort="low")

    await async_client.post("/v1/responses", json=_xai_request(reasoning={"effort": "high"}))
    request = _xai_request()
    del request["reasoning"]
    await async_client.post("/v1/responses", json=request)

    assert fake_cliproxy.responses_payloads[0]["reasoning"]["effort"] == "high"
    assert fake_cliproxy.responses_payloads[1]["reasoning"]["effort"] == "low"
    logs = sorted(await _sidecar_logs(), key=lambda log: log.id)
    assert [log.reasoning_effort for log in logs] == ["high", "low"]
    assert [log.requested_reasoning_effort for log in logs] == ["high", None]


# --- API keys: service tier and reservations ---------------------------------------


@pytest.mark.asyncio
async def test_api_key_service_tier_is_enforced_on_the_forwarded_body(async_client, fake_cliproxy):
    await _enable_api_key_auth(async_client)
    key = await _create_api_key("tier", enforced_service_tier="flex")

    response = await async_client.post(
        "/v1/responses",
        json=_xai_request(service_tier="priority"),
        headers={"Authorization": f"Bearer {key.key}"},
    )

    assert response.status_code == 200
    assert fake_cliproxy.responses_payloads[0]["service_tier"] == "flex"


@pytest.mark.asyncio
async def test_a_completed_turn_finalizes_its_reservation(async_client, fake_cliproxy):
    await _enable_api_key_auth(async_client)
    key = await _create_api_key(
        "reserve",
        limits=[LimitRuleInput(limit_type="total_tokens", limit_window="weekly", max_value=100000)],
    )

    response = await async_client.post(
        "/v1/responses",
        json=_xai_request(),
        headers={"Authorization": f"Bearer {key.key}"},
    )

    assert response.status_code == 200
    assert await _reservation_statuses() == ["finalized"]


@pytest.mark.asyncio
async def test_an_unreachable_cliproxy_releases_the_reservation(async_client, fake_cliproxy):
    await _enable_api_key_auth(async_client)
    key = await _create_api_key(
        "release",
        limits=[LimitRuleInput(limit_type="total_tokens", limit_window="weekly", max_value=100000)],
    )
    fake_cliproxy.responses_errors = [ClaudeSidecarUnavailableError("down")]

    response = await async_client.post(
        "/v1/responses",
        json=_xai_request(),
        headers={"Authorization": f"Bearer {key.key}"},
    )

    assert response.status_code == 503
    assert await _reservation_statuses() == ["released"]
    [log] = await _sidecar_logs()
    assert log.status == "error"


@pytest.mark.asyncio
async def test_an_upstream_error_is_relayed_and_releases_the_reservation(async_client, fake_cliproxy):
    await _enable_api_key_auth(async_client)
    key = await _create_api_key(
        "upstream-error",
        limits=[LimitRuleInput(limit_type="total_tokens", limit_window="weekly", max_value=100000)],
    )
    fake_cliproxy.responses_errors = [ClaudeSidecarError(400, "bad request from xai")]

    response = await async_client.post(
        "/v1/responses",
        json=_xai_request(),
        headers={"Authorization": f"Bearer {key.key}"},
    )

    assert response.status_code == 400
    assert await _reservation_statuses() == ["released"]


# --- usage and cost -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_streaming_usage_and_xai_cost_are_recorded(async_client, fake_cliproxy):
    """Scout risk 5: xAI's exact per-request cost was not recorded."""

    response = await async_client.post("/v1/responses", json=_xai_request())

    assert response.status_code == 200
    [log] = await _sidecar_logs()
    assert log.input_tokens == 1000
    assert log.cached_input_tokens == 900
    assert log.output_tokens == 50
    assert log.reasoning_tokens == 30
    assert log.cost_usd == pytest.approx(COST_TICKS / 10_000_000_000)
    assert log.cost_source == CostSource.UPSTREAM_BILLED.value
    assert log.model == XAI_MODEL


@pytest.mark.asyncio
async def test_streaming_usage_and_xai_cost_are_recorded(async_client, fake_cliproxy):
    async with async_client.stream("POST", "/v1/responses", json=_xai_request(stream=True)) as response:
        body = await response.aread()

    assert response.status_code == 200
    assert fake_cliproxy.stream_responses_payloads[0]["stream"] is True
    events = _sse_events(body)
    assert events[-1]["type"] == "response.completed"
    [log] = await _sidecar_logs()
    assert log.status == "success"
    assert log.cached_input_tokens == 900
    assert log.reasoning_tokens == 30
    assert log.cost_usd == pytest.approx(COST_TICKS / 10_000_000_000)
    assert log.cost_source == CostSource.UPSTREAM_BILLED.value


@pytest.mark.asyncio
async def test_a_zero_tick_cost_is_not_recorded_as_billed(async_client, fake_cliproxy):
    """A subscription login reports zero; that is not a free request."""

    fake_cliproxy.response_usage = _xai_usage(cost_ticks=0)

    await async_client.post("/v1/responses", json=_xai_request())

    [log] = await _sidecar_logs()
    assert log.cost_source != CostSource.UPSTREAM_BILLED.value


# --- streaming relay ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_stream_is_relayed_byte_for_byte(async_client, fake_cliproxy):
    """Upstream chunks split anywhere; the client still gets the exact bytes."""

    events = _stream_events(XAI_MODEL, usage=_xai_usage())
    whole = b"".join(events)
    # Cut mid-event and mid-JSON to prove re-framing is lossless.
    fake_cliproxy.stream_chunks = [whole[:7], whole[7:150], whole[150:151], whole[151:]]

    async with async_client.stream("POST", "/v1/responses", json=_xai_request(stream=True)) as response:
        body = await response.aread()

    assert body.replace(b": keep-alive\n\n", b"") == whole
    assert ENCRYPTED_REASONING.encode() in body


@pytest.mark.asyncio
async def test_a_stream_without_a_terminal_event_ends_as_failed(async_client, fake_cliproxy):
    fake_cliproxy.stream_chunks = _stream_events(XAI_MODEL, usage=_xai_usage())[:-1]

    async with async_client.stream("POST", "/v1/responses", json=_xai_request(stream=True)) as response:
        body = await response.aread()

    events = _sse_events(body)
    assert events[-1]["type"] == "response.failed"
    [log] = await _sidecar_logs()
    assert log.status == "error"
    assert log.error_code == "claude_sidecar_stream_incomplete"


@pytest.mark.asyncio
async def test_an_upstream_failed_event_is_logged_as_an_error_and_still_charged(async_client, fake_cliproxy):
    fake_cliproxy.stream_chunks = _stream_events(XAI_MODEL, usage=_xai_usage(), terminal="response.failed")

    async with async_client.stream("POST", "/v1/responses", json=_xai_request(stream=True)) as response:
        await response.aread()

    [log] = await _sidecar_logs()
    assert log.status == "error"
    assert log.error_code == "server_error"
    assert log.cost_source == CostSource.UPSTREAM_BILLED.value


@pytest.mark.asyncio
async def test_a_stream_that_cannot_open_ends_as_response_failed(async_client, fake_cliproxy):
    await _enable_api_key_auth(async_client)
    key = await _create_api_key(
        "stream-down",
        limits=[LimitRuleInput(limit_type="total_tokens", limit_window="weekly", max_value=100000)],
    )
    fake_cliproxy.stream_errors = [ClaudeSidecarUnavailableError("down")]

    async with async_client.stream(
        "POST",
        "/v1/responses",
        json=_xai_request(stream=True),
        headers={"Authorization": f"Bearer {key.key}"},
    ) as response:
        body = await response.aread()

    events = _sse_events(body)
    assert [event["type"] for event in events] == ["response.failed"]
    assert await _reservation_statuses() == ["released"]


# --- route selection -------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_switch_returns_xai_to_the_chat_bridge(async_client, fake_cliproxy, native_disabled):
    del native_disabled
    response = await async_client.post("/v1/responses", json=_xai_request())

    assert response.status_code == 200
    assert fake_cliproxy.responses_payloads == []
    assert len(fake_cliproxy.chat_payloads) == 1


@pytest.mark.asyncio
async def test_claude_stays_on_the_chat_bridge(async_client, fake_cliproxy):
    response = await async_client.post(
        "/v1/responses",
        json={"model": CLAUDE_MODEL, "input": "hi"},
    )

    assert response.status_code == 200
    assert fake_cliproxy.responses_payloads == []
    assert len(fake_cliproxy.chat_payloads) == 1


@pytest.mark.asyncio
async def test_a_prefixed_grok_id_stays_on_the_chat_bridge(async_client, fake_cliproxy):
    """``devin/grok-4-6`` names another executor; its body is not xAI's."""

    response = await async_client.post("/v1/responses", json={"model": "devin/grok-4-6", "input": "hi"})

    assert response.status_code == 200
    assert fake_cliproxy.responses_payloads == []
    assert len(fake_cliproxy.chat_payloads) == 1


@pytest.mark.asyncio
async def test_chat_completions_for_xai_are_unchanged(async_client, fake_cliproxy):
    response = await async_client.post(
        "/v1/chat/completions",
        json={"model": XAI_MODEL, "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert fake_cliproxy.responses_payloads == []
    assert len(fake_cliproxy.chat_payloads) == 1


@pytest.mark.asyncio
async def test_the_route_is_counted(async_client, fake_cliproxy, monkeypatch):
    counted: list[str] = []

    class _Counter:
        def labels(self, *, route: str):
            counted.append(route)
            return self

        def inc(self) -> None:
            return None

    monkeypatch.setattr(cliproxy_responses_dispatch, "cliproxy_xai_responses_route_total", _Counter())

    await async_client.post("/v1/responses", json=_xai_request())

    assert counted == ["native"]


@pytest.mark.asyncio
async def test_a_failed_credential_moves_the_request_once(async_client, fake_cliproxy, monkeypatch):
    """PR #148 parity: 401/403/429 rebinds the pin before the error reaches the client."""

    rebinds: list[str] = []

    async def fake_rebind(body, *, client):
        del client
        rebinds.append(str(body["model"]))
        body["model"] = f"spare/{XAI_MODEL}"
        return object()

    monkeypatch.setattr(cliproxy_responses_dispatch, "rebind_cliproxy_account_route", fake_rebind)
    monkeypatch.setattr(cliproxy_responses_dispatch, "apply_cliproxy_account_route", AsyncMock(return_value=None))
    fake_cliproxy.responses_errors = [ClaudeSidecarError(429, "rate limited")]

    response = await async_client.post("/v1/responses", json=_xai_request())

    assert response.status_code == 200
    assert rebinds == [XAI_MODEL]
    assert [payload["model"] for payload in fake_cliproxy.responses_payloads] == [XAI_MODEL, f"spare/{XAI_MODEL}"]


@pytest.mark.asyncio
async def test_the_account_route_sees_the_cache_key_it_pins_on(async_client, fake_cliproxy, monkeypatch):
    """The pin key and the forwarded prompt_cache_key must be the same id."""

    seen: list[tuple[str | None, str | None]] = []

    async def fake_route(body, *, headers, client, hints):
        del headers, client
        seen.append((hints.prompt_cache_key, body.get("prompt_cache_key")))
        return None

    monkeypatch.setattr(cliproxy_responses_dispatch, "apply_cliproxy_account_route", fake_route)

    await async_client.post("/v1/responses", json=_xai_request())

    assert seen == [("thread-xai-1", "thread-xai-1")]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429])
async def test_a_failed_credential_moves_a_stream_once(async_client, fake_cliproxy, monkeypatch, status):
    """PR #148 parity on the streaming path: rebind before any byte reaches the client."""

    rebinds: list[str] = []

    async def fake_rebind(body, *, client):
        del client
        rebinds.append(str(body["model"]))
        body["model"] = f"spare/{XAI_MODEL}"
        return object()

    monkeypatch.setattr(cliproxy_responses_dispatch, "rebind_cliproxy_account_route", fake_rebind)
    monkeypatch.setattr(cliproxy_responses_dispatch, "apply_cliproxy_account_route", AsyncMock(return_value=None))
    fake_cliproxy.stream_errors = [ClaudeSidecarError(status, "credential refused")]

    async with async_client.stream("POST", "/v1/responses", json=_xai_request(stream=True)) as response:
        body = await response.aread()

    assert response.status_code == 200
    assert rebinds == [XAI_MODEL]
    assert [payload["model"] for payload in fake_cliproxy.stream_responses_payloads] == [
        XAI_MODEL,
        f"spare/{XAI_MODEL}",
    ]
    assert _sse_events(body)[-1]["type"] == "response.completed"
    [log] = await _sidecar_logs()
    assert log.status == "success"


@pytest.mark.asyncio
async def test_a_stream_rebinds_only_once(async_client, fake_cliproxy, monkeypatch):
    rebind = AsyncMock(return_value=object())
    monkeypatch.setattr(cliproxy_responses_dispatch, "rebind_cliproxy_account_route", rebind)
    monkeypatch.setattr(cliproxy_responses_dispatch, "apply_cliproxy_account_route", AsyncMock(return_value=None))
    fake_cliproxy.stream_errors = [ClaudeSidecarError(429, "limited"), ClaudeSidecarError(429, "limited again")]

    async with async_client.stream("POST", "/v1/responses", json=_xai_request(stream=True)) as response:
        body = await response.aread()

    assert rebind.await_count == 1
    assert len(fake_cliproxy.stream_responses_payloads) == 2
    assert _sse_events(body)[-1]["type"] == "response.failed"
    [log] = await _sidecar_logs()
    assert log.status == "error"


@pytest.fixture
def _cooldown_wait(monkeypatch):
    """A real cooldown budget with no sleep, so the retry loop runs instantly."""

    monkeypatch.setattr("app.modules.proxy.claude_sidecar_dispatch.CLAUDE_SIDECAR_COOLDOWN_WAIT_SECONDS", 5.0)
    monkeypatch.setattr("app.modules.proxy.claude_sidecar_dispatch.CLAUDE_SIDECAR_COOLDOWN_RETRY_SLEEP_SECONDS", 0.0)
    reset_claude_sidecar_cooldown_gate()
    yield
    reset_claude_sidecar_cooldown_gate()


@pytest.mark.asyncio
async def test_a_cooling_pool_is_waited_out_non_streaming(async_client, fake_cliproxy, _cooldown_wait):
    """CLIProxyAPI's auth_unavailable 503 is retried, as on the chat route."""

    fake_cliproxy.responses_errors = [ClaudeSidecarError(503, "auth_unavailable: no auth available")]

    response = await async_client.post("/v1/responses", json=_xai_request())

    assert response.status_code == 200
    assert len(fake_cliproxy.responses_payloads) == 2
    [log] = await _sidecar_logs()
    assert log.status == "success"


@pytest.mark.asyncio
async def test_a_cooling_pool_is_waited_out_streaming(async_client, fake_cliproxy, _cooldown_wait):
    fake_cliproxy.stream_errors = [ClaudeSidecarError(503, "auth_unavailable: no auth available")]

    async with async_client.stream("POST", "/v1/responses", json=_xai_request(stream=True)) as response:
        body = await response.aread()

    assert len(fake_cliproxy.stream_responses_payloads) == 2
    assert _sse_events(body)[-1]["type"] == "response.completed"
    [log] = await _sidecar_logs()
    assert log.status == "success"


@pytest.mark.asyncio
async def test_a_non_cooldown_stream_error_is_not_retried(async_client, fake_cliproxy, _cooldown_wait):
    fake_cliproxy.stream_errors = [ClaudeSidecarError(500, "upstream exploded")]

    async with async_client.stream("POST", "/v1/responses", json=_xai_request(stream=True)) as response:
        body = await response.aread()

    assert len(fake_cliproxy.stream_responses_payloads) == 1
    assert _sse_events(body)[-1]["type"] == "response.failed"
