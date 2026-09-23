from __future__ import annotations

import json
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import Request
from starlette.responses import StreamingResponse

from app.core.clients.claude_sidecar import SidecarPrefix
from app.core.clients.nvidia_sidecar import NvidiaSidecarClient, NvidiaSidecarConfig, NvidiaSidecarError
from app.core.clients.openai_compat_sidecar import (
    OpenAICompatSidecarClient,
    OpenAICompatSidecarConfig,
    OpenAICompatSidecarError,
    OpenAICompatSidecarUnavailableError,
)
from app.core.clients.openrouter_sidecar import (
    OpenRouterSidecarClient,
    OpenRouterSidecarConfig,
    OpenRouterSidecarError,
)
from app.core.openai.chat_requests import ChatCompletionsRequest
from app.core.types import JsonValue
from app.modules.proxy.nvidia_sidecar_dispatch import proxy_chat_to_nvidia
from app.modules.proxy.openai_compat_dispatch import proxy_chat_to_openai_compat
from app.modules.proxy.openrouter_sidecar_dispatch import proxy_chat_to_openrouter

pytestmark = pytest.mark.unit


def _prefixes(prefix: str) -> tuple[SidecarPrefix, ...]:
    return (SidecarPrefix(prefix=prefix, strip=True),)


def _openrouter_config() -> OpenRouterSidecarConfig:
    return OpenRouterSidecarConfig(
        enabled=True,
        base_url="https://openrouter.ai/api/v1",
        api_key="key",
        prefixes=_prefixes("openrouter/"),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
    )


def _nvidia_config() -> NvidiaSidecarConfig:
    return NvidiaSidecarConfig(
        enabled=True,
        base_url="https://integrate.api.nvidia.com/v1",
        api_key="key",
        prefixes=_prefixes("nvidia/"),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
    )


def _compat_config() -> OpenAICompatSidecarConfig:
    return OpenAICompatSidecarConfig(
        endpoint_id="groq",
        name="Groq",
        enabled=True,
        base_url="https://api.groq.com/openai/v1",
        api_key="key",
        prefixes=_prefixes("groq/"),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
    )


class _ScriptedChatClient:
    def __init__(self, results: list[JsonValue | Exception], config: object) -> None:
        self._results = list(results)
        self.calls = 0
        self.config = config

    async def chat_completion(self, payload: object) -> JsonValue:
        del payload
        self.calls += 1
        item = self._results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class _ScriptedStreamClient:
    def __init__(self, attempts: list[Exception | list[bytes | Exception]], config: object) -> None:
        self._attempts = list(attempts)
        self.calls = 0
        self.config = config

    def stream_chat_completion(self, payload: object) -> "_ScriptedStream":
        del payload
        self.calls += 1
        return _ScriptedStream(self._attempts.pop(0))


class _ScriptedStream:
    def __init__(self, attempt: Exception | list[bytes | Exception]) -> None:
        self._attempt = attempt

    async def __aenter__(self) -> AsyncIterator[bytes]:
        if isinstance(self._attempt, Exception):
            raise self._attempt

        async def chunks() -> AsyncIterator[bytes]:
            for chunk in self._attempt:
                if isinstance(chunk, Exception):
                    raise chunk
                yield chunk

        return chunks()

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


def _silence(monkeypatch: pytest.MonkeyPatch, module: str) -> list[dict[str, object]]:
    logged: list[dict[str, object]] = []

    class _SessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

    class _Repository:
        def __init__(self, session: object) -> None:
            del session

        async def add_log(self, **kwargs: object) -> None:
            logged.append(kwargs)

    class _Cost:
        cost_usd = None
        cost_source = None
        price_status = None

    class _Settlement:
        usage = None
        cost = _Cost()

    async def _settlement(**_kwargs: object) -> _Settlement:
        return _Settlement()

    async def _cost(*_args: object, **_kwargs: object) -> _Cost:
        return _Cost()

    monkeypatch.setattr(f"{module}.get_background_session", _SessionContext)
    monkeypatch.setattr(f"{module}.RequestLogsRepository", _Repository)
    monkeypatch.setattr(f"{module}.get_request_id", lambda: "req-retry")
    monkeypatch.setattr(f"{module}.external_response_settlement", _settlement)
    monkeypatch.setattr(f"{module}.external_request_cost", _cost)
    return logged


def _chat_request(*, stream: bool) -> ChatCompletionsRequest:
    return ChatCompletionsRequest.model_validate(
        {"model": "vendor/model", "messages": [{"role": "user", "content": "hi"}], "stream": stream}
    )


