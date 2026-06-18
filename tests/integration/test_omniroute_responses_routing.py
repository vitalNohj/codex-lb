from __future__ import annotations

from dataclasses import dataclass

import pytest
from sqlalchemy import select

from app.core.clients.omniroute_sidecar import OmniRouteSidecarConfig, OmniRouteSidecarUnavailableError
from app.core.config.settings import get_settings
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
        return _FakeStreamContext(self.stream_error)


class _FakeStreamContext:
    def __init__(self, error: Exception | None) -> None:
        self.error = error

    async def __aenter__(self):
        if self.error is not None:
            raise self.error

        async def chunks():
            yield b'data: {"id":"chunk-1","object":"chat.completion.chunk","choices":[{"delta":{"content":"hi"}}]}\n\n'
            yield (
                b'data: {"id":"chunk-2","object":"chat.completion.chunk","choices":[],'
                b'"usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15}}\n\n'
            )
            yield b"data: [DONE]\n\n"

        return chunks()

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


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
        full_models=("omniroute/test-chat",),
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


async def _create_api_key(name: str, *, limits: list[LimitRuleInput] | None = None):
    async with SessionLocal() as session:
        service = ApiKeysService(ApiKeysRepository(session))
        return await service.create_key(ApiKeyCreateData(name=name, allowed_models=None, limits=limits))


async def _reservation_statuses() -> list[str]:
    async with SessionLocal() as session:
        result = await session.execute(select(ApiKeyUsageReservation.status))
        return list(result.scalars().all())


async def _configure_omniroute(async_client) -> None:
    await async_client.put(
        "/api/settings",
        json={
            "omnirouteSidecarEnabled": True,
            "omnirouteSidecarApiKey": "omniroute-key",
            "omnirouteSidecarSelectedModels": ["omniroute/test-chat"],
        },
    )


def _responses_body(**overrides) -> dict:
    body = {
        "model": "omniroute/test-chat",
        "instructions": "be helpful",
        "input": [{"role": "user", "content": [{"type": "input_text", "text": "hello"}]}],
    }
    body.update(overrides)
    return body


@pytest.mark.asyncio
async def test_v1_responses_non_stream_routes_to_omniroute(async_client, omniroute_enabled, fake_omniroute):
    await _configure_omniroute(async_client)
    await _enable_api_key_auth(async_client)
    key = await _create_api_key(
        "omniroute-responses",
        limits=[LimitRuleInput(limit_type="total_tokens", limit_window="weekly", max_value=1000)],
    )

    response = await async_client.post(
        "/v1/responses",
        headers={"Authorization": f"Bearer {key.key}"},
        json=_responses_body(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "response"
    assert body["output"][0]["content"][0]["text"] == "hi"
    assert fake_omniroute.chat_payloads[0]["model"] == "omniroute/test-chat"
    assert fake_omniroute.chat_payloads[0]["messages"][0] == {"role": "system", "content": "be helpful"}
    assert await _reservation_statuses() == ["finalized"]
    async with SessionLocal() as session:
        logs = list((await session.execute(select(RequestLog))).scalars().all())
    sidecar_logs = [log for log in logs if log.source == "omniroute_sidecar"]
    assert len(sidecar_logs) == 1
    assert sidecar_logs[0].model == "omniroute/test-chat"


@pytest.mark.asyncio
async def test_v1_responses_streaming_emits_responses_events(async_client, omniroute_enabled, fake_omniroute):
    await _configure_omniroute(async_client)
    await _enable_api_key_auth(async_client)
    key = await _create_api_key(
        "omniroute-responses-stream",
        limits=[LimitRuleInput(limit_type="total_tokens", limit_window="weekly", max_value=1000)],
    )

    response = await async_client.post(
        "/v1/responses",
        headers={"Authorization": f"Bearer {key.key}"},
        json=_responses_body(stream=True),
    )

    assert response.status_code == 200
    text = response.text
    assert '"type":"response.created"' in text
    assert '"type":"response.completed"' in text
    assert "data: [DONE]" in text
    assert fake_omniroute.stream_payloads[0]["stream_options"] == {"include_usage": True}
    assert await _reservation_statuses() == ["finalized"]


@pytest.mark.asyncio
async def test_backend_codex_responses_routes_to_omniroute(async_client, omniroute_enabled, fake_omniroute):
    await _configure_omniroute(async_client)

    response = await async_client.post(
        "/backend-api/codex/responses",
        json=_responses_body(),
    )

    assert response.status_code == 200
    assert response.json()["output"][0]["content"][0]["text"] == "hi"
    assert fake_omniroute.chat_payloads[0]["model"] == "omniroute/test-chat"


@pytest.mark.asyncio
async def test_unselected_model_keeps_codex_path(async_client, omniroute_enabled, fake_omniroute):
    await _configure_omniroute(async_client)

    response = await async_client.post(
        "/v1/responses",
        json=_responses_body(model="omniroute/not-selected"),
    )

    assert fake_omniroute.chat_payloads == []
    assert fake_omniroute.stream_payloads == []
    # Without selected-model routing the request enters the Codex upstream path,
    # which has no account available in tests.
    assert response.status_code != 200


@pytest.mark.asyncio
async def test_disabled_sidecar_does_not_dispatch(async_client, monkeypatch):
    # OmniRoute disabled: the unified resolver receives no enabled OmniRoute entry.
    config = OmniRouteSidecarConfig(
        enabled=False,
        base_url="http://127.0.0.1:20128/v1",
        api_key="omniroute-key",
        full_models=("omniroute/test-chat",),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
    )
    client = _FakeOmniRouteClient(config)

    async def load_config():
        return config

    monkeypatch.setattr("app.modules.proxy.api.load_omniroute_sidecar_config", load_config)
    monkeypatch.setattr("app.modules.proxy.api.OmniRouteSidecarClient", lambda _config: client)

    response = await async_client.post("/v1/responses", json=_responses_body())

    assert client.chat_payloads == []
    assert response.status_code != 200


@pytest.mark.asyncio
async def test_omniroute_unavailable_returns_503_and_releases_reservation(
    async_client, omniroute_enabled, fake_omniroute
):
    await _configure_omniroute(async_client)
    await _enable_api_key_auth(async_client)
    key = await _create_api_key(
        "omniroute-responses-unavailable",
        limits=[LimitRuleInput(limit_type="total_tokens", limit_window="weekly", max_value=1000)],
    )
    fake_omniroute.chat_error = OmniRouteSidecarUnavailableError("upstream down")

    response = await async_client.post(
        "/v1/responses",
        headers={"Authorization": f"Bearer {key.key}"},
        json=_responses_body(),
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "omniroute_sidecar_unavailable"
    assert await _reservation_statuses() == ["released"]
