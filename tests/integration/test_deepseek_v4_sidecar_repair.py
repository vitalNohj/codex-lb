from __future__ import annotations

import json

import pytest

from app.core.clients.omniroute_sidecar import OmniRouteSidecarConfig
from app.core.config.settings import get_settings
from app.modules.proxy.deepseek_v4_compat import get_reasoning_cache

pytestmark = pytest.mark.integration

DEEPSEEK_MODEL = "oc/deepseek-v4-flash-free"


class _FakeStreamContext:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def __aenter__(self):
        async def gen():
            for chunk in self._chunks:
                yield chunk

        return gen()

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class _FakeOmniRouteClient:
    def __init__(self, config: OmniRouteSidecarConfig) -> None:
        self.config = config
        self.chat_payloads: list[dict] = []
        self.stream_payloads: list[dict] = []
        self.chat_response: dict | None = None
        self.stream_chunks: list[bytes] = []

    async def list_models_cached(self):
        return []

    async def chat_completion(self, payload):
        self.chat_payloads.append(json.loads(json.dumps(payload)))
        assert self.chat_response is not None
        return self.chat_response

    def stream_chat_completion(self, payload):
        self.stream_payloads.append(json.loads(json.dumps(payload)))
        return _FakeStreamContext(self.stream_chunks)


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
        full_models=(DEEPSEEK_MODEL,),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
    )
    client = _FakeOmniRouteClient(config)

    async def load_config():
        return config

    monkeypatch.setattr("app.modules.proxy.api.load_omniroute_sidecar_config", load_config)
    monkeypatch.setattr("app.modules.proxy.api.OmniRouteSidecarClient", lambda _config: client)
    get_reasoning_cache().clear()
    return client


async def _configure(async_client) -> None:
    await async_client.put(
        "/api/settings",
        json={
            "omnirouteSidecarEnabled": True,
            "omnirouteSidecarApiKey": "omniroute-key",
            "omnirouteSidecarSelectedModels": [DEEPSEEK_MODEL],
        },
    )


_ASSISTANT_TOOL_CALL = {
    "role": "assistant",
    "content": None,
    "tool_calls": [
        {"id": "call_1", "type": "function", "function": {"name": "get_weather", "arguments": '{"city":"Paris"}'}}
    ],
}

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "weather",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
                "additionalProperties": False,
            },
        },
    }
]


@pytest.mark.asyncio
async def test_non_streaming_repair_reinjects_reasoning_on_next_turn(async_client, omniroute_enabled, fake_omniroute):
    await _configure(async_client)
    fake_omniroute.chat_response = {
        "id": "c1",
        "object": "chat.completion",
        "model": DEEPSEEK_MODEL,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "reasoning_content": "thinking about Paris",
                    "tool_calls": _ASSISTANT_TOOL_CALL["tool_calls"],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }

    # Turn 1: user asks; upstream returns assistant tool_calls + reasoning_content
    first = await async_client.post(
        "/v1/chat/completions",
        json={
            "model": DEEPSEEK_MODEL,
            "messages": [{"role": "user", "content": "weather in Paris?"}],
            "tools": _TOOLS,
        },
    )
    assert first.status_code == 200
    # The forwarded payload for turn 1 has no reasoning to inject
    assert "reasoning_content" not in json.dumps(fake_omniroute.chat_payloads[0]["messages"])

    # Turn 2: client echoes assistant tool_calls (without reasoning) + tool result
    second = await async_client.post(
        "/v1/chat/completions",
        json={
            "model": DEEPSEEK_MODEL,
            "messages": [
                {"role": "user", "content": "weather in Paris?"},
                dict(_ASSISTANT_TOOL_CALL),
                {"role": "tool", "tool_call_id": "call_1", "content": '{"temp_c":18}'},
            ],
            "tools": _TOOLS,
        },
    )
    assert second.status_code == 200
    forwarded = fake_omniroute.chat_payloads[1]["messages"]
    assert forwarded[1]["reasoning_content"] == "thinking about Paris"