def _completion() -> dict[str, JsonValue]:
    return {
        "id": "chatcmpl-retry",
        "choices": [{"message": {"role": "assistant", "content": "ok"}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
    }


async def _read_stream(response: StreamingResponse) -> bytes:
    chunks: list[bytes] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk if isinstance(chunk, bytes) else str(chunk).encode())
    return b"".join(chunks)


async def _proxy_openrouter(client: object, *, stream: bool):
    return await proxy_chat_to_openrouter(
        cast(Request, SimpleNamespace()),
        _chat_request(stream=stream),
        effective_model="vendor/model",
        api_key=None,
        reservation=None,
        rate_limit_headers={},
        sse_keepalive_interval_seconds=0,
        client=cast(OpenRouterSidecarClient, client),
    )


async def _proxy_nvidia(client: object, *, stream: bool):
    return await proxy_chat_to_nvidia(
        cast(Request, SimpleNamespace()),
        _chat_request(stream=stream),
        effective_model="vendor/model",
        api_key=None,
        reservation=None,
        rate_limit_headers={},
        sse_keepalive_interval_seconds=0,
        client=cast(NvidiaSidecarClient, client),
    )


async def _proxy_compat(client: object, *, stream: bool):
    return await proxy_chat_to_openai_compat(
        cast(Request, SimpleNamespace()),
        _chat_request(stream=stream),
        effective_model="vendor/model",
        api_key=None,
        reservation=None,
        rate_limit_headers={},
        sse_keepalive_interval_seconds=0,
        client=cast(OpenAICompatSidecarClient, client),
    )


@pytest.mark.asyncio
async def test_openrouter_retries_524_then_returns_the_second_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    logged = _silence(monkeypatch, "app.modules.proxy.openrouter_sidecar_dispatch")
    client = _ScriptedChatClient(
        [OpenRouterSidecarError(524, "OpenRouter sidecar returned HTTP 524"), _completion()],
        _openrouter_config(),
    )

    response = await _proxy_openrouter(client, stream=False)

    assert response.status_code == 200
    assert json.loads(bytes(response.body))["id"] == "chatcmpl-retry"
    assert client.calls == 2
    assert len(logged) == 1
    assert logged[0]["status"] == "success"


@pytest.mark.asyncio
async def test_openrouter_returns_the_second_524_once(monkeypatch: pytest.MonkeyPatch) -> None:
    logged = _silence(monkeypatch, "app.modules.proxy.openrouter_sidecar_dispatch")
    client = _ScriptedChatClient(
        [
            OpenRouterSidecarError(524, "OpenRouter sidecar returned HTTP 524"),
            OpenRouterSidecarError(524, "OpenRouter sidecar returned HTTP 524"),
        ],
        _openrouter_config(),
    )

    response = await _proxy_openrouter(client, stream=False)

    assert response.status_code == 524
    assert client.calls == 2
    assert len(logged) == 1
    assert logged[0]["status"] == "error"


@pytest.mark.asyncio
async def test_nvidia_does_not_retry_http_400(monkeypatch: pytest.MonkeyPatch) -> None:
    _silence(monkeypatch, "app.modules.proxy.nvidia_sidecar_dispatch")
    client = _ScriptedChatClient(
        [NvidiaSidecarError(400, "bad request", body={"error": {"message": "bad request"}})],
        _nvidia_config(),
    )

    response = await _proxy_nvidia(client, stream=False)

    assert response.status_code == 400
    assert client.calls == 1


@pytest.mark.asyncio
async def test_openai_compat_retries_503_then_returns_the_second_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    logged = _silence(monkeypatch, "app.modules.proxy.openai_compat_dispatch")
    client = _ScriptedChatClient(
        [OpenAICompatSidecarUnavailableError("connection reset"), _completion()],
        _compat_config(),
    )

    response = await _proxy_compat(client, stream=False)

    assert response.status_code == 200
    assert client.calls == 2
    assert len(logged) == 1
    assert logged[0]["status"] == "success"


@pytest.mark.asyncio
async def test_openrouter_stream_retries_502_before_any_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    logged = _silence(monkeypatch, "app.modules.proxy.openrouter_sidecar_dispatch")
    client = _ScriptedStreamClient(
        [
            OpenRouterSidecarError(502, "bad gateway"),
            [b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n', b"data: [DONE]\n\n"],
        ],
        _openrouter_config(),
    )

    response = await _proxy_openrouter(client, stream=True)
    body = await _read_stream(response)

    assert client.calls == 2
    assert b'"content":"ok"' in body
    assert b"bad gateway" not in body
    assert logged[0]["status"] == "success"


@pytest.mark.asyncio
async def test_openrouter_stream_does_not_retry_after_a_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    _silence(monkeypatch, "app.modules.proxy.openrouter_sidecar_dispatch")
    client = _ScriptedStreamClient(
        [
            [
                b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n',
                OpenRouterSidecarError(524, "OpenRouter sidecar returned HTTP 524"),
            ]
        ],
        _openrouter_config(),
    )

    response = await _proxy_openrouter(client, stream=True)
    body = await _read_stream(response)

    assert client.calls == 1
    assert b'"content":"hi"' in body
    assert b"HTTP 524" in body


@pytest.mark.asyncio
async def test_nvidia_stream_retries_502_before_any_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    _silence(monkeypatch, "app.modules.proxy.nvidia_sidecar_dispatch")
    client = _ScriptedStreamClient(
        [
            NvidiaSidecarError(502, "bad gateway"),
            [b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n', b"data: [DONE]\n\n"],
        ],
        _nvidia_config(),
    )

    response = await _proxy_nvidia(client, stream=True)
    body = await _read_stream(response)

    assert client.calls == 2
    assert b'"content":"ok"' in body
    assert b"bad gateway" not in body


@pytest.mark.asyncio
async def test_openai_compat_does_not_retry_http_400(monkeypatch: pytest.MonkeyPatch) -> None:
    _silence(monkeypatch, "app.modules.proxy.openai_compat_dispatch")
    client = _ScriptedChatClient(
        [OpenAICompatSidecarError(400, "bad request", body={"error": {"message": "bad request"}})],
        _compat_config(),
    )

    response = await _proxy_compat(client, stream=False)

    assert response.status_code == 400
    assert client.calls == 1
