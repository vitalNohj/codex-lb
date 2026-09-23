from __future__ import annotations

import json
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import Request
from starlette.responses import StreamingResponse

from app.core.clients.claude_sidecar import SidecarPrefix
from app.core.clients.orcarouter_sidecar import (
    OrcaRouterSidecarClient,
    OrcaRouterSidecarConfig,
    OrcaRouterSidecarError,
    OrcaRouterSidecarUnavailableError,
)
from app.core.openai.chat_requests import ChatCompletionsRequest
from app.core.types import JsonValue
from app.modules.proxy.claude_sidecar_dispatch import SidecarUsage, extract_billed_cost, extract_usage
from app.modules.proxy.orcarouter_sidecar_dispatch import (
    _finalize_or_release_orcarouter_reservation,
    _log_orcarouter_request,
    _orcarouter_request_cost,
    build_orcarouter_chat_payload,
    proxy_chat_to_orcarouter,
)


def _config(
    *,
    enabled: bool = True,
    prefixes: tuple[SidecarPrefix, ...] = (SidecarPrefix(prefix="orcarouter/", strip=False),),
    default_reasoning_effort: str | None = None,
) -> OrcaRouterSidecarConfig:
    return OrcaRouterSidecarConfig(
        enabled=enabled,
        base_url="https://api.orcarouter.ai/v1",
        api_key="key",
        prefixes=prefixes,
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
        default_reasoning_effort=default_reasoning_effort,
    )


def test_build_orcarouter_chat_payload_preserves_extra_fields_and_effective_model() -> None:
    request = ChatCompletionsRequest.model_validate(
        {
            "model": "gpt-5.4",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
            "temperature": 0.2,
            "custom_flag": "kept",
        }
    )

    payload = build_orcarouter_chat_payload(request, "orcarouter/auto", _config())

    assert payload.body["model"] == "orcarouter/auto"
    assert payload.body["messages"] == [{"role": "user", "content": "hi"}]
    assert payload.body["custom_flag"] == "kept"


def test_build_orcarouter_chat_payload_injects_override_effort_when_absent() -> None:
    request = ChatCompletionsRequest.model_validate(
        {"model": "gpt-5.4", "messages": [{"role": "user", "content": "hi"}]}
    )

    payload = build_orcarouter_chat_payload(request, "orcarouter/auto", _config(default_reasoning_effort="high"))

    assert payload.body["reasoning_effort"] == "high"


def test_build_orcarouter_chat_payload_override_replaces_client_effort() -> None:
    request = ChatCompletionsRequest.model_validate(
        {
            "model": "gpt-5.4",
            "messages": [{"role": "user", "content": "hi"}],
            "reasoning_effort": "low",
        }
    )

    payload = build_orcarouter_chat_payload(request, "orcarouter/auto", _config(default_reasoning_effort="high"))

    assert payload.body["reasoning_effort"] == "high"


def test_build_orcarouter_chat_payload_override_replaces_nested_reasoning() -> None:
    request = ChatCompletionsRequest.model_validate(
        {
            "model": "gpt-5.4",
            "messages": [{"role": "user", "content": "hi"}],
            "reasoning": {"effort": "minimal"},
        }
    )

    payload = build_orcarouter_chat_payload(request, "orcarouter/auto", _config(default_reasoning_effort="high"))

    assert payload.body["reasoning_effort"] == "high"
    assert "reasoning" not in payload.body


@pytest.mark.asyncio
async def test_log_orcarouter_request_passes_authoritative_cost(monkeypatch: pytest.MonkeyPatch) -> None:
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

    monkeypatch.setattr("app.modules.proxy.orcarouter_sidecar_dispatch.get_background_session", _SessionContext)
    monkeypatch.setattr("app.modules.proxy.orcarouter_sidecar_dispatch.RequestLogsRepository", _Repository)
    monkeypatch.setattr("app.modules.proxy.orcarouter_sidecar_dispatch.get_request_id", lambda: "req-orcarouter-cost")

    await _log_orcarouter_request(
        api_key=None,
        model="orcarouter/auto",
        started_at=0,
        status="success",
        usage=SidecarUsage(input_tokens=10, output_tokens=5, cost_usd=0.00123),
    )

    assert len(calls) == 1
    assert calls[0]["request_id"] == "req-orcarouter-cost"
    assert calls[0]["source"] == "orcarouter_sidecar"
    assert calls[0]["cost_usd"] == 0.00123


