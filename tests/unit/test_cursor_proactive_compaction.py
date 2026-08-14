"""GPT-5.6 Cursor proactive compaction (success-path usage rewrite)."""

from __future__ import annotations

import json

from app.core.openai.chat_requests import ChatCompletionsRequest
from app.core.openai.chat_responses import (
    ChatCompletion,
    ChatCompletionChoice,
    ChatCompletionMessage,
    ChatCompletionUsage,
)
from app.modules.proxy.cursor_chat_compat import (
    CURSOR_CONTEXT_LIMIT_SYNTHETIC_USAGE_TOKENS,
    CursorChatSseCompatRewriter,
    apply_cursor_usage_fallback,
    apply_cursor_usage_fallback_to_response,
    needs_cursor_proactive_compaction,
    stream_responses_with_cursor_context_limit_fallback,
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
