"""GPT-5.6 Cursor proactive compaction (success-path usage rewrite)."""

from __future__ import annotations

import asyncio
import contextlib
import json

import pytest

from app.core.openai.chat_requests import ChatCompletionsRequest
from app.core.openai.chat_responses import (
    ChatCompletion,
    ChatCompletionChoice,
    ChatCompletionMessage,
    ChatCompletionUsage,
    stream_chat_chunks,
)
from app.core.utils.stream_close import aclose_stream
from app.modules.proxy.cursor_chat_compat import (
    CURSOR_CONTEXT_LIMIT_SYNTHETIC_USAGE_TOKENS,
    CursorChatSseCompatRewriter,
    apply_cursor_usage_fallback,
    apply_cursor_usage_fallback_to_response,
    needs_cursor_proactive_compaction,
    stream_bytes_with_cursor_usage_fallback,
    stream_responses_with_cursor_context_limit_fallback,
    stream_with_cursor_usage_fallback,
)


def _payload(model: str) -> ChatCompletionsRequest:
    return ChatCompletionsRequest(model=model, messages=[{"role": "user", "content": "hi"}])


def _completion(model: str, *, prompt_tokens: int, completion_tokens: int = 12) -> ChatCompletion:
    return ChatCompletion(
        id="chatcmpl_test",
        object="chat.completion",
        created=1,
        model=model,
        choices=[
            ChatCompletionChoice(
                index=0,
                message=ChatCompletionMessage(role="assistant", content="ok"),
                finish_reason="stop",
            )
        ],
        usage=ChatCompletionUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
    )


def test_needs_cursor_proactive_compaction_at_threshold() -> None:
    assert needs_cursor_proactive_compaction("gpt-5.6-sol", {"prompt_tokens": 350_000}) is True
    assert needs_cursor_proactive_compaction("GPT-5.6-sol-xhigh", {"prompt_tokens": 366_841}) is True


def test_needs_cursor_proactive_compaction_below_threshold() -> None:
    assert needs_cursor_proactive_compaction("gpt-5.6-sol", {"prompt_tokens": 349_999}) is False


def test_needs_cursor_proactive_compaction_skips_non_gpt56() -> None:
    assert needs_cursor_proactive_compaction("gpt-5.5-extra", {"prompt_tokens": 400_000}) is False
    assert needs_cursor_proactive_compaction("gpt-5.6", {"prompt_tokens": 400_000}) is False


def test_needs_cursor_proactive_compaction_skips_bad_usage() -> None:
    assert needs_cursor_proactive_compaction("gpt-5.6-sol", None) is False
    assert needs_cursor_proactive_compaction("gpt-5.6-sol", "nope") is False
    assert needs_cursor_proactive_compaction("gpt-5.6-sol", {"prompt_tokens": "350000"}) is False


def test_apply_cursor_usage_fallback_rewrites_sol_at_threshold() -> None:
    result = _completion("gpt-5.6-sol", prompt_tokens=350_000, completion_tokens=88)
    apply_cursor_usage_fallback(result, _payload("gpt-5.6-sol"), source="test")
    assert result.usage is not None
    assert result.usage.prompt_tokens == CURSOR_CONTEXT_LIMIT_SYNTHETIC_USAGE_TOKENS
    assert result.usage.completion_tokens == 88
    assert result.usage.total_tokens == CURSOR_CONTEXT_LIMIT_SYNTHETIC_USAGE_TOKENS + 88


def test_apply_cursor_usage_fallback_leaves_sol_below_threshold() -> None:
    result = _completion("gpt-5.6-sol", prompt_tokens=349_999, completion_tokens=88)
    apply_cursor_usage_fallback(result, _payload("gpt-5.6-sol"), source="test")
    assert result.usage is not None
    assert result.usage.prompt_tokens == 349_999
    assert result.usage.completion_tokens == 88


def test_apply_cursor_usage_fallback_leaves_gpt55_high_usage() -> None:
    result = _completion("gpt-5.5-extra", prompt_tokens=400_000, completion_tokens=10)
    apply_cursor_usage_fallback(result, _payload("gpt-5.5-extra"), source="test")
    assert result.usage is not None
    assert result.usage.prompt_tokens == 400_000


