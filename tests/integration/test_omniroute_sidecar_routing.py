from __future__ import annotations

from dataclasses import dataclass

import pytest
from sqlalchemy import select

from app.core.clients.omniroute_sidecar import OmniRouteSidecarConfig, OmniRouteSidecarUnavailableError
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
    owned_by: str | None = "omniroute"


class _FakeOmniRouteClient:
    def __init__(self, config: OmniRouteSidecarConfig) -> None:
        self.config = config
        self.chat_payloads: list[dict] = []
        self.stream_payloads: list[dict] = []
        self.models = [_FakeModel("omniroute/test-chat")]
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
            "id": "chatcmpl-omniroute",
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
async def omniroute_enabled(monkeypatch):
    monkeypatch.setenv("CODEX_LB_OMNIROUTE_SIDECAR_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def fake_omniroute(monkeypatch):
    config = OmniRouteSidecarConfig(
        enabled=True,
        base_url="http://127.0.0.1:20128/v1",
        api_key="omniroute-key",
        selected_models=("omniroute/test-chat",),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
    )
    client = _FakeOmniRouteClient(config)

    async def load_config():
        return config

    monkeypatch.setattr("app.modules.proxy.api.load_omniroute_sidecar_config", load_config)
    monkeypatch.setattr("app.modules.proxy.api.OmniRouteSidecarClient", lambda _config: client)
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
async def test_omniroute_non_stream_routes_to_sidecar_and_finalizes_reservation(
    async_client,
    omniroute_enabled,
    fake_omniroute,
):
    await async_client.put(
        "/api/settings",
        json={
            "omnirouteSidecarEnabled": True,
            "omnirouteSidecarApiKey": "omniroute-key",
            "omnirouteSidecarSelectedModels": ["omniroute/test-chat"],
        },
    )
    await _enable_api_key_auth(async_client)
    key = await _create_api_key(
        "omniroute-key",
        limits=[LimitRuleInput(limit_type="total_tokens", limit_window="weekly", max_value=1000)],
    )

    response = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}"},
        json={"model": "omniroute/test-chat", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "hi"
    assert fake_omniroute.chat_payloads[0]["model"] == "omniroute/test-chat"
    assert await _reservation_statuses() == ["finalized"]
    async with SessionLocal() as session:
        logs = list((await session.execute(select(RequestLog))).scalars().all())
    sidecar_logs = [log for log in logs if log.source == "omniroute_sidecar"]
    assert len(sidecar_logs) == 1
    assert sidecar_logs[0].model == "omniroute/test-chat"


@pytest.mark.asyncio
async def test_omniroute_streaming_relays_sse_and_finalizes_reservation(async_client, omniroute_enabled, fake_omniroute):
    await async_client.put(
        "/api/settings",
        json={
            "omnirouteSidecarEnabled": True,
            "omnirouteSidecarApiKey": "omniroute-key",
            "omnirouteSidecarSelectedModels": ["omniroute/test-chat"],
        },
    )
    await _enable_api_key_auth(async_client)
    key = await _create_api_key(
        "omniroute-stream-key",
        limits=[LimitRuleInput(limit_type="total_tokens", limit_window="weekly", max_value=1000)],
    )

    response = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}"},
        json={"model": "omniroute/test-chat", "stream": True, "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert "data: [DONE]" in response.text
    assert fake_omniroute.stream_payloads[0]["stream_options"] == {"include_usage": True}
    assert await _reservation_statuses() == ["finalized"]


@pytest.mark.asyncio
async def test_omniroute_model_list_merges_selected_models_and_filters(async_client, omniroute_enabled, fake_omniroute):
    await async_client.put(
        "/api/settings",
        json={
            "omnirouteSidecarEnabled": True,
            "omnirouteSidecarApiKey": "omniroute-key",
            "omnirouteSidecarSelectedModels": ["omniroute/test-chat", "omniroute/not-discovered"],
        },
    )
    await _enable_api_key_auth(async_client)
    registry = get_model_registry()
    await registry.update({"plus": [_make_upstream_model("gpt-5.4")]})
    key = await _create_api_key("models-key", allowed_models=["omniroute/test-chat"])

    response = await async_client.get("/v1/models", headers={"Authorization": f"Bearer {key.key}"})

    assert response.status_code == 200
    data = response.json()["data"]
    ids = [item["id"] for item in data]
    assert "omniroute/test-chat" in ids
    assert "omniroute/not-discovered" not in ids
    assert "gpt-5.4" not in ids

    sidecar_entry = next(item for item in data if item["id"] == "omniroute/test-chat")
    # Clients (e.g. Cursor) read the advertised context window to trigger their
    # own compaction; sidecar models must expose it.
    assert sidecar_entry["context_length"] == 200_000
    assert sidecar_entry["capabilities"]["context_length"] == 200_000


@pytest.mark.asyncio
async def test_unselected_model_does_not_hit_omniroute_sidecar(async_client, omniroute_enabled, fake_omniroute):
    await async_client.put(
        "/api/settings",
        json={
            "omnirouteSidecarEnabled": True,
            "omnirouteSidecarApiKey": "omniroute-key",
            "omnirouteSidecarSelectedModels": ["omniroute/test-chat"],
        },
    )

    response = await async_client.post(
        "/v1/chat/completions",
        json={"model": "omniroute/test-chat-plus", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code in {502, 503}
    assert fake_omniroute.chat_payloads == []
    assert fake_omniroute.stream_payloads == []


@pytest.mark.asyncio
async def test_omniroute_sidecar_unavailable_returns_503(async_client, omniroute_enabled, fake_omniroute):
    await async_client.put(
        "/api/settings",
        json={
            "omnirouteSidecarEnabled": True,
            "omnirouteSidecarApiKey": "omniroute-key",
            "omnirouteSidecarSelectedModels": ["omniroute/test-chat"],
        },
    )
    fake_omniroute.chat_error = OmniRouteSidecarUnavailableError("upstream down")

    response = await async_client.post(
        "/v1/chat/completions",
        json={"model": "omniroute/test-chat", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "omniroute_sidecar_unavailable"
