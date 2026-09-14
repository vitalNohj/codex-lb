from __future__ import annotations

import json

import pytest
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.clients.claude_sidecar import SidecarPrefix
from app.core.clients.opencode_go_sidecar import (
    OpenCodeGoSidecarConfig,
    OpenCodeGoSidecarError,
    OpenCodeGoSidecarUnavailableError,
)
from app.core.openai.chat_requests import ChatCompletionsRequest
from app.modules.proxy.opencode_go_sidecar_dispatch import (
    OPENCODE_GO_SIDECAR_SOURCE,
    _headers_with_retry_after,
    build_opencode_go_chat_payload,
    opencode_go_routing_entry,
    proxy_chat_to_opencode_go,
)
from app.modules.proxy.sidecar_routing import SidecarRoutingEntry, resolve_sidecar_route

pytestmark = pytest.mark.unit


def _config(**overrides) -> OpenCodeGoSidecarConfig:
    values = {
        "enabled": True,
        "base_url": "https://opencode.ai/zen/go/v1",
        "api_key": "sk-go-key",
        "prefixes": (SidecarPrefix(prefix="opencode-go/", strip=True),),
        "connect_timeout_seconds": 8.0,
        "request_timeout_seconds": 600.0,
        "models_cache_ttl_seconds": 60.0,
        "full_models": (),
    }
    values.update(overrides)
    return OpenCodeGoSidecarConfig(**values)


class _FakeRequest:
    def __init__(self, headers: dict[str, str] | None = None) -> None:
        self.headers = headers or {"user-agent": "opencode/1.0"}


class _FakeStream:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def __aenter__(self):
        async def _iter():
            for chunk in self._chunks:
                yield chunk

        return _iter()

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class _FakeClient:
    def __init__(self, *, response=None, error: Exception | None = None, chunks: list[bytes] | None = None) -> None:
        self.config = _config()
        self._response = response
        self._error = error
        self._chunks = chunks or []
        self.calls: list[tuple[dict, dict | None]] = []

    async def chat_completion(self, payload, *, client_headers=None):
        self.calls.append((dict(payload), dict(client_headers) if client_headers else None))
        if self._error is not None:
            raise self._error
        return self._response

    def stream_chat_completion(self, payload, *, client_headers=None):
        self.calls.append((dict(payload), dict(client_headers) if client_headers else None))
        if self._error is not None:
            raise self._error
        return _FakeStream(self._chunks)


