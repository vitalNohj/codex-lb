from __future__ import annotations

from dataclasses import dataclass

import pytest
from sqlalchemy import select

from app.core.clients.claude_sidecar import ClaudeSidecarConfig, ClaudeSidecarError
from app.modules.proxy.cursor_chat_compat import CURSOR_CONTEXT_LIMIT_SYNTHETIC_USAGE_TOKENS
from app.core.config.settings import get_settings
from app.core.openai.model_registry import ReasoningLevel, UpstreamModel, get_model_registry
from app.db.models import ApiKeyUsageReservation, RequestLog
from app.db.session import SessionLocal
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeyCreateData, ApiKeysService, LimitRuleInput

pytestmark = pytest.mark.integration


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
        self.stream_error: Exception | None = None
        self.stream_include_usage = True

    async def list_models_cached(self):
        return self.models

    async def chat_completion(self, payload):
        self.chat_payloads.append(dict(payload))
        if self.chat_error is not None:
            raise self.chat_error
        return {
            "id": "chatcmpl-sidecar",
            "object": "chat.completion",
            "model": payload["model"],
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

    def stream_chat_completion(self, payload):
        self.stream_payloads.append(dict(payload))
        return _FakeStreamContext(self.stream_error, include_usage=self.stream_include_usage)


class _FakeStreamContext:
    def __init__(self, error: Exception | None, *, include_usage: bool = True) -> None:
        self.error = error
        self.include_usage = include_usage

    async def __aenter__(self):
        if self.error is not None:
            raise self.error

        async def chunks():
            yield b'data: {"id":"chunk-1","object":"chat.completion.chunk","choices":[{"delta":{"content":"hi"}}]}\n\n'
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
        model_prefixes=("claude", "cp-"),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
    )
    client = _FakeSidecarClient(config)

    async def load_config():
        return config

    monkeypatch.setattr("app.modules.proxy.api.load_sidecar_config", load_config)
    monkeypatch.setattr("app.modules.proxy.api.ClaudeSidecarClient", lambda _config: client)
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
    await _enable_api_key_auth(async_client)
    registry = get_model_registry()
    await registry.update({"plus": [_make_upstream_model("gpt-5.4")]})
    key = await _create_api_key("models-key", allowed_models=["claude-sonnet-4-5-20250929"])

    response = await async_client.get("/v1/models", headers={"Authorization": f"Bearer {key.key}"})

    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["data"]]
    assert "claude-sonnet-4-5-20250929" in ids
    assert "gpt-5.4" not in ids


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
    assert b'"prompt_tokens":' in body
    assert b'"completion_tokens":' in body