@pytest.mark.asyncio
async def test_partial_usage_keeps_orcarouter_billed_cost_on_log_and_quota(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    finalized: list[dict[str, object]] = []
    logged: list[dict[str, object]] = []

    class _SessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

    class _ApiKeysService:
        def __init__(self, repository: object) -> None:
            self.repository = repository

        async def finalize_usage_reservation(self, reservation_id: str, **kwargs: object) -> None:
            finalized.append({"reservation_id": reservation_id, **kwargs})

    class _Repository:
        def __init__(self, session: object) -> None:
            self.session = session

        async def add_log(self, **kwargs: object) -> None:
            logged.append(kwargs)

    monkeypatch.setattr("app.modules.proxy.orcarouter_sidecar_dispatch.get_background_session", _SessionContext)
    monkeypatch.setattr("app.modules.proxy.orcarouter_sidecar_dispatch.ApiKeysService", _ApiKeysService)
    monkeypatch.setattr("app.modules.proxy.orcarouter_sidecar_dispatch.RequestLogsRepository", _Repository)
    monkeypatch.setattr("app.modules.proxy.orcarouter_sidecar_dispatch.get_request_id", lambda: "req-billed")

    payload = {"usage": {"prompt_tokens": 10, "cost_usd": 0.0125}}
    usage = extract_usage(payload)
    cost = await _orcarouter_request_cost(
        "vendor/model-x",
        usage,
        billed_cost_usd=extract_billed_cost(payload),
    )
    await _finalize_or_release_orcarouter_reservation(
        SimpleNamespace(reservation_id="reservation-1"),
        api_key=None,
        model="vendor/model-x",
        usage=usage,
        cost=cost,
    )
    await _log_orcarouter_request(
        api_key=None,
        model="vendor/model-x",
        started_at=0,
        status="success",
        usage=usage,
        cost=cost,
    )

    assert cost.cost_usd == pytest.approx(0.0125)
    assert cost.cost_source == "upstream_billed"
    assert finalized[0]["cost_microdollars"] == 12_500
    assert logged[0]["cost_usd"] == pytest.approx(0.0125)
    assert logged[0]["cost_source"] == "upstream_billed"


@pytest.mark.asyncio
async def test_log_orcarouter_free_request_records_reference_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.usage.pricing import ModelPrice
    from app.core.usage.runtime_pricing import get_runtime_pricing_registry

    registry = get_runtime_pricing_registry()
    registry.clear()
    registry.update_models([("vendor/model-x", ModelPrice(input_per_1m=0.8, output_per_1m=4.0))])

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

    monkeypatch.setattr("app.modules.proxy.orcarouter_sidecar_dispatch.get_background_session", _SessionContext)
    monkeypatch.setattr("app.modules.proxy.orcarouter_sidecar_dispatch.RequestLogsRepository", _Repository)
    monkeypatch.setattr("app.modules.proxy.orcarouter_sidecar_dispatch.get_request_id", lambda: "req-free")

    await _log_orcarouter_request(
        api_key=None,
        model="vendor/model-x:free",
        started_at=0,
        status="success",
        usage=SidecarUsage(input_tokens=10_000, output_tokens=2_000, cost_usd=0.0),
    )

    registry.clear()
    assert len(calls) == 1
    # Free model: actual spend is 0 but reference (paid-equivalent) cost is recorded.
    assert calls[0]["cost_usd"] == 0.0
    assert calls[0]["reference_cost_usd"] == pytest.approx(0.016)


@pytest.mark.asyncio
async def test_shared_model_id_is_priced_per_provider_in_the_request_log(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each provider's request log must use that provider's own list price.

    OpenRouter and OrcaRouter both list ids like ``deepseek/deepseek-chat``. With
    one unqualified pricing key space the last refresh won, so one provider's
    request could record the other's ``reference_cost_usd``.
    """

    from app.core.usage.pricing import ModelPrice
    from app.core.usage.runtime_pricing import get_runtime_pricing_registry
    from app.modules.proxy.openrouter_sidecar_dispatch import _log_openrouter_request

    registry = get_runtime_pricing_registry()
    registry.clear()
    registry.update_models(
        [("deepseek/deepseek-chat", ModelPrice(input_per_1m=1.0, output_per_1m=2.0))],
        provider="openrouter",
    )
    # OrcaRouter refreshes last, which used to redefine the shared entry.
    registry.update_models(
        [("deepseek/deepseek-chat", ModelPrice(input_per_1m=10.0, output_per_1m=20.0))],
        provider="orcarouter",
    )

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

    for module in (
        "app.modules.proxy.orcarouter_sidecar_dispatch",
        "app.modules.proxy.openrouter_sidecar_dispatch",
    ):
        monkeypatch.setattr(f"{module}.get_background_session", _SessionContext)
        monkeypatch.setattr(f"{module}.RequestLogsRepository", _Repository)
        monkeypatch.setattr(f"{module}.get_request_id", lambda: "req-shared-model")

    usage = SidecarUsage(input_tokens=1_000_000, output_tokens=1_000_000, cost_usd=None)
    await _log_openrouter_request(
        api_key=None,
        model="deepseek/deepseek-chat",
        started_at=0,
        status="success",
        usage=usage,
    )
    await _log_orcarouter_request(
        api_key=None,
        model="deepseek/deepseek-chat",
        started_at=0,
        status="success",
        usage=usage,
    )

    registry.clear()
    by_source = {call["source"]: call for call in calls}
    assert by_source["openrouter_sidecar"]["reference_cost_usd"] == pytest.approx(3.0)
    assert by_source["orcarouter_sidecar"]["reference_cost_usd"] == pytest.approx(30.0)


def test_build_orcarouter_chat_payload_captures_requested_and_effective_with_override() -> None:
    request = ChatCompletionsRequest.model_validate(
        {
            "model": "gpt-5.4",
            "messages": [{"role": "user", "content": "hi"}],
            "reasoning_effort": "medium",
        }
    )

    payload = build_orcarouter_chat_payload(request, "orcarouter/auto", _config(default_reasoning_effort="high"))

    assert payload.requested_reasoning_effort == "medium"
    assert payload.effective_reasoning_effort == "high"


def test_build_orcarouter_chat_payload_requested_equals_effective_without_override() -> None:
    request = ChatCompletionsRequest.model_validate(
        {
            "model": "gpt-5.4",
            "messages": [{"role": "user", "content": "hi"}],
            "reasoning_effort": "high",
        }
    )

    payload = build_orcarouter_chat_payload(request, "orcarouter/auto", _config())

    assert payload.requested_reasoning_effort == "high"
    assert payload.effective_reasoning_effort == "high"


def test_build_orcarouter_chat_payload_requested_none_effective_override() -> None:
    request = ChatCompletionsRequest.model_validate(
        {"model": "gpt-5.4", "messages": [{"role": "user", "content": "hi"}]}
    )

    payload = build_orcarouter_chat_payload(request, "orcarouter/auto", _config(default_reasoning_effort="low"))

    assert payload.requested_reasoning_effort is None
    assert payload.effective_reasoning_effort == "low"


class _RetryChatClient:
    def __init__(self, results: list[JsonValue | Exception]) -> None:
        self._results = list(results)
        self.calls = 0
        self.config = _config()

    async def chat_completion(self, payload: object) -> JsonValue:
        del payload
        self.calls += 1
        item = self._results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class _RetryStreamClient:
    def __init__(self, attempts: list[Exception | list[bytes | Exception]]) -> None:
        self._attempts = list(attempts)
        self.calls = 0
        self.config = _config()

    def stream_chat_completion(self, payload: object) -> "_RetryStreamContext":
        del payload
        self.calls += 1
        return _RetryStreamContext(self._attempts.pop(0))


class _RetryStreamContext:
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


def _silence_orcarouter_logs(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
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

    monkeypatch.setattr("app.modules.proxy.orcarouter_sidecar_dispatch.get_background_session", _SessionContext)
    monkeypatch.setattr("app.modules.proxy.orcarouter_sidecar_dispatch.RequestLogsRepository", _Repository)
    monkeypatch.setattr("app.modules.proxy.orcarouter_sidecar_dispatch.get_request_id", lambda: "req-retry")
    return logged


def _chat_request(*, stream: bool) -> ChatCompletionsRequest:
    return ChatCompletionsRequest.model_validate(
        {
            "model": "z-ai/glm-5.3-flash",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": stream,
        }
    )


def _completion() -> dict[str, JsonValue]:
    return {
        "id": "chatcmpl-retry",
        "choices": [{"message": {"role": "assistant", "content": "ok"}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
    }


async def _proxy(client: object, *, stream: bool):
    return await proxy_chat_to_orcarouter(
        cast(Request, SimpleNamespace()),
        _chat_request(stream=stream),
        effective_model="z-ai/glm-5.3-flash",
        api_key=None,
        reservation=None,
        rate_limit_headers={},
        sse_keepalive_interval_seconds=0,
        client=cast(OrcaRouterSidecarClient, client),
    )


async def _read_stream(response: StreamingResponse) -> bytes:
    chunks: list[bytes] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk if isinstance(chunk, bytes) else str(chunk).encode())
    return b"".join(chunks)


@pytest.mark.asyncio
async def test_orcarouter_retries_524_then_returns_the_second_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    logged = _silence_orcarouter_logs(monkeypatch)
    client = _RetryChatClient(
        [
            OrcaRouterSidecarError(524, "OrcaRouter sidecar returned HTTP 524"),
            _completion(),
        ]
    )

    response = await _proxy(client, stream=False)

    assert response.status_code == 200
    assert json.loads(bytes(response.body))["id"] == "chatcmpl-retry"
    assert client.calls == 2
    assert logged[0]["status"] == "success"
    assert len(logged) == 1


@pytest.mark.asyncio
async def test_orcarouter_returns_the_second_524_once(monkeypatch: pytest.MonkeyPatch) -> None:
    logged = _silence_orcarouter_logs(monkeypatch)
    client = _RetryChatClient(
        [
            OrcaRouterSidecarError(524, "OrcaRouter sidecar returned HTTP 524"),
            OrcaRouterSidecarError(524, "OrcaRouter sidecar returned HTTP 524"),
        ]
    )

    response = await _proxy(client, stream=False)

    assert response.status_code == 524
    assert json.loads(bytes(response.body))["error"]["message"] == "OrcaRouter sidecar returned HTTP 524"
    assert client.calls == 2
    assert len(logged) == 1
    assert logged[0]["status"] == "error"


@pytest.mark.asyncio
async def test_orcarouter_does_not_retry_http_400(monkeypatch: pytest.MonkeyPatch) -> None:
    _silence_orcarouter_logs(monkeypatch)
    client = _RetryChatClient(
        [OrcaRouterSidecarError(400, "bad request", body={"error": {"message": "bad request"}})]
    )

    response = await _proxy(client, stream=False)

    assert response.status_code == 400
    assert client.calls == 1


@pytest.mark.asyncio
async def test_orcarouter_retries_transport_failure_once(monkeypatch: pytest.MonkeyPatch) -> None:
    _silence_orcarouter_logs(monkeypatch)
    client = _RetryChatClient([OrcaRouterSidecarUnavailableError("connection reset"), _completion()])

    response = await _proxy(client, stream=False)

    assert response.status_code == 200
    assert client.calls == 2


@pytest.mark.asyncio
async def test_orcarouter_stream_retries_502_before_any_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    logged = _silence_orcarouter_logs(monkeypatch)
    client = _RetryStreamClient(
        [
            OrcaRouterSidecarError(502, "bad gateway"),
            [b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n', b"data: [DONE]\n\n"],
        ]
    )

    response = await _proxy(client, stream=True)
    body = await _read_stream(response)

    assert client.calls == 2
    assert b'"content":"ok"' in body
    assert b"bad gateway" not in body
    assert logged[0]["status"] == "success"


@pytest.mark.asyncio
async def test_orcarouter_stream_does_not_retry_after_a_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    _silence_orcarouter_logs(monkeypatch)
    client = _RetryStreamClient(
        [
            [
                b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n',
                OrcaRouterSidecarError(524, "OrcaRouter sidecar returned HTTP 524"),
            ],
            [b'data: {"choices":[{"delta":{"content":"nope"}}]}\n\n', b"data: [DONE]\n\n"],
        ]
    )

    response = await _proxy(client, stream=True)
    body = await _read_stream(response)

    assert client.calls == 1
    assert b'"content":"hi"' in body
    assert b"nope" not in body
    assert b"HTTP 524" in body