@pytest.mark.asyncio
async def test_streaming_repair_reinjects_accumulated_reasoning(async_client, omniroute_enabled, fake_omniroute):
    await _configure(async_client)
    fake_omniroute.stream_chunks = [
        b'data: {"object":"chat.completion.chunk","choices":[{"index":0,"delta":{"reasoning_content":"step 1 "}}]}\n\n',
        b'data: {"object":"chat.completion.chunk","choices":[{"index":0,"delta":{"reasoning_content":"step 2"}}]}\n\n',
        (
            b'data: {"object":"chat.completion.chunk","choices":[{"index":0,"delta":{"tool_calls":'
            b'[{"index":0,"id":"call_1","type":"function","function":'
            b'{"name":"get_weather","arguments":"{\\"city\\":\\"Paris\\"}"}}]}}]}\n\n'
        ),
        b'data: {"object":"chat.completion.chunk","choices":[{"index":0,"delta":{},"finish_reason":"tool_calls"}]}\n\n',
        b'data: {"object":"chat.completion.chunk","choices":[],"usage":{"prompt_tokens":10,"completion_tokens":5}}\n\n',
        b"data: [DONE]\n\n",
    ]

    first = await async_client.post(
        "/v1/chat/completions",
        json={
            "model": DEEPSEEK_MODEL,
            "stream": True,
            "messages": [{"role": "user", "content": "weather in Paris?"}],
            "tools": _TOOLS,
        },
    )
    assert first.status_code == 200
    assert "data: [DONE]" in first.text

    # Now non-streaming continuation gets the accumulated reasoning re-injected
    fake_omniroute.chat_response = {
        "id": "c2",
        "object": "chat.completion",
        "model": DEEPSEEK_MODEL,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "18C"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 2, "total_tokens": 13},
    }
    second = await async_client.post(
        "/v1/chat/completions",
        json={
            "model": DEEPSEEK_MODEL,
            "messages": [
                {"role": "user", "content": "weather in Paris?"},
                dict(_ASSISTANT_TOOL_CALL),
                {"role": "tool", "tool_call_id": "call_1", "content": '{"temp_c":18}'},
            ],
            "tools": _TOOLS,
        },
    )
    assert second.status_code == 200
    forwarded = fake_omniroute.chat_payloads[0]["messages"]
    assert forwarded[1]["reasoning_content"] == "step 1 step 2"


@pytest.mark.asyncio
async def test_missing_cache_forwards_unchanged(async_client, omniroute_enabled, fake_omniroute):
    await _configure(async_client)
    fake_omniroute.chat_response = {
        "id": "c1",
        "object": "chat.completion",
        "model": DEEPSEEK_MODEL,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    response = await async_client.post(
        "/v1/chat/completions",
        json={
            "model": DEEPSEEK_MODEL,
            "messages": [
                {"role": "user", "content": "weather in Paris?"},
                dict(_ASSISTANT_TOOL_CALL),
                {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
            ],
            "tools": _TOOLS,
        },
    )
    assert response.status_code == 200
    forwarded = fake_omniroute.chat_payloads[0]["messages"]
    assert "reasoning_content" not in forwarded[1]


@pytest.mark.asyncio
async def test_cursor_usage_fallback_preserved_for_deepseek(async_client, omniroute_enabled, fake_omniroute):
    await _configure(async_client)
    # No usage in response -> cursor fallback should synthesize it
    fake_omniroute.chat_response = {
        "id": "c1",
        "object": "chat.completion",
        "model": DEEPSEEK_MODEL,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "hello there"}, "finish_reason": "stop"}],
    }
    response = await async_client.post(
        "/v1/chat/completions",
        headers={"user-agent": "Cursor/1.0"},
        json={"model": DEEPSEEK_MODEL, "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 200
    usage = response.json()["usage"]
    assert usage["prompt_tokens"] > 0
    assert usage["completion_tokens"] > 0


@pytest.mark.asyncio
async def test_non_deepseek_model_is_not_intercepted(async_client, omniroute_enabled, monkeypatch):
    # Configure a non-DeepSeek selected model and confirm no reasoning capture occurs.
    config = OmniRouteSidecarConfig(
        enabled=True,
        base_url="http://127.0.0.1:20128/v1",
        api_key="omniroute-key",
        full_models=("omniroute/plain-chat",),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
    )
    client = _FakeOmniRouteClient(config)

    async def load_config():
        return config

    monkeypatch.setattr("app.modules.proxy.api.load_omniroute_sidecar_config", load_config)
    monkeypatch.setattr("app.modules.proxy.api.OmniRouteSidecarClient", lambda _config: client)
    get_reasoning_cache().clear()

    await async_client.put(
        "/api/settings",
        json={
            "omnirouteSidecarEnabled": True,
            "omnirouteSidecarApiKey": "omniroute-key",
            "omnirouteSidecarSelectedModels": ["omniroute/plain-chat"],
        },
    )
    client.chat_response = {
        "id": "c1",
        "object": "chat.completion",
        "model": "omniroute/plain-chat",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "reasoning_content": "should-not-be-cached",
                    "tool_calls": _ASSISTANT_TOOL_CALL["tool_calls"],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    first = await async_client.post(
        "/v1/chat/completions",
        json={
            "model": "omniroute/plain-chat",
            "messages": [{"role": "user", "content": "weather in Paris?"}],
            "tools": _TOOLS,
        },
    )
    assert first.status_code == 200

    # Next turn for the same conversation must NOT get reasoning injected
    # (non-DeepSeek traffic is never intercepted).
    second = await async_client.post(
        "/v1/chat/completions",
        json={
            "model": "omniroute/plain-chat",
            "messages": [
                {"role": "user", "content": "weather in Paris?"},
                dict(_ASSISTANT_TOOL_CALL),
                {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
            ],
            "tools": _TOOLS,
        },
    )
    assert second.status_code == 200
    forwarded = client.chat_payloads[1]["messages"]
    assert "reasoning_content" not in forwarded[1]
