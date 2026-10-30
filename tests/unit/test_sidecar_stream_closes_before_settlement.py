"""The Claude sidecar closes the client stream before usage settlement.

The write that used to fill the gap is ``_settle_and_log_sidecar_stream`` (chat)
and ``_settle_and_log`` (native Responses). Both ran in the body generator's
``finally``, so Starlette could not send ``more_body=False`` until they
finished. They now run from ``ClosingStreamingResponse`` after that frame.
Usage, the request log, and a mid-stream disconnect still settle once.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
from starlette.requests import Request
from starlette.types import Message, Scope

from app.core.clients.claude_sidecar import ClaudeSidecarClient, ClaudeSidecarConfig, SidecarPrefix
from app.core.openai.chat_requests import ChatCompletionsRequest
from app.core.openai.requests import ResponsesRequest
from app.modules.proxy import claude_sidecar_dispatch, cliproxy_responses_dispatch, responses_provider_dispatch
from app.modules.proxy.cliproxy_account_routing import CliproxyStickyHints

pytestmark = pytest.mark.unit

_SCOPE: Scope = {
    "type": "http",
    "asgi": {"version": "3.0", "spec_version": "2.3"},
    "http_version": "1.1",
    "method": "POST",
    "scheme": "http",
    "path": "/v1/chat/completions",
    "raw_path": b"/v1/chat/completions",
    "query_string": b"",
    "headers": [],
    "client": ("127.0.0.1", 9),
    "server": ("127.0.0.1", 80),
}


def _config() -> ClaudeSidecarConfig:
    return ClaudeSidecarConfig(
        enabled=True,
        base_url="http://127.0.0.1:9",
        api_key="sk-test",
        prefixes=(SidecarPrefix(prefix="claude", strip=False),),
        connect_timeout_seconds=1.0,
        request_timeout_seconds=1.0,
        models_cache_ttl_seconds=0.0,
    )


class _ChunkStream:
    def __init__(self, chunks: list[bytes], *, hold: asyncio.Event | None = None) -> None:
        self._chunks = chunks
        self._hold = hold

    async def __aenter__(self) -> AsyncIterator[bytes]:
        chunks = self._chunks
        hold = self._hold

        async def iterate() -> AsyncIterator[bytes]:
            for chunk in chunks:
                yield chunk
            if hold is not None:
                await hold.wait()

        return iterate()

    async def __aexit__(self, *exc: object) -> bool:
        del exc
        return False


class _ChatUpstream:
    def __init__(self, chunks: list[bytes], *, hold: asyncio.Event | None = None) -> None:
        self.config = _config()
        self._chunks = chunks
        self._hold = hold

    def stream_chat_completion(self, payload: object) -> _ChunkStream:
        del payload
        return _ChunkStream(self._chunks, hold=self._hold)


class _ResponsesUpstream:
    def __init__(self, chunks: list[bytes], *, hold: asyncio.Event | None = None) -> None:
        self.config = _config()
        self._chunks = chunks
        self._hold = hold

    def stream_responses(self, payload: object) -> _ChunkStream:
        del payload
        return _ChunkStream(self._chunks, hold=self._hold)


def _sse(event: dict[str, Any]) -> bytes:
    return f"event: {event['type']}\ndata: {json.dumps(event)}\n\n".encode()


def _chat_usage_chunks() -> list[bytes]:
    return [
        b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n',
        (
            b'data: {"choices":[],"usage":{"prompt_tokens":11,"completion_tokens":4,'
            b'"prompt_tokens_details":{"cached_tokens":2}}}\n\n'
        ),
        b"data: [DONE]\n\n",
    ]


async def _no_route(*args: object, **kwargs: object) -> None:
    del args, kwargs


async def _drive(response: object, send: Any) -> None:
    await cast(Any, response)(_SCOPE, _never_disconnects, send)


async def _never_disconnects() -> Message:
    await asyncio.Event().wait()
    raise AssertionError("unreachable")


def _recording_send(order: list[str]) -> Any:
    async def send(message: Message) -> None:
        if message.get("type") != "http.response.body":
            return
        order.append("closed" if not message.get("more_body", True) else "chunk")

    return send


@pytest.fixture
def _no_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(claude_sidecar_dispatch, "CLAUDE_SIDECAR_COOLDOWN_WAIT_SECONDS", 0.0)
    monkeypatch.setattr(claude_sidecar_dispatch, "apply_cliproxy_account_route", _no_route)
    monkeypatch.setattr(cliproxy_responses_dispatch, "apply_cliproxy_account_route", _no_route)


@pytest.mark.asyncio
async def test_chat_stream_closes_before_usage_settlement(_no_cooldown: None, monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    seen: list[dict[str, Any]] = []

    async def settle(reservation: object, **kwargs: Any) -> None:
        del reservation
        order.append("settled")
        seen.append(kwargs)

    monkeypatch.setattr(claude_sidecar_dispatch, "_settle_and_log_sidecar_stream", settle)
    response = await claude_sidecar_dispatch.proxy_chat_to_sidecar(
        Request(_SCOPE),
        ChatCompletionsRequest(
            model="bench-instant",
            messages=[{"role": "user", "content": "hi"}],
            stream=True,
        ),
        effective_model="bench-instant",
        api_key=None,
        reservation=None,
        rate_limit_headers={},
        sse_keepalive_interval_seconds=0.0,
        client=cast(ClaudeSidecarClient, _ChatUpstream(_chat_usage_chunks())),
    )

    await _drive(response, _recording_send(order))

    assert order.index("closed") < order.index("settled")
    assert seen[0]["completed"] is True
    usage = seen[0]["usage"]
    assert usage.input_tokens == 11
    assert usage.output_tokens == 4
    assert usage.cached_input_tokens == 2
    assert order.count("settled") == 1


@pytest.mark.asyncio
async def test_native_stream_closes_before_usage_settlement(
    _no_cooldown: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []
    seen: list[dict[str, Any]] = []
    completed = {
        "type": "response.completed",
        "response": {
            "id": "resp_1",
            "status": "completed",
            "usage": {"input_tokens": 11, "output_tokens": 4, "input_tokens_details": {"cached_tokens": 2}},
        },
    }

    async def settle(reservation: object, **kwargs: Any) -> None:
        del reservation
        order.append("settled")
        seen.append(kwargs)

    monkeypatch.setattr(cliproxy_responses_dispatch, "_settle_and_log", settle)
    response = await cliproxy_responses_dispatch.proxy_responses_to_cliproxy_native(
        Request(_SCOPE),
        ResponsesRequest(model="grok-4", instructions="be brief", input="hi", stream=True),
        effective_model="grok-4",
        wire_model="grok-4",
        api_key=None,
        reservation=None,
        rate_limit_headers={},
        sse_keepalive_interval_seconds=0.0,
        client=cast(ClaudeSidecarClient, _ResponsesUpstream([_sse(completed)])),
        sticky_hints=CliproxyStickyHints(),
    )

    await _drive(response, _recording_send(order))

    assert order.index("closed") < order.index("settled")
    assert seen[0]["failure"] is None
    response_body = seen[0]["response"]
    assert response_body["usage"]["input_tokens"] == 11
    assert response_body["usage"]["output_tokens"] == 4
    assert order.count("settled") == 1


@pytest.mark.asyncio
async def test_native_incomplete_stream_sends_the_failure_frame_before_settlement(
    _no_cooldown: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []
    bodies: list[bytes] = []
    seen: list[Any] = []

    async def settle(reservation: object, **kwargs: Any) -> None:
        del reservation
        order.append("settled")
        seen.append(kwargs["failure"])

    monkeypatch.setattr(cliproxy_responses_dispatch, "_settle_and_log", settle)
    delta = {"type": "response.output_text.delta", "delta": "hi"}
    response = await cliproxy_responses_dispatch.proxy_responses_to_cliproxy_native(
        Request(_SCOPE),
        ResponsesRequest(model="grok-4", instructions="be brief", input="hi", stream=True),
        effective_model="grok-4",
        wire_model="grok-4",
        api_key=None,
        reservation=None,
        rate_limit_headers={},
        sse_keepalive_interval_seconds=0.0,
        client=cast(ClaudeSidecarClient, _ResponsesUpstream([_sse(delta)])),
        sticky_hints=CliproxyStickyHints(),
    )

    async def send(message: Message) -> None:
        if message.get("type") != "http.response.body":
            return
        body = message.get("body", b"")
        if body:
            bodies.append(body if isinstance(body, bytes) else bytes(body))
        if not message.get("more_body", True):
            order.append("closed")

    await _drive(response, send)

    relayed = b"".join(bodies).decode()
    assert "response.failed" in relayed
    assert order == ["closed", "settled"]
    assert seen[0] is not None
    assert seen[0].code == "claude_sidecar_stream_incomplete"


@pytest.mark.asyncio
async def test_chat_disconnect_mid_stream_still_charges_once(
    _no_cooldown: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    outcomes: list[str] = []

    async def settle(*args: object, **kwargs: object) -> None:
        del args, kwargs
        outcomes.append("settled")

    async def charge(*args: object, **kwargs: object) -> None:
        del args, kwargs
        outcomes.append("charged")

    monkeypatch.setattr(claude_sidecar_dispatch, "_settle_and_log_sidecar_stream", settle)
    monkeypatch.setattr(claude_sidecar_dispatch, "_charge_and_log_sidecar_request", charge)
    response = await claude_sidecar_dispatch.proxy_chat_to_sidecar(
        Request(_SCOPE),
        ChatCompletionsRequest(
            model="bench-instant",
            messages=[{"role": "user", "content": "hi"}],
            stream=True,
        ),
        effective_model="bench-instant",
        api_key=None,
        reservation=None,
        rate_limit_headers={},
        sse_keepalive_interval_seconds=0.0,
        client=cast(ClaudeSidecarClient, _ChatUpstream(_chat_usage_chunks(), hold=asyncio.Event())),
    )
    first_chunk = asyncio.Event()

    async def send(message: Message) -> None:
        if message.get("body"):
            first_chunk.set()
            await asyncio.Event().wait()

    async def receive() -> Message:
        await first_chunk.wait()
        return {"type": "http.disconnect"}

    await cast(Any, response)(_SCOPE, receive, send)

    assert outcomes == ["charged"]


@pytest.mark.asyncio
async def test_chat_settlement_finishes_when_cancelled_after_the_body_closes(
    _no_cooldown: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    finished: list[dict[str, Any]] = []

    async def settle(reservation: object, **kwargs: Any) -> None:
        del reservation
        started.set()
        await release.wait()
        finished.append(kwargs)

    monkeypatch.setattr(claude_sidecar_dispatch, "_settle_and_log_sidecar_stream", settle)
    response = await claude_sidecar_dispatch.proxy_chat_to_sidecar(
        Request(_SCOPE),
        ChatCompletionsRequest(
            model="bench-instant",
            messages=[{"role": "user", "content": "hi"}],
            stream=True,
        ),
        effective_model="bench-instant",
        api_key=None,
        reservation=None,
        rate_limit_headers={},
        sse_keepalive_interval_seconds=0.0,
        client=cast(ClaudeSidecarClient, _ChatUpstream(_chat_usage_chunks())),
    )
    task = asyncio.create_task(_drive(response, _recording_send([])))
    await started.wait()
    task.cancel()
    release.set()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished[0]["completed"] is True
    assert finished[0]["usage"].input_tokens == 11
    assert finished[0]["usage"].output_tokens == 4


@pytest.mark.asyncio
async def test_bridged_responses_stream_without_done_settles_once(
    _no_cooldown: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Responses translation replaces the chat response.

    The replacement must keep the after-close write. A chat stream that ends
    without ``[DONE]`` still settles and logs exactly once, and the client
    frame still precedes that write.
    """

    order: list[str] = []
    seen: list[dict[str, Any]] = []

    async def settle(reservation: object, **kwargs: Any) -> None:
        del reservation
        order.append("settled")
        seen.append(kwargs)

    async def no_snapshot() -> None:
        return None

    monkeypatch.setattr(claude_sidecar_dispatch, "_settle_and_log_sidecar_stream", settle)
    monkeypatch.setattr(claude_sidecar_dispatch, "_stored_claude_quota_snapshot", no_snapshot)
    translated = await responses_provider_dispatch.dispatch_responses_via_chat_provider(
        Request(_SCOPE),
        ChatCompletionsRequest(
            model="claude-haiku-4-5",
            messages=[{"role": "user", "content": "hi"}],
            stream=True,
        ),
        provider="claude",
        effective_model="claude-haiku-4-5",
        wire_model=None,
        api_key=None,
        reservation=None,
        rate_limit_headers={},
        sse_keepalive_interval_seconds=0.0,
        cursor_compat=False,
        client=cast(
            ClaudeSidecarClient,
            _ChatUpstream(
                [
                    b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n',
                    (
                        b'data: {"choices":[],"usage":{"prompt_tokens":11,"completion_tokens":4,'
                        b'"prompt_tokens_details":{"cached_tokens":2}}}\n\n'
                    ),
                ]
            ),
        ),
    )

    bodies: list[bytes] = []

    async def send(message: Message) -> None:
        if message.get("type") != "http.response.body":
            return
        body = message.get("body", b"")
        if body:
            bodies.append(body if isinstance(body, bytes) else bytes(body))
            order.append("chunk")
        if not message.get("more_body", True):
            order.append("closed")

    await _drive(translated, send)

    relayed = b"".join(bodies).decode()
    assert "response.incomplete" in relayed or "response.completed" in relayed
    assert relayed.count("data: [DONE]") == 1
    assert order[-2:] == ["closed", "settled"]
    assert order.count("settled") == 1
    # No [DONE], so the chat dispatcher logs the stream as incomplete and
    # does not keep the usage it saw. The row still has to be written once.
    assert seen[0]["completed"] is False
    assert seen[0]["usage"] is None