def test_apply_cursor_usage_fallback_to_response_rewrites_sol() -> None:
    body = {
        "id": "chatcmpl_test",
        "choices": [],
        "usage": {"prompt_tokens": 352_800, "completion_tokens": 40, "total_tokens": 352_840},
    }
    out = apply_cursor_usage_fallback_to_response(body, _payload("gpt-5.6-sol"), source="test")
    assert out["usage"] == {
        "prompt_tokens": CURSOR_CONTEXT_LIMIT_SYNTHETIC_USAGE_TOKENS,
        "completion_tokens": 40,
        "total_tokens": CURSOR_CONTEXT_LIMIT_SYNTHETIC_USAGE_TOKENS + 40,
    }


def test_sse_rewriter_inflates_usage_chunk_for_sol() -> None:
    rewriter = CursorChatSseCompatRewriter(_payload("gpt-5.6-sol"), source="stream_test")
    usage_event = (
        "data: "
        + json.dumps(
            {
                "id": "chatcmpl_stream",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "gpt-5.6-sol",
                "choices": [],
                "usage": {
                    "prompt_tokens": 351_802,
                    "completion_tokens": 16,
                    "total_tokens": 351_818,
                },
            },
            separators=(",", ":"),
        )
        + "\n\n"
    )
    chunks = rewriter.feed(usage_event.encode("utf-8"))
    assert len(chunks) == 1
    line = chunks[0].decode("utf-8").strip()
    assert line.startswith("data: ")
    parsed = json.loads(line.removeprefix("data: "))
    assert parsed["usage"]["prompt_tokens"] == CURSOR_CONTEXT_LIMIT_SYNTHETIC_USAGE_TOKENS
    assert parsed["usage"]["completion_tokens"] == 16
    assert parsed["usage"]["total_tokens"] == CURSOR_CONTEXT_LIMIT_SYNTHETIC_USAGE_TOKENS + 16


def test_sse_rewriter_leaves_usage_chunk_for_gpt55() -> None:
    rewriter = CursorChatSseCompatRewriter(_payload("gpt-5.5-extra"), source="stream_test")
    usage_event = (
        "data: "
        + json.dumps(
            {
                "id": "chatcmpl_stream",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "gpt-5.5-extra",
                "choices": [],
                "usage": {
                    "prompt_tokens": 400_000,
                    "completion_tokens": 16,
                    "total_tokens": 400_016,
                },
            },
            separators=(",", ":"),
        )
        + "\n\n"
    )
    chunks = rewriter.feed(usage_event.encode("utf-8"))
    assert len(chunks) == 1
    parsed = json.loads(chunks[0].decode("utf-8").strip().removeprefix("data: "))
    assert parsed["usage"]["prompt_tokens"] == 400_000


class _TrackedSseStream:
    def __init__(self, events: list[str]) -> None:
        self._events = events
        self.closed = False
        self._index = 0

    def __aiter__(self) -> _TrackedSseStream:
        return self

    async def __anext__(self) -> str:
        if self._index >= len(self._events):
            raise StopAsyncIteration
        event = self._events[self._index]
        self._index += 1
        return event

    async def aclose(self) -> None:
        self.closed = True


async def test_stream_responses_fallback_closes_source_on_context_limit() -> None:
    failed = (
        'data: {"type":"response.failed","response":{"id":"resp_ctx","error":'
        '{"message":"Input token limit exceeded","type":"invalid_request_error",'
        '"code":"context_length_exceeded","param":"input"}}}\n\n'
    )
    leftover = 'data: {"type":"response.output_text.delta","delta":"should not leak"}\n\n'
    source = _TrackedSseStream(
        [
            'data: {"type":"response.created","response":{"id":"resp_ctx"}}\n\n',
            failed,
            leftover,
        ]
    )

    events = [
        event
        async for event in stream_responses_with_cursor_context_limit_fallback(
            source,
            model="gpt-5.6-sol",
            source="test",
        )
    ]

    assert source.closed is True
    assert source._index == 2
    assert any("1000000" in event for event in events)
    assert not any("should not leak" in event for event in events)


