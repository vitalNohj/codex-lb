from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.clients.claude_sidecar import SidecarPrefix
from app.core.clients.openai_compat_sidecar import (
    OpenAICompatSidecarConfig,
    OpenAICompatSidecarError,
    OpenAICompatSidecarUnavailableError,
)
from app.core.openai.model_registry import ReasoningLevel, UpstreamModel, get_model_registry
from app.db.models import ApiKeyUsageReservation, RequestLog
from app.db.session import SessionLocal
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeyCreateData, ApiKeysService, LimitRuleInput
from app.modules.proxy.cursor_chat_compat import CURSOR_CONTEXT_LIMIT_SYNTHETIC_USAGE_TOKENS

pytestmark = pytest.mark.integration

ENDPOINT_ID = "2c9b8f3a-1e4d-4b7a-9c11-7a0e4d2b1c0a"
PROVIDER_ID = f"openai_compat:{ENDPOINT_ID}"
MODEL = "Qwen/Qwen2.5-7B"


@dataclass(frozen=True, slots=True)
class _FakeModel:
    id: str
    created: int | None = 123
    owned_by: str | None = "openai_compat"
    raw: dict | None = None


class _FakeOpenAICompatClient:
    def __init__(self, config: OpenAICompatSidecarConfig) -> None:
        self.config = config
        self.chat_payloads: list[dict] = []
        self.stream_payloads: list[dict] = []
        self.models = [_FakeModel(MODEL)]
        self.chat_error: Exception | None = None
        self.stream_error: Exception | None = None
        self.stream_include_usage = True
        self.stream_context_error = False
        self.stream_provider_error = False
        self.stream_tool_calls = False

    async def list_models_cached(self):
        return self.models

    async def chat_completion(self, payload):
        self.chat_payloads.append(dict(payload))
        if self.chat_error is not None:
            raise self.chat_error
        return {
            "id": "chatcmpl-compat",
            "object": "chat.completion",
            "model": payload["model"],
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

    def stream_chat_completion(self, payload):
        self.stream_payloads.append(dict(payload))
        return _FakeStreamContext(
            self.stream_error,
            include_usage=self.stream_include_usage,
            context_error=self.stream_context_error,
            provider_error=self.stream_provider_error,
            tool_calls=self.stream_tool_calls,
        )


class _FakeStreamContext:
    def __init__(
        self,
        error: Exception | None,
        *,
        include_usage: bool = True,
        context_error: bool = False,
        provider_error: bool = False,
        tool_calls: bool = False,
    ) -> None:
        self.error = error
        self.include_usage = include_usage
        self.context_error = context_error
        self.provider_error = provider_error
        self.tool_calls = tool_calls

    async def __aenter__(self):
        if self.error is not None:
            raise self.error

        async def chunks():
            if self.tool_calls:
                yield (
                    b'data: {"id":"chunk-1","object":"chat.completion.chunk","choices":[{"delta":'
                    b'{"tool_calls":[{"index":0,"id":"call_1","type":"function","function":'
                    b'{"name":"lookup","arguments":"{}"}}]}}]}\n\n'
                )
                yield b"data: [DONE]\n\n"
                return
            yield b'data: {"id":"chunk-1","object":"chat.completion.chunk","choices":[{"delta":{"content":"hi"}}]}\n\n'
            if self.context_error:
                yield (b'data: {"error":{"code":"context_length_exceeded","message":"Input token limit exceeded"}}\n\n')
                yield b"data: [DONE]\n\n"
                return
            if self.provider_error:
                yield (b'data: {"error":{"code":"upstream_error","message":"compat overloaded"}}\n\n')
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


_CATALOG_CONTROL_REFUSED: tuple[str, ...] = (
    "ClaudeSidecarClient",
    "OpenRouterSidecarClient",
    "OrcaRouterSidecarClient",
    "get_orcarouter_sidecar_client",
    "OmniRouteSidecarClient",
    "OllamaSidecarClient",
    "_source_chat_completion_response",
    "collect_chat_completion",
    "_probe_chat_stream_startup_error",
)


class _UnexpectedTransport(Exception):
    """A transport other than the expected OpenAI-compat fake was constructed."""


@pytest.fixture
def block_unexpected_transports(monkeypatch):
    def _refuse(name: str):
        def _factory(*args, **kwargs):
            del args, kwargs
            raise _UnexpectedTransport(name)

        return _factory

    for name in _CATALOG_CONTROL_REFUSED:
        monkeypatch.setattr(f"app.modules.proxy.api.{name}", _refuse(name), raising=True)

    from app.modules.proxy.service import ProxyService

    monkeypatch.setattr(ProxyService, "stream_responses", _refuse("ProxyService.stream_responses"), raising=True)


@pytest_asyncio.fixture
async def lifespan_free_client(_reset_db_state, block_unexpected_transports, fake_openai_compat, monkeypatch):
    del _reset_db_state, block_unexpected_transports
    import app.modules.proxy.api as proxy_api
    from app.main import create_app

    monkeypatch.setattr(
        "app.modules.proxy.api.OpenAICompatSidecarClient",
        lambda _config: fake_openai_compat,
        raising=True,
    )
    monkeypatch.setattr(
        "app.modules.proxy.api.get_openai_compat_sidecar_client",
        lambda _config: fake_openai_compat,
        raising=True,
    )

    app = create_app()

    async def _drain_proxy_persistence(response) -> None:
        del response
        service = getattr(app.state, "proxy_service", None)
        if service is not None and hasattr(service, "drain_persistence_tasks"):
            await service.drain_persistence_tasks(timeout_seconds=5)

    assert proxy_api.__file__.startswith(str(Path(__file__).resolve().parents[2])), (
        f"app module resolved outside this task copy: {proxy_api.__file__}"
    )
    assert proxy_api.OpenAICompatSidecarClient(fake_openai_compat.config) is fake_openai_compat
    assert proxy_api.get_openai_compat_sidecar_client(fake_openai_compat.config) is fake_openai_compat
    for name in _CATALOG_CONTROL_REFUSED:
        with pytest.raises(_UnexpectedTransport):
            getattr(proxy_api, name)()

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        event_hooks={"response": [_drain_proxy_persistence]},
    ) as client:
        yield client


