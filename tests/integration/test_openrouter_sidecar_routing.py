from __future__ import annotations

import json
from dataclasses import dataclass

import pytest
from sqlalchemy import select

from app.core.clients.openrouter_sidecar import (
    OpenRouterSidecarConfig,
    OpenRouterSidecarUnavailableError,
)
from app.core.config.settings import get_settings
from app.core.openai.model_registry import ReasoningLevel, UpstreamModel, get_model_registry
from app.db.models import ApiKeyUsageReservation, RequestLog
from app.db.session import SessionLocal
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeyCreateData, ApiKeysService, LimitRuleInput
from app.modules.proxy.cursor_chat_compat import CURSOR_CONTEXT_LIMIT_SYNTHETIC_USAGE_TOKENS

pytestmark = pytest.mark.integration


@dataclass(frozen=True, slots=True)
class _FakeModel:
    id: str
    created: int | None = 123
    owned_by: str | None = "openrouter"


class _FakeOpenRouterClient:
    def __init__(self, config: OpenRouterSidecarConfig) -> None:
        self.config = config
        self.chat_payloads: list[dict] = []
        self.stream_payloads: list[dict] = []
        self.models = [_FakeModel("deepseek/deepseek-chat")]
        self.chat_error: Exception | None = None
        self.stream_error: Exception | None = None
        self.stream_include_usage = True
        self.stream_context_error = False

    async def list_models_cached(self):
        return self.models

    async def chat_completion(self, payload):
        self.chat_payloads.append(dict(payload))
        if self.chat_error is not None:
            raise self.chat_error
        return {
            "id": "chatcmpl-openrouter",
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
                yield (
                    b'data: {"error":{"code":"context_length_exceeded",'
                    b'"message":"Input token limit exceeded"}}\n\n'
                )
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
async def openrouter_enabled(monkeypatch):
    monkeypatch.setenv("CODEX_LB_OPENROUTER_SIDECAR_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def fake_openrouter(monkeypatch):
    config = OpenRouterSidecarConfig(
        enabled=True,
        base_url="https://openrouter.ai/api/v1",
        api_key="openrouter-key",
        model_prefixes=("deepseek/",),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
    )
    client = _FakeOpenRouterClient(config)

    async def load_config():
        return config

    monkeypatch.setattr("app.modules.proxy.api.load_openrouter_sidecar_config", load_config)
    monkeypatch.setattr("app.modules.proxy.api.OpenRouterSidecarClient", lambda _config: client)
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
        return await service.create_key(ApiKeyCreateData(name=name, allowed_models=allowed_models, limits=limits))


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
async def test_openrouter_non_stream_routes_to_sidecar_and_finalizes_reservation(
    async_client,
    openrouter_enabled,
    fake_openrouter,
):
    await async_client.put(
        "/api/settings",
        json={
            "openrouterSidecarEnabled": True,
            "openrouterSidecarApiKey": "openrouter-key",
            "openrouterSidecarModelPrefixes": ["deepseek/"],
        },
    )
    await _enable_api_key_auth(async_client)
    key = await _create_api_key(
        "openrouter-key",
        limits=[LimitRuleInput(limit_type="total_tokens", limit_window="weekly", max_value=1000)],
    )

    response = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}"},
        json={"model": "deepseek/deepseek-chat", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "hi"
    assert fake_openrouter.chat_payloads[0]["model"] == "deepseek/deepseek-chat"
    assert await _reservation_statuses() == ["finalized"]
    async with SessionLocal() as session:
        logs = list((await session.execute(select(RequestLog))).scalars().all())
    sidecar_logs = [log for log in logs if log.source == "openrouter_sidecar"]
    assert len(sidecar_logs) == 1
    assert sidecar_logs[0].model == "deepseek/deepseek-chat"


@pytest.mark.asyncio
async def test_openrouter_model_list_merges_and_filters(async_client, openrouter_enabled, fake_openrouter):
    await async_client.put(
        "/api/settings",
        json={
            "openrouterSidecarEnabled": True,
            "openrouterSidecarApiKey": "openrouter-key",
            "openrouterSidecarModelPrefixes": ["deepseek/"],
        },
    )
    await _enable_api_key_auth(async_client)
    registry = get_model_registry()
    await registry.update({"plus": [_make_upstream_model("gpt-5.4")]})
    key = await _create_api_key("models-key", allowed_models=["deepseek/deepseek-chat"])

    response = await async_client.get("/v1/models", headers={"Authorization": f"Bearer {key.key}"})

    assert response.status_code == 200
    data = response.json()["data"]
    ids = [item["id"] for item in data]
    assert "deepseek/deepseek-chat" in ids
    assert "gpt-5.4" not in ids

    sidecar_entry = next(item for item in data if item["id"] == "deepseek/deepseek-chat")
    # Clients (e.g. Cursor) read the advertised context window to trigger their
    # own compaction; sidecar models must expose it.
    assert sidecar_entry["context_length"] == 200_000
    assert sidecar_entry["capabilities"]["context_length"] == 200_000


@pytest.mark.asyncio
async def test_gpt_request_does_not_hit_openrouter_sidecar(async_client, openrouter_enabled, fake_openrouter):
    await async_client.put(
        "/api/settings",
        json={
            "openrouterSidecarEnabled": True,
            "openrouterSidecarApiKey": "openrouter-key",
            "openrouterSidecarModelPrefixes": ["deepseek/"],
        },
    )

    response = await async_client.post(
        "/v1/chat/completions",
        json={"model": "gpt-5.4", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code in {502, 503}
    assert fake_openrouter.chat_payloads == []
    assert fake_openrouter.stream_payloads == []


@pytest.mark.asyncio
async def test_openrouter_sidecar_unavailable_returns_503(async_client, openrouter_enabled, fake_openrouter):
    await async_client.put(
        "/api/settings",
        json={
            "openrouterSidecarEnabled": True,
            "openrouterSidecarApiKey": "openrouter-key",
            "openrouterSidecarModelPrefixes": ["deepseek/"],
        },
    )
    fake_openrouter.chat_error = OpenRouterSidecarUnavailableError("upstream down")

    response = await async_client.post(
        "/v1/chat/completions",
        json={"model": "deepseek/deepseek-chat", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "openrouter_sidecar_unavailable"


@pytest.mark.asyncio
async def test_openrouter_sidecar_cursor_stream_applies_usage_fallback(
    async_client,
    openrouter_enabled,
    fake_openrouter,
):
    await async_client.put(
        "/api/settings",
        json={
            "openrouterSidecarEnabled": True,
            "openrouterSidecarApiKey": "openrouter-key",
            "openrouterSidecarModelPrefixes": ["deepseek/"],
        },
    )
    fake_openrouter.stream_include_usage = False

    async with async_client.stream(
        "POST",
        "/v1/chat/completions",
        headers={"User-Agent": "Cursor/1.0"},
        json={
            "model": "deepseek/deepseek-chat",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
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
async def test_openrouter_sidecar_cursor_stream_context_limit_returns_synthetic_usage(
    async_client,
    openrouter_enabled,
    fake_openrouter,
):
    await async_client.put(
        "/api/settings",
        json={
            "openrouterSidecarEnabled": True,
            "openrouterSidecarApiKey": "openrouter-key",
            "openrouterSidecarModelPrefixes": ["deepseek/"],
        },
    )
    fake_openrouter.stream_context_error = True

    async with async_client.stream(
        "POST",
        "/v1/chat/completions",
        headers={"User-Agent": "Cursor/1.0"},
        json={
            "model": "deepseek/deepseek-chat",
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
async def test_openrouter_sidecar_non_cursor_stream_does_not_apply_usage_fallback(
    async_client,
    openrouter_enabled,
    fake_openrouter,
):
    await async_client.put(
        "/api/settings",
        json={
            "openrouterSidecarEnabled": True,
            "openrouterSidecarApiKey": "openrouter-key",
            "openrouterSidecarModelPrefixes": ["deepseek/"],
        },
    )
    fake_openrouter.stream_include_usage = False

    async with async_client.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": "deepseek/deepseek-chat",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    ) as response:
        body = await response.aread()

    assert response.status_code == 200
    assert _usage_chunks(_chat_sse_payloads(body)) == []
    assert body.rstrip().endswith(b"data: [DONE]")