async def test_chat_bytes_fallback_settles_upstream_on_context_limit() -> None:
    """The chat wrapper must close the sidecar stream it stops consuming.

    The sidecar stream iterators release the API-key usage reservation in a
    ``finally``. This wrapper returns early once it rewrites a context-limit
    error into a synthetic success, and ``async for`` does not close the
    iterator it consumes, so without an explicit close that release would only
    run at a later event-loop finalization - after the response completed, with
    the caller's quota still held in the meantime.
    """

    settled: list[str] = []

    async def settling_stream():
        try:
            yield b'data: {"id":"c1","object":"chat.completion.chunk","choices":[{"delta":{"content":"hi"}}]}\n\n'
            yield (b'data: {"error":{"code":"context_length_exceeded","message":"Input token limit exceeded"}}\n\n')
            yield b'data: {"id":"c2","object":"chat.completion.chunk","choices":[]}\n\n'
        finally:
            settled.append("released")

    chunks = [
        chunk
        async for chunk in stream_bytes_with_cursor_usage_fallback(
            settling_stream(),
            _payload("deepseek/deepseek-chat"),
            source="test",
        )
    ]

    body = b"".join(chunks)
    assert b'"error"' not in body
    assert str(CURSOR_CONTEXT_LIMIT_SYNTHETIC_USAGE_TOKENS).encode() in body
    # Settled as part of this request, not deferred to a later GC pass.
    assert settled == ["released"]


async def test_chat_text_fallback_settles_upstream_on_context_limit() -> None:
    """Same contract for the ``str`` variant used by the native chat path."""

    settled: list[str] = []

    async def settling_stream():
        try:
            yield 'data: {"id":"c1","object":"chat.completion.chunk","choices":[{"delta":{"content":"hi"}}]}\n\n'
            yield 'data: {"error":{"code":"context_length_exceeded","message":"Input token limit exceeded"}}\n\n'
            yield 'data: {"id":"c2","object":"chat.completion.chunk","choices":[]}\n\n'
        finally:
            settled.append("released")

    events = [
        event
        async for event in stream_with_cursor_usage_fallback(
            settling_stream(),
            _payload("deepseek/deepseek-chat"),
        )
    ]

    assert not any('"error"' in event for event in events)
    assert settled == ["released"]


async def test_production_chat_chunk_chain_settles_upstream_on_context_limit() -> None:
    """The real native-chat wrapper chain must settle, not just a bare generator.

    `/v1/chat/completions` stacks `stream_chat_chunks` over the reservation-owning
    service stream and only then applies the Cursor rewrite. Each intermediate
    layer is an `async for`, which does not close what it consumes, so a close
    that stops at the outermost wrapper would still strand the reservation. This
    exercises that production stacking rather than handing the wrapper a settling
    generator directly.
    """

    settled: list[str] = []

    async def reservation_owning_stream():
        try:
            yield 'data: {"type":"response.output_text.delta","delta":"hi"}\n\n'
            yield (
                'data: {"type":"response.failed","response":{"id":"r","error":'
                '{"message":"Input token limit exceeded","type":"invalid_request_error",'
                '"code":"context_length_exceeded","param":"input"}}}\n\n'
            )
            yield 'data: {"type":"response.output_text.delta","delta":"leak"}\n\n'
        finally:
            settled.append("released")

    # Keep a reference to every layer for the whole test, exactly as the server
    # does while the StreamingResponse task is alive. Without this, CPython
    # refcounting finalizes an abandoned generator the moment the last
    # reference drops, which would settle the reservation by accident and hide
    # the defect - so a test that let the layers go out of scope would pass
    # even with close propagation removed.
    owner = reservation_owning_stream()
    chained = stream_chat_chunks(
        owner,
        model="deepseek/deepseek-chat",
        include_usage=True,
    )

    events = [
        event
        async for event in stream_with_cursor_usage_fallback(
            chained,
            _payload("deepseek/deepseek-chat"),
        )
    ]

    assert not any("leak" in event for event in events)
    # Settled through the full production chain, within the request.
    assert settled == ["released"]

    # Still referenced, still settled exactly once - not stranded awaiting a
    # finalization that a live response task would never let happen.
    await asyncio.sleep(0.05)
    assert settled == ["released"]
    assert owner is not None