@pytest.fixture
async def fake_openai_compat(monkeypatch):
    config = OpenAICompatSidecarConfig(
        endpoint_id=ENDPOINT_ID,
        name="Vast",
        enabled=True,
        base_url="https://openai.vast.ai/demo/v1",
        api_key=None,
        prefixes=(SidecarPrefix(prefix="vast/", strip=True),),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
        full_models=(MODEL,),
    )
    client = _FakeOpenAICompatClient(config)

    async def load_configs():
        return (config,)

    async def load_claude_disabled():
        return None

    monkeypatch.setattr("app.modules.proxy.api.load_openai_compat_configs", load_configs)
    monkeypatch.setattr("app.modules.proxy.api.OpenAICompatSidecarClient", lambda _config: client)
    monkeypatch.setattr("app.modules.proxy.api.get_openai_compat_sidecar_client", lambda _config: client)
    monkeypatch.setattr("app.modules.proxy.api.load_sidecar_config", load_claude_disabled)
    return client


async def _enable_api_key_auth(async_client) -> None:
    response = await async_client.put("/api/settings", json={"apiKeyAuthEnabled": True})
    assert response.status_code == 200


async def _create_api_key(
    name: str,
    *,
    allowed_models: list[str] | None = None,
    limits: list[LimitRuleInput] | None = None,
    enforced_service_tier: str | None = None,
):
    async with SessionLocal() as session:
        service = ApiKeysService(ApiKeysRepository(session))
        return await service.create_key(
            ApiKeyCreateData(
                name=name,
                allowed_models=allowed_models,
                limits=limits or [],
                enforced_service_tier=enforced_service_tier,
            )
        )


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
async def test_openai_compat_non_stream_routes_and_finalizes_reservation(
    async_client,
    fake_openai_compat,
):
    await _enable_api_key_auth(async_client)
    key = await _create_api_key(
        "compat-key",
        limits=[LimitRuleInput(limit_type="total_tokens", limit_window="weekly", max_value=1000)],
    )

    response = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}"},
        json={"model": MODEL, "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "hi"
    assert fake_openai_compat.chat_payloads[0]["model"] == MODEL
    assert await _reservation_statuses() == ["finalized"]
    async with SessionLocal() as session:
        logs = list((await session.execute(select(RequestLog))).scalars().all())
    sidecar_logs = [log for log in logs if log.source == PROVIDER_ID]
    assert len(sidecar_logs) == 1
    assert sidecar_logs[0].model == MODEL
    assert sidecar_logs[0].transport == "http"


@pytest.mark.asyncio
async def test_openai_compat_model_list_merges_and_filters(lifespan_free_client, fake_openai_compat):
    from app.core.cache.invalidation import get_cache_invalidation_poller

    assert get_cache_invalidation_poller() is None

    await _enable_api_key_auth(lifespan_free_client)
    registry = get_model_registry()
    await registry.update({"plus": [_make_upstream_model("gpt-5.4")]})
    key = await _create_api_key("models-key", allowed_models=[MODEL])

    response = await lifespan_free_client.get("/v1/models", headers={"Authorization": f"Bearer {key.key}"})

    assert response.status_code == 200
    data = response.json()["data"]
    ids = [item["id"] for item in data]
    assert MODEL in ids
    assert "gpt-5.4" not in ids

    sidecar_entry = next(item for item in data if item["id"] == MODEL)
    assert sidecar_entry["context_length"] == 200_000
    assert sidecar_entry["capabilities"]["context_length"] == 200_000
    assert sidecar_entry["owned_by"] == "openai_compat"
    # No catalog modality metadata: do not advertise image input.
    assert sidecar_entry["supports_vision"] is False
    assert sidecar_entry["supportsVision"] is False
    assert sidecar_entry["capabilities"]["input_modalities"] == ["text"]


@pytest.mark.asyncio
async def test_gpt_request_does_not_hit_openai_compat(async_client, fake_openai_compat):
    response = await async_client.post(
        "/v1/chat/completions",
        json={"model": "gpt-5.4", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code in {502, 503}
    assert fake_openai_compat.chat_payloads == []
    assert fake_openai_compat.stream_payloads == []


@pytest.mark.asyncio
async def test_openai_compat_unavailable_returns_503(async_client, fake_openai_compat):
    fake_openai_compat.chat_error = OpenAICompatSidecarUnavailableError("upstream down")

    response = await async_client.post(
        "/v1/chat/completions",
        json={"model": MODEL, "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "openai_compat_unavailable"


@pytest.mark.asyncio
async def test_openai_compat_cursor_stream_applies_usage_fallback(async_client, fake_openai_compat):
    fake_openai_compat.stream_include_usage = False

    async with async_client.stream(
        "POST",
        "/v1/chat/completions",
        headers={"User-Agent": "Cursor/1.0"},
        json={"model": MODEL, "messages": [{"role": "user", "content": "hi"}], "stream": True},
    ) as response:
        body = await response.aread()

    assert response.status_code == 200
    usage_chunks = _usage_chunks(_chat_sse_payloads(body))
    assert len(usage_chunks) == 1
    usage = usage_chunks[0]["usage"]
    assert usage["prompt_tokens"] > 0
    assert usage["completion_tokens"] > 0
    assert usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]
    assert body.rstrip().endswith(b"data: [DONE]")


@pytest.mark.asyncio
async def test_openai_compat_cursor_stream_context_limit_returns_synthetic_usage(async_client, fake_openai_compat):
    fake_openai_compat.stream_context_error = True

    async with async_client.stream(
        "POST",
        "/v1/chat/completions",
        headers={"User-Agent": "Cursor/1.0"},
        json={"model": MODEL, "messages": [{"role": "user", "content": "too much context"}], "stream": True},
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
async def test_cursor_context_limit_error_is_logged_as_success_and_releases_its_reservation(
    async_client, fake_openai_compat
):
    await _enable_api_key_auth(async_client)
    key = await _create_api_key(
        "cursor-context-limit-key",
        limits=[LimitRuleInput(limit_type="total_tokens", limit_window="weekly", max_value=1000)],
    )
    fake_openai_compat.chat_error = OpenAICompatSidecarError(
        400,
        "This endpoint's maximum context length is 163840 tokens",
        body={"error": {"code": "context_length_exceeded", "message": "maximum context length"}},
    )

    response = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}", "User-Agent": "Cursor/1.0"},
        json={"model": MODEL, "messages": [{"role": "user", "content": "too much"}]},
    )

    assert response.status_code == 200
    assert response.json()["usage"]["prompt_tokens"] == CURSOR_CONTEXT_LIMIT_SYNTHETIC_USAGE_TOKENS

    async with SessionLocal() as session:
        logs = list((await session.execute(select(RequestLog))).scalars().all())
    sidecar_logs = [log for log in logs if log.source == PROVIDER_ID]
    assert not [log for log in sidecar_logs if log.status == "error"]
    assert not [log for log in sidecar_logs if log.error_code == "openai_compat_error"]
    assert await _reservation_statuses() == ["released"]


@pytest.mark.asyncio
async def test_openai_compat_non_cursor_stream_does_not_apply_usage_fallback(async_client, fake_openai_compat):
    fake_openai_compat.stream_include_usage = False

    async with async_client.stream(
        "POST",
        "/v1/chat/completions",
        json={"model": MODEL, "messages": [{"role": "user", "content": "hi"}], "stream": True},
    ) as response:
        body = await response.aread()

    assert response.status_code == 200
    assert _usage_chunks(_chat_sse_payloads(body)) == []
    assert body.rstrip().endswith(b"data: [DONE]")


@pytest.mark.asyncio
async def test_openai_compat_alias_is_discoverable_and_routes(async_client, fake_openai_compat):
    await async_client.put(
        "/api/settings",
        json={"modelAliases": {"alias-qwen": MODEL}},
    )

    models_response = await async_client.get("/v1/models")
    assert models_response.status_code == 200
    ids = {item["id"] for item in models_response.json()["data"]}
    assert "alias-qwen" in ids

    response = await async_client.post(
        "/v1/chat/completions",
        json={"model": "alias-qwen", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert fake_openai_compat.chat_payloads
    assert fake_openai_compat.chat_payloads[0]["model"] == MODEL


@pytest.mark.asyncio
async def test_openai_compat_strip_prefix_forwards_wire_model(async_client, fake_openai_compat):
    response = await async_client.post(
        "/v1/chat/completions",
        json={"model": f"vast/{MODEL}", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert fake_openai_compat.chat_payloads[0]["model"] == MODEL


@pytest.mark.asyncio
async def test_openai_compat_allowlist_hides_unlisted_full_model(lifespan_free_client, fake_openai_compat):
    await _enable_api_key_auth(lifespan_free_client)
    registry = get_model_registry()
    await registry.update({"plus": [_make_upstream_model("gpt-5.4")]})
    key = await _create_api_key("gpt-only-key", allowed_models=["gpt-5.4"])

    response = await lifespan_free_client.get("/v1/models", headers={"Authorization": f"Bearer {key.key}"})

    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["data"]]
    assert MODEL not in ids


@pytest.mark.asyncio
async def test_disabled_openai_compat_does_not_dispatch(async_client, fake_openai_compat, monkeypatch):
    async def load_disabled():
        return (
            OpenAICompatSidecarConfig(
                endpoint_id=ENDPOINT_ID,
                name="Vast",
                enabled=False,
                base_url="https://openai.vast.ai/demo/v1",
                api_key=None,
                prefixes=(),
                connect_timeout_seconds=8.0,
                request_timeout_seconds=600.0,
                models_cache_ttl_seconds=60.0,
                full_models=(MODEL,),
            ),
        )

    monkeypatch.setattr("app.modules.proxy.api.load_openai_compat_configs", load_disabled)

    response = await async_client.post(
        "/v1/chat/completions",
        json={"model": MODEL, "messages": [{"role": "user", "content": "hi"}]},
    )

    assert fake_openai_compat.chat_payloads == []
    assert fake_openai_compat.stream_payloads == []
    assert response.status_code in {400, 502, 503}


_IMAGE = "data:image/png;base64,AAAA"


def _image_input() -> dict:
    return {
        "model": MODEL,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "what is this"},
                    {"type": "input_image", "image_url": _IMAGE},
                ],
            }
        ],
    }


def _assert_image_survived(payload: dict) -> None:
    messages = payload["messages"]
    parts = messages[-1]["content"]
    assert isinstance(parts, list)
    assert {"type": "image_url", "image_url": {"url": _IMAGE}} in parts


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/v1/responses", "/backend-api/codex/responses"])
async def test_responses_openai_compat_preserves_image(async_client, fake_openai_compat, path):
    response = await async_client.post(path, json=_image_input())

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "response"
    assert body["model"] == MODEL
    assert body["output"][0]["content"][0]["text"] == "hi"
    assert len(fake_openai_compat.chat_payloads) == 1
    _assert_image_survived(fake_openai_compat.chat_payloads[0])
    assert fake_openai_compat.stream_payloads == []


@pytest.mark.asyncio
async def test_responses_openai_compat_streams_image(async_client, fake_openai_compat):
    payload = _image_input()
    payload["stream"] = True
    async with async_client.stream("POST", "/v1/responses", json=payload) as response:
        body = await response.aread()

    assert response.status_code == 200
    assert body.rstrip().endswith(b"data: [DONE]")
    assert b"hi" in body
    assert body.count(b"data: [DONE]") == 1
    assert len(fake_openai_compat.stream_payloads) == 1
    _assert_image_survived(fake_openai_compat.stream_payloads[0])


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/v1/responses", "/backend-api/codex/responses"])
async def test_responses_openai_compat_preserves_function_call_history(async_client, fake_openai_compat, path):
    response = await async_client.post(
        path,
        json={
            "model": MODEL,
            "input": [
                {"type": "function_call", "call_id": "call_1", "name": "lookup", "arguments": "{}"},
                {"type": "function_call_output", "call_id": "call_1", "output": "72F"},
            ],
        },
    )

    assert response.status_code == 200, response.text
    assert len(fake_openai_compat.chat_payloads) == 1
    messages = fake_openai_compat.chat_payloads[0]["messages"]
    assert messages[0]["tool_calls"][0]["id"] == "call_1"
    assert messages[0]["tool_calls"][0]["function"]["name"] == "lookup"
    assert messages[1] == {"role": "tool", "tool_call_id": "call_1", "content": "72F"}


@pytest.mark.asyncio
async def test_responses_openai_compat_streams_function_calls(async_client, fake_openai_compat):
    fake_openai_compat.stream_tool_calls = True
    payload = {"model": MODEL, "input": "lookup the weather", "stream": True}

    async with async_client.stream("POST", "/v1/responses", json=payload) as response:
        body = await response.aread()

    assert response.status_code == 200, body
    assert b"response.function_call_arguments.done" in body
    assert b'"call_id": "call_1"' in body or b'"call_id":"call_1"' in body
    assert b'"name": "lookup"' in body or b'"name":"lookup"' in body
    assert body.count(b"data: [DONE]") == 1
    assert b'"type": "message"' not in body and b'"type":"message"' not in body


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("enforced_service_tier", "expected_service_tier"),
    [("priority", "priority"), ("auto", None)],
)
async def test_responses_openai_compat_uses_enforced_service_tier(
    async_client,
    fake_openai_compat,
    enforced_service_tier,
    expected_service_tier,
):
    await _enable_api_key_auth(async_client)
    key = await _create_api_key(
        f"compat-tier-{enforced_service_tier}",
        allowed_models=[MODEL],
        enforced_service_tier=enforced_service_tier,
    )

    response = await async_client.post(
        "/v1/responses",
        headers={"Authorization": f"Bearer {key.key}"},
        json={"model": MODEL, "input": "hi", "service_tier": "flex"},
    )

    assert response.status_code == 200, response.text
    assert len(fake_openai_compat.chat_payloads) == 1
    assert fake_openai_compat.chat_payloads[0].get("service_tier") == expected_service_tier


@pytest.mark.asyncio
async def test_responses_openai_compat_missing_client_does_not_reserve(
    async_client,
    fake_openai_compat,
    monkeypatch,
):
    await _enable_api_key_auth(async_client)
    key = await _create_api_key(
        "compat-missing-client",
        allowed_models=[MODEL],
        limits=[LimitRuleInput(limit_type="total_tokens", limit_window="weekly", max_value=1000)],
    )

    async def _missing_client(_provider: str) -> None:
        return None

    monkeypatch.setattr("app.modules.proxy.api._responses_chat_provider_client", _missing_client)

    response = await async_client.post(
        "/v1/responses",
        headers={"Authorization": f"Bearer {key.key}"},
        json={"model": MODEL, "input": "hi"},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "sidecar_not_configured"
    assert fake_openai_compat.chat_payloads == []
    assert fake_openai_compat.stream_payloads == []
    assert await _reservation_statuses() == []


@pytest.mark.asyncio
async def test_responses_openai_compat_catalog_image_modality(lifespan_free_client, fake_openai_compat):
    fake_openai_compat.models = [
        _FakeModel(MODEL, raw={"architecture": {"modality": "text+image->text"}}),
    ]

    response = await lifespan_free_client.get("/v1/models")

    assert response.status_code == 200
    entry = next(item for item in response.json()["data"] if item["id"] == MODEL)
    assert entry["supports_vision"] is True
    assert entry["supportsVision"] is True
    assert entry["supports_images"] is True
    assert entry["capabilities"]["input_modalities"] == ["text", "image"]


@pytest.mark.asyncio
async def test_responses_unknown_authoritative_model_skips_codex(lifespan_free_client, fake_openai_compat):
    registry = get_model_registry()
    state = await registry.export_state()
    try:
        await registry.clear()
        served = _make_upstream_model("gpt-5.4")
        await registry.update(
            {"plus": [served]},
            per_account_results={"acct": ("plus", [served])},
            active_account_plans={"acct": "plus"},
        )
        snapshot = registry.get_snapshot()
        assert snapshot is not None and snapshot.account_catalogs_authoritative

        missing = await lifespan_free_client.post(
            "/v1/responses",
            json={"model": "nvidia/nemotron-3-content-safety", "input": "hi"},
        )
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "model_not_found"
        assert fake_openai_compat.chat_payloads == []
        assert fake_openai_compat.stream_payloads == []

        served_response = await lifespan_free_client.post(
            "/v1/responses",
            json={"model": "gpt-5.4", "input": "hi"},
        )
        assert served_response.status_code == 503
        assert served_response.json()["error"]["code"] == "no_accounts"
    finally:
        await registry.import_state(state, content_hash="restore-responses-routing")


@pytest.mark.asyncio
async def test_responses_nonauthoritative_unknown_still_reaches_codex(lifespan_free_client, fake_openai_compat):
    registry = get_model_registry()
    state = await registry.export_state()
    try:
        await registry.clear()
        response = await lifespan_free_client.post(
            "/v1/responses",
            json={"model": "nvidia/not-in-a-catalog", "input": "hi"},
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "no_accounts"
        assert fake_openai_compat.chat_payloads == []
        assert fake_openai_compat.stream_payloads == []
    finally:
        await registry.import_state(state, content_hash="restore-responses-routing")


@pytest.mark.asyncio
async def test_compact_rejects_openai_compat_model(lifespan_free_client, fake_openai_compat):
    response = await lifespan_free_client.post(
        "/v1/responses/compact",
        json={"model": MODEL, "input": "hello"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "model_requires_responses_http"
    assert fake_openai_compat.chat_payloads == []
    assert fake_openai_compat.stream_payloads == []


@pytest.mark.asyncio
async def test_openai_compat_stream_provider_error_then_done_is_logged_as_error(
    async_client,
    fake_openai_compat,
):
    fake_openai_compat.stream_provider_error = True

    async with async_client.stream(
        "POST",
        "/v1/chat/completions",
        json={"model": MODEL, "messages": [{"role": "user", "content": "hi"}], "stream": True},
    ) as response:
        body = await response.aread()

    assert response.status_code == 200
    assert b'"error"' in body
    async with SessionLocal() as session:
        logs = list((await session.execute(select(RequestLog))).scalars().all())
    sidecar_logs = [log for log in logs if log.source == PROVIDER_ID]
    assert sidecar_logs
    assert sidecar_logs[-1].status == "error"
    assert sidecar_logs[-1].error_code == "upstream_error"
    assert sidecar_logs[-1].error_message == "compat overloaded"