@pytest.fixture(autouse=True)
def _isolate_side_effects(monkeypatch: pytest.MonkeyPatch):
    """Keep dispatch off the database and off the pricing network.

    Every test here exercises request handling, so logging and reservation
    settlement are captured in memory rather than written. Pricing is stubbed to
    a fixed answer so a test asserting dispatch behavior cannot fail because the
    price store was empty.
    """

    logs: list[dict] = []

    async def _log(**kwargs):
        logs.append(kwargs)

    class _Cost:
        cost_usd = None
        cost_source = None
        price_status = None

    async def _cost(*_args, **_kwargs):
        return _Cost()

    class _Settlement:
        usage = None
        cost = _Cost()

    async def _settlement(**_kwargs):
        return _Settlement()

    async def _settle(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.modules.proxy.opencode_go_sidecar_dispatch._log_opencode_go_request", _log)
    monkeypatch.setattr("app.modules.proxy.opencode_go_sidecar_dispatch.external_request_cost", _cost)
    monkeypatch.setattr("app.modules.proxy.opencode_go_sidecar_dispatch.external_response_settlement", _settlement)
    monkeypatch.setattr(
        "app.modules.proxy.opencode_go_sidecar_dispatch._finalize_or_release_opencode_go_reservation", _settle
    )
    monkeypatch.setattr("app.modules.proxy.opencode_go_sidecar_dispatch._release_opencode_go_reservation", _settle)
    return logs


def _chat_request(model: str, *, stream: bool = False) -> ChatCompletionsRequest:
    return ChatCompletionsRequest.model_validate(
        {"model": model, "messages": [{"role": "user", "content": "hi"}], "stream": stream}
    )


async def _dispatch(client, model: str, *, stream: bool = False, headers=None, wire_model: str | None = None):
    return await proxy_chat_to_opencode_go(
        _FakeRequest(headers),  # type: ignore[arg-type]
        _chat_request(model, stream=stream),
        effective_model=model,
        api_key=None,
        reservation=None,
        rate_limit_headers={},
        sse_keepalive_interval_seconds=15.0,
        client=client,  # type: ignore[arg-type]
        wire_model=wire_model,
    )


# --------------------------------------------------------------------------
# Payload construction
# --------------------------------------------------------------------------


def test_payload_uses_resolved_wire_model_and_keeps_extra_fields() -> None:
    request = ChatCompletionsRequest.model_validate(
        {
            "model": "opencode-go/glm-5.3",
            "messages": [{"role": "user", "content": "hi"}],
            "temperature": 0.2,
            "custom_flag": "kept",
        }
    )

    payload = build_opencode_go_chat_payload(request, "glm-5.3")

    assert payload.body["model"] == "glm-5.3"
    assert payload.body["custom_flag"] == "kept"


# --------------------------------------------------------------------------
# Routing
# --------------------------------------------------------------------------


def test_routing_entry_strips_the_opencode_go_prefix() -> None:
    entry = opencode_go_routing_entry(_config())

    decision = resolve_sidecar_route("opencode-go/glm-5.3", (entry,))

    assert decision is not None
    assert decision.provider == "opencode_go"
    # OpenCode's own config format is ``opencode-go/<id>``; the prefix is an
    # alias and must come off before the wire model is sent.
    assert decision.wire_model == "glm-5.3"


def test_underscore_spelling_does_not_route_by_accident() -> None:
    """``opencode_go/`` is not an alias for the configured ``opencode-go/``.

    The resolver's ``-``/``_`` interchange applies only to a prefix whose *final*
    character is the separator (``cc-`` / ``cc_``). ``opencode-go/`` ends in
    ``/``, so the hyphen inside it is literal. Recorded as a test because the
    hyphen/underscore mismatch between the operator-facing prefix and the
    internal provider key is exactly the kind of thing later reading would
    assume works.
    """

    entry = opencode_go_routing_entry(_config())

    assert resolve_sidecar_route("opencode_go/glm-5.3", (entry,)) is None
    assert resolve_sidecar_route("opencode-go/glm-5.3", (entry,)) is not None


def test_disabled_integration_contributes_no_route() -> None:
    # The caller only appends entries for enabled integrations; with none
    # contributed the model must not resolve to OpenCode Go.
    assert resolve_sidecar_route("opencode-go/glm-5.3", ()) is None


def test_another_integrations_prefix_is_not_stolen() -> None:
    entries = (
        opencode_go_routing_entry(_config()),
        SidecarRoutingEntry(provider="orcarouter", prefixes=(SidecarPrefix("orcarouter/", False),), full_models=()),
    )

    decision = resolve_sidecar_route("orcarouter/deepseek-chat", entries)

    assert decision is not None
    assert decision.provider == "orcarouter"


def test_longest_prefix_wins_over_opencode_go() -> None:
    entries = (
        opencode_go_routing_entry(_config()),
        SidecarRoutingEntry(
            provider="orcarouter", prefixes=(SidecarPrefix("opencode-go/special-", True),), full_models=()
        ),
    )

    decision = resolve_sidecar_route("opencode-go/special-model", entries)

    assert decision is not None
    assert decision.provider == "orcarouter"


# --------------------------------------------------------------------------
# Protocol gate
# --------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["qwen3.7-plus", "minimax-m3", "grok-4.6", "muse-spark-1.3-contributor", "nope-1"])
async def test_unsupported_model_is_rejected_without_any_upstream_call(model: str, _isolate_side_effects) -> None:
    client = _FakeClient(response={})

    response = await _dispatch(client, model)

    assert isinstance(response, JSONResponse)
    assert response.status_code == 400
    body = json.loads(bytes(response.body))
    assert body["error"]["code"] == "opencode_go_model_unsupported"
    # The gate runs before dispatch: no request reaches the subscription.
    assert client.calls == []


@pytest.mark.asyncio
async def test_unsupported_model_rejection_is_logged(_isolate_side_effects) -> None:
    await _dispatch(_FakeClient(response={}), "qwen3.7-plus")

    assert _isolate_side_effects[-1]["error_code"] == "opencode_go_model_unsupported"
    assert _isolate_side_effects[-1]["status"] == "error"


@pytest.mark.asyncio
async def test_supported_model_reaches_the_upstream(_isolate_side_effects) -> None:
    client = _FakeClient(response={"id": "x", "choices": []})

    response = await _dispatch(client, "opencode-go/glm-5.3", wire_model="glm-5.3")

    assert response.status_code == 200
    assert client.calls[0][0]["model"] == "glm-5.3"


# --------------------------------------------------------------------------
# Session identity threading
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_client_headers_are_threaded_to_the_client(_isolate_side_effects) -> None:
    client = _FakeClient(response={})

    await _dispatch(
        client,
        "glm-5.3",
        headers={"user-agent": "opencode/1.0", "x-opencode-session": "ses_abc"},
    )

    _payload, headers = client.calls[0]
    assert headers is not None
    assert headers["x-opencode-session"] == "ses_abc"


@pytest.mark.asyncio
async def test_streaming_also_threads_client_headers(_isolate_side_effects) -> None:
    client = _FakeClient(chunks=[b"data: [DONE]\n\n"])

    response = await _dispatch(client, "glm-5.3", stream=True, headers={"user-agent": "opencode/1.0"})

    assert isinstance(response, StreamingResponse)
    async for _chunk in response.body_iterator:
        pass
    assert client.calls[0][1] is not None


# --------------------------------------------------------------------------
# Error handling
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upstream_401_becomes_503_with_retry_after(_isolate_side_effects) -> None:
    client = _FakeClient(error=OpenCodeGoSidecarError(401, "Missing API key.", body={}))

    response = await _dispatch(client, "glm-5.3")

    # Once the *client's* API key was accepted, an upstream credential failure
    # is a provider-side problem. Passing 401 through kills long-running coding
    # clients that treat it as fatal.
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "60"


@pytest.mark.asyncio
async def test_upstream_403_becomes_503(_isolate_side_effects) -> None:
    response = await _dispatch(_FakeClient(error=OpenCodeGoSidecarError(403, "forbidden", body={})), "glm-5.3")

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_upstream_429_is_relayed_with_its_own_retry_after(_isolate_side_effects) -> None:
    client = _FakeClient(
        error=OpenCodeGoSidecarError(
            429, "rate limited", body={"error": {"message": "rate limited"}}, retry_after="137"
        )
    )

    response = await _dispatch(client, "glm-5.3")

    assert response.status_code == 429
    assert response.headers["retry-after"] == "137"


@pytest.mark.asyncio
async def test_transport_failure_becomes_503_unavailable(_isolate_side_effects) -> None:
    client = _FakeClient(error=OpenCodeGoSidecarUnavailableError("dead"))

    response = await _dispatch(client, "glm-5.3")

    assert response.status_code == 503
    assert json.loads(bytes(response.body))["error"]["code"] == "opencode_go_sidecar_unavailable"


@pytest.mark.asyncio
async def test_upstream_error_message_is_redacted_before_reaching_the_client(_isolate_side_effects) -> None:
    key = "sk-go-abcdef0123456789"
    client = _FakeClient(
        error=OpenCodeGoSidecarError(
            400,
            f"Invalid key {key}",
            body={"error": {"message": f"Invalid key {key}"}},
        )
    )
    client.config = _config(api_key=key)

    response = await _dispatch(client, "glm-5.3")

    assert key not in bytes(response.body).decode()


def test_headers_with_retry_after_omits_the_header_when_upstream_sent_none() -> None:
    error = OpenCodeGoSidecarError(429, "rate limited", body={})

    assert "Retry-After" not in _headers_with_retry_after({}, error)


# --------------------------------------------------------------------------
# Streaming lifecycle
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_relays_chunks_and_marks_success_on_done(_isolate_side_effects) -> None:
    chunks = [
        b'data: {"choices":[{"delta":{"content":"he"}}]}\n\n',
        b'data: {"choices":[{"delta":{"content":"llo"}}],'
        b'"usage":{"prompt_tokens":10,"completion_tokens":5}}\n\n',
        b"data: [DONE]\n\n",
    ]
    response = await _dispatch(_FakeClient(chunks=chunks), "glm-5.3", stream=True)

    received = b""
    async for chunk in response.body_iterator:
        received += chunk if isinstance(chunk, bytes) else chunk.encode()

    # Chunks are relayed byte for byte, in order, and untouched.
    assert received == b"".join(chunks)
    assert _isolate_side_effects[-1]["status"] == "success"


@pytest.mark.asyncio
async def test_stream_without_done_is_logged_incomplete(_isolate_side_effects) -> None:
    chunks = [b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n']

    response = await _dispatch(_FakeClient(chunks=chunks), "glm-5.3", stream=True)
    async for _chunk in response.body_iterator:
        pass

    assert _isolate_side_effects[-1]["status"] == "error"
    assert _isolate_side_effects[-1]["error_code"] == "opencode_go_sidecar_stream_incomplete"


@pytest.mark.asyncio
async def test_stream_tool_calls_are_relayed_verbatim(_isolate_side_effects) -> None:
    tool_chunk = (
        b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1",'
        b'"function":{"name":"ls","arguments":"{}"}}]}}]}\n\n'
    )
    response = await _dispatch(_FakeClient(chunks=[tool_chunk, b"data: [DONE]\n\n"]), "glm-5.3", stream=True)

    received = b""
    async for chunk in response.body_iterator:
        received += chunk if isinstance(chunk, bytes) else chunk.encode()

    assert b'"tool_calls"' in received
    assert b"call_1" in received


@pytest.mark.asyncio
async def test_stream_usage_is_requested_so_pricing_gets_tokens(_isolate_side_effects) -> None:
    client = _FakeClient(chunks=[b"data: [DONE]\n\n"])

    response = await _dispatch(client, "glm-5.3", stream=True)
    async for _chunk in response.body_iterator:
        pass

    # Without this the upstream omits the usage object entirely and the pricing
    # module receives no tokens for a streamed request.
    assert client.calls[0][0]["stream_options"] == {"include_usage": True}


@pytest.mark.asyncio
async def test_stream_upstream_error_emits_error_event_then_done(_isolate_side_effects) -> None:
    client = _FakeClient(error=OpenCodeGoSidecarError(500, "upstream boom", body={}))

    response = await _dispatch(client, "glm-5.3", stream=True)
    received = b""
    async for chunk in response.body_iterator:
        received += chunk if isinstance(chunk, bytes) else chunk.encode()

    assert b"opencode_go_sidecar_error" in received
    assert received.rstrip().endswith(b"data: [DONE]")


@pytest.mark.asyncio
async def test_stream_cancellation_still_settles_and_logs(_isolate_side_effects) -> None:
    class _ExplodingStream:
        async def __aenter__(self):
            async def _iter():
                yield b'data: {"choices":[{"delta":{"content":"a"}}]}\n\n'
                raise GeneratorExit

            return _iter()

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    class _Client(_FakeClient):
        def stream_chat_completion(self, payload, *, client_headers=None):
            self.calls.append((dict(payload), None))
            return _ExplodingStream()

    response = await _dispatch(_Client(), "glm-5.3", stream=True)
    with pytest.raises(BaseException):
        async for _chunk in response.body_iterator:
            pass

    # A cancelled stream must neither leak a reservation nor lose the log row.
    assert _isolate_side_effects[-1]["error_code"] == "opencode_go_sidecar_stream_interrupted"


# --------------------------------------------------------------------------
# Log source
# --------------------------------------------------------------------------


def test_log_source_matches_the_published_pricing_contract() -> None:
    from app.core.usage.external_pricing.providers import (
        PROVIDER_OPENCODE_GO,
        external_priced_provider_for_log_source,
        is_external_priced_log_source,
    )

    assert OPENCODE_GO_SIDECAR_SOURCE == "opencode_go_sidecar"
    assert is_external_priced_log_source(OPENCODE_GO_SIDECAR_SOURCE)
    assert external_priced_provider_for_log_source(OPENCODE_GO_SIDECAR_SOURCE) == PROVIDER_OPENCODE_GO
