from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from app.core.clients.claude_sidecar import SidecarPrefix
from app.core.clients.ollama_sidecar import (
    OllamaSidecarClient,
    OllamaSidecarConfig,
    OllamaSidecarError,
    OllamaSidecarUnavailableError,
)

pytestmark = pytest.mark.unit


def _config(**overrides) -> OllamaSidecarConfig:
    values = {
        "enabled": True,
        "base_url": "https://ollama.com/",
        "api_key": "ollama-key",
        "prefixes": (SidecarPrefix(prefix="ollama-", strip=True),),
        "full_models": ("gpt-oss:120b-cloud",),
        "connect_timeout_seconds": 8.0,
        "request_timeout_seconds": 600.0,
        "models_cache_ttl_seconds": 60.0,
    }
    values.update(overrides)
    return OllamaSidecarConfig(**values)


class _ModelObj:
    def __init__(self, model: str, modified_at: object = None) -> None:
        self.model = model
        self.modified_at = modified_at


class _NameObj:
    def __init__(self, name: str) -> None:
        self.name = name


class _ListResponse:
    def __init__(self, models: list[object]) -> None:
        self.models = models


class _FakeAsyncClient:
    list_calls = 0
    chat_calls: list[dict[str, object]] = []
    list_response: object = _ListResponse([])
    chat_response: object = {}
    list_error: Exception | None = None
    chat_error: Exception | None = None
    init_kwargs: dict[str, object] = {}

    def __init__(self, **kwargs: object) -> None:
        type(self).init_kwargs = kwargs

    async def list(self) -> object:
        type(self).list_calls += 1
        if self.list_error is not None:
            raise self.list_error
        return self.list_response

    async def chat(self, **kwargs: object) -> object:
        type(self).chat_calls.append(kwargs)
        if self.chat_error is not None:
            raise self.chat_error
        return self.chat_response


def _reset_fake() -> None:
    _FakeAsyncClient.list_calls = 0
    _FakeAsyncClient.chat_calls = []
    _FakeAsyncClient.list_response = _ListResponse([])
    _FakeAsyncClient.chat_response = {}
    _FakeAsyncClient.list_error = None
    _FakeAsyncClient.chat_error = None
    _FakeAsyncClient.init_kwargs = {}


@pytest.mark.asyncio
async def test_cloud_model_filtering_keeps_only_cloud_models() -> None:
    _reset_fake()
    _FakeAsyncClient.list_response = _ListResponse(
        [
            {"model": "gpt-oss:120b-cloud", "modified_at": 123},
            {"name": "deepseek-v3.1:671b-cloud"},
            _ModelObj("kimi-k2-thinking"),
            _NameObj("llama3.2"),
            {"model": "GPT-OSS:120B-CLOUD"},
            {"model": "  "},
        ]
    )
    client = OllamaSidecarClient(_config(), async_client_factory=_FakeAsyncClient)

    models = await client.list_models()

    assert _FakeAsyncClient.init_kwargs["host"] == "https://ollama.com"
    assert _FakeAsyncClient.init_kwargs["headers"] == {"Authorization": "Bearer ollama-key"}
    assert [model.id for model in models] == [
        "gpt-oss:120b-cloud",
        "deepseek-v3.1:671b-cloud",
        "kimi-k2-thinking",
    ]
    assert models[0].owned_by == "ollama"
    assert models[0].created == 123


@pytest.mark.asyncio
async def test_list_models_cached_uses_cache_inside_ttl() -> None:
    _reset_fake()
    _FakeAsyncClient.list_response = _ListResponse([{"model": "gpt-oss:20b-cloud"}])
    client = OllamaSidecarClient(_config(), async_client_factory=_FakeAsyncClient)

    first = await client.list_models_cached()
    second = await client.list_models_cached()

    assert [model.id for model in first] == ["gpt-oss:20b-cloud"]
    assert [model.id for model in second] == ["gpt-oss:20b-cloud"]
    assert _FakeAsyncClient.list_calls == 1


@pytest.mark.asyncio
async def test_response_error_becomes_ollama_sidecar_error() -> None:
    import ollama

    _reset_fake()
    _FakeAsyncClient.list_error = ollama.ResponseError("bad key", status_code=401)
    client = OllamaSidecarClient(_config(), async_client_factory=_FakeAsyncClient)

    with pytest.raises(OllamaSidecarError) as exc_info:
        await client.list_models()

    assert exc_info.value.status_code == 401
    assert exc_info.value.message == "bad key"


@pytest.mark.asyncio
async def test_connection_failure_becomes_unavailable() -> None:
    _reset_fake()
    _FakeAsyncClient.list_error = OSError("boom")
    client = OllamaSidecarClient(_config(), async_client_factory=_FakeAsyncClient)

    with pytest.raises(OllamaSidecarUnavailableError):
        await client.list_models()


@pytest.mark.asyncio
async def test_chat_completion_calls_sdk_with_payload_fields() -> None:
    _reset_fake()
    _FakeAsyncClient.chat_response = {"message": {"content": "hi"}, "done": True}
    client = OllamaSidecarClient(_config(), async_client_factory=_FakeAsyncClient)

    response = await client.chat_completion(
        {
            "model": "gpt-oss:120b-cloud",
            "messages": [{"role": "user", "content": "hello"}],
            "format": "json",
            "options": {"temperature": 0.1},
        }
    )

    assert response == {"message": {"content": "hi"}, "done": True}
    assert _FakeAsyncClient.chat_calls == [
        {
            "model": "gpt-oss:120b-cloud",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1},
        }
    ]


@pytest.mark.asyncio
async def test_streaming_yields_normalized_chunks() -> None:
    _reset_fake()

    async def _chunks() -> AsyncIterator[object]:
        yield {"message": {"content": "a"}, "done": False}
        yield {"message": {"content": "b"}, "done": True, "eval_count": 2}

    _FakeAsyncClient.chat_response = _chunks()
    client = OllamaSidecarClient(_config(), async_client_factory=_FakeAsyncClient)

    chunks = [chunk async for chunk in client.stream_chat_completion({"model": "gpt-oss:120b-cloud", "messages": []})]

    assert chunks == [
        {"message": {"content": "a"}, "done": False},
        {"message": {"content": "b"}, "done": True, "eval_count": 2},
    ]
    assert _FakeAsyncClient.chat_calls[0]["stream"] is True
