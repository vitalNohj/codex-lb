from __future__ import annotations

import pytest

from app.core.clients.claude_sidecar import SidecarPrefix
from app.core.clients.ollama_sidecar import OllamaSidecarConfig
from app.core.openai.chat_requests import ChatCompletionsRequest
from app.modules.proxy.claude_sidecar_dispatch import SidecarUsage
from app.modules.proxy.ollama_sidecar_dispatch import (
    OLLAMA_SIDECAR_SOURCE,
    _log_ollama_request,
    _ollama_stream_iterator,
    build_ollama_chat_payload,
    ollama_response_to_openai_chat_completion,
    ollama_routing_entry,
)


def _config() -> OllamaSidecarConfig:
    return OllamaSidecarConfig(
        enabled=True,
        base_url="https://ollama.com",
        api_key="key",
        prefixes=(SidecarPrefix(prefix="ollama-", strip=True),),
        full_models=("gpt-oss:120b-cloud",),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
    )


def test_ollama_routing_entry_uses_configured_prefixes_and_full_models() -> None:
    entry = ollama_routing_entry(_config())

    assert entry.provider == "ollama"
    assert entry.prefixes == (SidecarPrefix(prefix="ollama-", strip=True),)
    assert entry.full_models == ("gpt-oss:120b-cloud",)


def test_build_ollama_chat_payload_converts_chat_request_to_sdk_shape() -> None:
    request = ChatCompletionsRequest.model_validate(
        {
            "model": "ollama-gpt-oss:120b-cloud",
            "messages": [
                {"role": "system", "content": "You are brief."},
                {"role": "user", "content": [{"type": "text", "text": "hi"}]},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "lookup", "arguments": "{}"},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call_1", "name": "lookup", "content": "ok"},
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "lookup",
                        "description": "Look up data",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
            "top_p": 0.8,
            "max_tokens": 64,
            "stop": ["\n\n"],
            "stream": True,
        }
    )

    payload = build_ollama_chat_payload(request, "gpt-oss:120b-cloud")

    assert payload.body["model"] == "gpt-oss:120b-cloud"
    assert payload.body["stream"] is True
    assert payload.body["messages"] == [
        {"role": "system", "content": "You are brief."},
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "lookup", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "content": "ok", "tool_name": "lookup", "tool_call_id": "call_1"},
    ]
    assert payload.body["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "Look up data",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    assert payload.body["format"] == "json"
    assert payload.body["options"] == {
        "temperature": 0.2,
        "top_p": 0.8,
        "num_predict": 64,
        "stop": ["\n\n"],
    }


def test_build_ollama_chat_payload_injects_default_effort_as_think() -> None:
    request = ChatCompletionsRequest.model_validate(
        {"model": "gpt-oss:120b-cloud", "messages": [{"role": "user", "content": "hi"}]}
    )

    payload = build_ollama_chat_payload(request, "gpt-oss:120b-cloud", "low")

    assert payload.body["think"] == "low"
    assert "reasoning_effort" not in payload.body


def test_build_ollama_chat_payload_default_effort_does_not_override_client_thinking() -> None:
    request = ChatCompletionsRequest.model_validate(
        {
            "model": "gpt-oss:120b-cloud",
            "messages": [{"role": "user", "content": "hi"}],
            "reasoning": {"effort": "high"},
        }
    )

    payload = build_ollama_chat_payload(request, "gpt-oss:120b-cloud", "low")

    assert payload.body["think"] == "high"


def test_build_ollama_chat_payload_without_default_effort_omits_think() -> None:
    request = ChatCompletionsRequest.model_validate(
        {"model": "gpt-oss:120b-cloud", "messages": [{"role": "user", "content": "hi"}]}
    )

    payload = build_ollama_chat_payload(request, "gpt-oss:120b-cloud")

    assert "think" not in payload.body


def test_ollama_non_stream_response_maps_content_usage_and_finish_reason() -> None:
    response = ollama_response_to_openai_chat_completion(
        {
            "model": "gpt-oss:120b-cloud",
            "message": {"role": "assistant", "content": "hello"},
            "done_reason": "stop",
            "prompt_eval_count": 11,
            "eval_count": 7,
        }
    )

    assert response["object"] == "chat.completion"
    assert response["model"] == "gpt-oss:120b-cloud"
    assert response["choices"] == [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "hello"},
            "finish_reason": "stop",
        }
    ]
    assert response["usage"] == {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}


def test_ollama_non_stream_response_maps_tool_calls() -> None:
    response = ollama_response_to_openai_chat_completion(
        {
            "model": "gpt-oss:120b-cloud",
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": "lookup", "arguments": {"query": "hi"}}}],
            },
            "done_reason": "stop",
        }
    )

    choice = response["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["tool_calls"] == [
        {
            "id": "call_0",
            "type": "function",
            "function": {"name": "lookup", "arguments": '{"query":"hi"}'},
        }
    ]


@pytest.mark.asyncio
async def test_ollama_stream_iterator_emits_openai_chunks_and_usage() -> None:
    class _Client:
        async def stream_chat_completion(self, payload):
            yield {"model": payload["model"], "message": {"content": "hel"}}
            yield {
                "model": payload["model"],
                "message": {"content": "lo"},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 3,
                "eval_count": 2,
            }

    chunks = [
        chunk.decode("utf-8")
        async for chunk in _ollama_stream_iterator(
            {"model": "gpt-oss:120b-cloud", "stream_options": {"include_usage": True}},
            api_key=None,
            reservation=None,
            model="gpt-oss:120b-cloud",
            started_at=0.0,
            client=_Client(),
        )
    ]

    assert '"delta":{"role":"assistant"}' in chunks[0]
    assert '"content":"hel"' in chunks[1]
    assert '"content":"lo"' in chunks[2]
    assert '"finish_reason":"stop"' in chunks[3]
    assert '"usage":{"prompt_tokens":3,"completion_tokens":2,"total_tokens":5}' in chunks[4]
    assert chunks[-1] == "data: [DONE]\n\n"


@pytest.mark.asyncio
async def test_log_ollama_request_records_source_tokens_and_null_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    class _SessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

    class _Repository:
        def __init__(self, session: object) -> None:
            self.session = session

        async def add_log(self, **kwargs: object) -> None:
            calls.append(kwargs)

    monkeypatch.setattr("app.modules.proxy.ollama_sidecar_dispatch.get_background_session", _SessionContext)
    monkeypatch.setattr("app.modules.proxy.ollama_sidecar_dispatch.RequestLogsRepository", _Repository)
    monkeypatch.setattr("app.modules.proxy.ollama_sidecar_dispatch.get_request_id", lambda: "req-ollama")

    await _log_ollama_request(
        api_key=None,
        model="gpt-oss:120b-cloud",
        started_at=0,
        status="success",
        usage=SidecarUsage(input_tokens=10, output_tokens=5, cost_usd=None),
    )

    assert calls == [
        {
            "account_id": None,
            "request_id": "req-ollama",
            "model": "gpt-oss:120b-cloud",
            "input_tokens": 10,
            "output_tokens": 5,
            "cached_input_tokens": 0,
            "latency_ms": calls[0]["latency_ms"],
            "status": "success",
            "error_code": None,
            "error_message": None,
            "transport": "http",
            "api_key_id": None,
            "source": OLLAMA_SIDECAR_SOURCE,
            "failure_phase": None,
            "cost_usd": None,
            "reference_cost_usd": None,
        }
    ]