async def test_context_limit_close_settles_when_cancelled_mid_settlement() -> None:
    """A client disconnect arriving *during* settlement must not interrupt it.

    This is the case the shield exists for. The rewrite returns early and begins
    closing the reservation-owning stream; settlement is not instantaneous (it
    awaits real database work), so a disconnect can land while that close is
    in flight. Awaiting the close unshielded lets the cancellation tear
    settlement apart partway, stranding the reservation on the very path where
    a leak is most likely - so the close defers cancellation instead.
    """

    settled: list[str] = []

    async def reservation_owning_stream():
        try:
            yield b'data: {"id":"c","object":"chat.completion.chunk","choices":[{"delta":{"content":"hi"}}]}\n\n'
            yield (b'data: {"error":{"code":"context_length_exceeded","message":"Input token limit exceeded"}}\n\n')
            yield b'data: {"id":"c2","object":"chat.completion.chunk","choices":[]}\n\n'
        finally:
            # Settlement is awaited work, not a bare append - a single `await`
            # here is what makes it interruptible.
            for _ in range(5):
                await asyncio.sleep(0.02)
            settled.append("released")

    # Held for the duration, as the live response task holds it: otherwise
    # refcount finalization would settle the reservation by itself and this
    # would pass even with the close removed.
    owner = reservation_owning_stream()
    wrapper = stream_bytes_with_cursor_usage_fallback(
        owner,
        _payload("deepseek/deepseek-chat"),
        source="test",
    )

    async def consume() -> None:
        async for _ in wrapper:
            pass

    task = asyncio.create_task(consume())
    # Let the rewrite fire and reach the close, then disconnect mid-settlement.
    await asyncio.sleep(0.03)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    # Enough time for the settlement to finish if it was allowed to.
    await asyncio.sleep(0.5)

    assert settled == ["released"]
    assert owner is not None


async def test_aclose_stream_completes_the_close_then_re_raises_the_cancellation() -> None:
    """The shielded close must defer the caller's cancellation, never swallow it.

    Absorbing the cancellation so the upstream `finally` can settle is the whole
    point; returning normally afterwards is not. A request cancelled mid-close
    would then look completed to everything below it, which is the same defect
    that was already fixed once in the sibling settlement helper.
    """

    closed: list[str] = []

    class _SlowClosingStream:
        def __aiter__(self) -> _SlowClosingStream:
            return self

        async def __anext__(self) -> str:
            raise StopAsyncIteration

        async def aclose(self) -> None:
            # Closing awaits real work, as the sidecar settlement does.
            await asyncio.sleep(0.05)
            closed.append("closed")

    async def caller() -> str:
        await aclose_stream(_SlowClosingStream())
        return "completed-normally"

    task = asyncio.create_task(caller())
    await asyncio.sleep(0.01)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    # Both halves of the contract: the close ran to completion...
    assert closed == ["closed"]
    # ...and the caller did not finish normally (asserted by pytest.raises).


async def test_aclose_stream_without_cancellation_returns_normally() -> None:
    """Control: with no cancellation, nothing is deferred and nothing is raised."""

    closed: list[str] = []

    class _Stream:
        def __aiter__(self) -> _Stream:
            return self

        async def __anext__(self) -> str:
            raise StopAsyncIteration

        async def aclose(self) -> None:
            closed.append("closed")

    await aclose_stream(_Stream())
    assert closed == ["closed"]


async def test_aclose_stream_skips_iterators_without_aclose() -> None:
    """A plain class-based iterator has nothing to close and must not raise."""

    class _NoClose:
        def __aiter__(self) -> _NoClose:
            return self

        async def __anext__(self) -> str:
            raise StopAsyncIteration

    await aclose_stream(_NoClose())
