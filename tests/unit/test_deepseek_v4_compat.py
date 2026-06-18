from __future__ import annotations

import json

import pytest

from app.core.types import JsonValue
from app.modules.proxy.deepseek_v4_compat import (
    DeepSeekReasoningCache,
    DeepSeekReasoningRecorder,
    DeepSeekReasoningStreamObserver,
    api_key_hash,
    capture_reasoning_from_response,
    deepseek_v4_family_token,
    is_deepseek_v4_model,
    reasoning_cache_key,
    reinject_reasoning_into_sidecar_body,
)

# --------------------------------------------------------------------------
# Detection
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("deepseek-v4-pro", "deepseek-v4-pro"),
        ("deepseek-v4-flash", "deepseek-v4-flash"),
        ("DeepSeek-V4-Flash", "deepseek-v4-flash"),
        ("deepseek_v4_flash", "deepseek-v4-flash"),
        ("oc/deepseek-v4-flash-free", "deepseek-v4-flash"),
        ("openrouter/deepseek/deepseek-v4-pro", "deepseek-v4-pro"),
        ("opencode/deepseek-v4-flash-free", "deepseek-v4-flash"),
    ],
)
def test_family_token_matches(model: str, expected: str) -> None:
    assert deepseek_v4_family_token(model) == expected
    assert is_deepseek_v4_model(model) is True


@pytest.mark.parametrize(
    "model",
    [
        "gpt-5.2",
        "claude-sonnet-4-5",
        "oc/minimax-m3-free",
        "deepseek-v3",
        "deepseek-v4",  # bare family without pro/flash is out of scope
        "",
    ],
)
def test_non_deepseek_models_not_matched(model: str) -> None:
    assert deepseek_v4_family_token(model) is None
    assert is_deepseek_v4_model(model) is False


def test_alias_match_keys_by_alias_value() -> None:
    aliases = frozenset({"my-custom-ds4"})
    assert deepseek_v4_family_token("my-custom-ds4", aliases) == "my-custom-ds4"
    assert deepseek_v4_family_token("my-custom-ds4") is None


def test_alias_embedding_family_token_keys_by_family() -> None:
    aliases = frozenset({"vendor/deepseek-v4-pro-turbo"})
    assert deepseek_v4_family_token("vendor/deepseek-v4-pro-turbo", aliases) == "deepseek-v4-pro"


# --------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------


def test_cache_evicts_by_size() -> None:
    cache = DeepSeekReasoningCache(maxsize=2, ttl_seconds=1000)
    cache.set("a", "ra")
    cache.set("b", "rb")
    cache.set("c", "rc")
    assert cache.get("a") is None  # evicted (oldest)
    assert cache.get("b") == "rb"
    assert cache.get("c") == "rc"


def test_cache_expires_by_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.modules.proxy.deepseek_v4_compat as mod

    now = [1000.0]
    monkeypatch.setattr(mod.time, "monotonic", lambda: now[0])
    cache = DeepSeekReasoningCache(maxsize=10, ttl_seconds=30)
    cache.set("k", "r")
    now[0] = 1029.0
    assert cache.get("k") == "r"
    now[0] = 1031.0
    assert cache.get("k") is None


def test_cache_hit_moves_to_mru() -> None:
    cache = DeepSeekReasoningCache(maxsize=2, ttl_seconds=1000)
    cache.set("a", "ra")
    cache.set("b", "rb")
    assert cache.get("a") == "ra"  # makes 'a' MRU
    cache.set("c", "rc")  # evicts 'b'
    assert cache.get("b") is None
    assert cache.get("a") == "ra"
    assert cache.get("c") == "rc"


def test_cache_ignores_empty_reasoning() -> None:
    cache = DeepSeekReasoningCache()
    cache.set("k", "")
    assert cache.get("k") is None


# --------------------------------------------------------------------------
# Cache key strategy
# --------------------------------------------------------------------------


def _assistant_turn(reasoning: str | None = None) -> dict[str, JsonValue]:
    msg: dict[str, JsonValue] = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "get_weather", "arguments": '{"city":"Paris"}'}}
        ],
    }
    if reasoning is not None:
        msg["reasoning_content"] = reasoning
    return msg


def test_store_key_matches_lookup_key_ignoring_reasoning() -> None:
    outgoing = [{"role": "user", "content": "weather in Paris?"}]
    # Store side: outgoing + synthesized assistant turn (with reasoning present)
    store_prefix = [*outgoing, _assistant_turn(reasoning="because Paris")]
    # Lookup side: a later request where the assistant turn lacks reasoning
    lookup_prefix = [*outgoing, _assistant_turn(reasoning=None)]
    store_key = reasoning_cache_key(
        messages=store_prefix, provider="omniroute", model_family="deepseek-v4-flash", api_key_digest="d"
    )
    lookup_key = reasoning_cache_key(
        messages=lookup_prefix, provider="omniroute", model_family="deepseek-v4-flash", api_key_digest="d"
    )
    assert store_key == lookup_key


def test_keys_differ_across_provider_family_and_api_key() -> None:
    prefix = [{"role": "user", "content": "hi"}, _assistant_turn()]
    base = reasoning_cache_key(
        messages=prefix, provider="omniroute", model_family="deepseek-v4-flash", api_key_digest="d1"
    )
    assert base != reasoning_cache_key(
        messages=prefix, provider="openrouter", model_family="deepseek-v4-flash", api_key_digest="d1"
    )
    assert base != reasoning_cache_key(
        messages=prefix, provider="omniroute", model_family="deepseek-v4-pro", api_key_digest="d1"
    )
    assert base != reasoning_cache_key(
        messages=prefix, provider="omniroute", model_family="deepseek-v4-flash", api_key_digest="d2"
    )


def test_api_key_hash_distinguishes_none_and_values() -> None:
    assert api_key_hash(None) != api_key_hash("abc")
    assert api_key_hash("abc") == api_key_hash("abc")


# --------------------------------------------------------------------------
# Request re-injection
# --------------------------------------------------------------------------


def _seed_cache(cache: DeepSeekReasoningCache, *, outgoing: list[JsonValue], reasoning: str, **kwargs: str) -> None:
    prefix = [*outgoing, _assistant_turn(reasoning=reasoning)]
    key = reasoning_cache_key(messages=prefix, **kwargs)  # type: ignore[arg-type]
    cache.set(key, reasoning)


def test_reinject_patches_assistant_tool_call_message() -> None:
    cache = DeepSeekReasoningCache()
    outgoing = [{"role": "user", "content": "weather in Paris?"}]
    _seed_cache(
        cache,
        outgoing=outgoing,
        reasoning="because Paris",
        provider="omniroute",
        model_family="deepseek-v4-flash",
        api_key_digest="d",
    )
    body: dict[str, JsonValue] = {
        "model": "oc/deepseek-v4-flash-free",
        "messages": [
            {"role": "user", "content": "weather in Paris?"},
            _assistant_turn(reasoning=None),
            {"role": "tool", "tool_call_id": "call_1", "content": '{"temp_c":18}'},
        ],
    }
    reinject_reasoning_into_sidecar_body(
        body, provider="omniroute", model_family="deepseek-v4-flash", api_key_digest="d", cache=cache
    )
    messages = body["messages"]
    assert isinstance(messages, list)
    assert messages[1]["reasoning_content"] == "because Paris"


def test_reinject_missing_cache_leaves_body_unchanged() -> None:
    cache = DeepSeekReasoningCache()
    body: dict[str, JsonValue] = {
        "messages": [
            {"role": "user", "content": "weather in Paris?"},
            _assistant_turn(reasoning=None),
            {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
        ]
    }
    before = json.dumps(body, sort_keys=True)
    reinject_reasoning_into_sidecar_body(
        body, provider="omniroute", model_family="deepseek-v4-flash", api_key_digest="d", cache=cache
    )
    assert json.dumps(body, sort_keys=True) == before


def test_reinject_does_not_overwrite_existing_reasoning() -> None:
    cache = DeepSeekReasoningCache()
    outgoing = [{"role": "user", "content": "hi"}]
    _seed_cache(
        cache,
        outgoing=outgoing,
        reasoning="cached",
        provider="omniroute",
        model_family="deepseek-v4-flash",
        api_key_digest="d",
    )
    body: dict[str, JsonValue] = {
        "messages": [{"role": "user", "content": "hi"}, _assistant_turn(reasoning="client-sent")]
    }
    reinject_reasoning_into_sidecar_body(
        body, provider="omniroute", model_family="deepseek-v4-flash", api_key_digest="d", cache=cache
    )
    messages = body["messages"]
    assert isinstance(messages, list)
    assert messages[1]["reasoning_content"] == "client-sent"


# --------------------------------------------------------------------------
# Non-streaming capture + round trip
# --------------------------------------------------------------------------


def test_non_streaming_capture_and_reinject_round_trip() -> None:
    cache = DeepSeekReasoningCache()
    outgoing = [{"role": "user", "content": "weather in Paris?"}]
    response_body: dict[str, JsonValue] = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "reasoning_content": "thinking about Paris",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "get_weather", "arguments": '{"city":"Paris"}'},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ]
    }
    capture_reasoning_from_response(
        response_body,
        outgoing_messages=outgoing,
        provider="omniroute",
        model_family="deepseek-v4-flash",
        api_key_digest="d",
        cache=cache,
    )
    # Next turn: client echoes assistant tool_calls without reasoning + tool result
    body: dict[str, JsonValue] = {
        "messages": [
            {"role": "user", "content": "weather in Paris?"},
            _assistant_turn(reasoning=None),
            {"role": "tool", "tool_call_id": "call_1", "content": '{"temp_c":18}'},
        ]
    }
    reinject_reasoning_into_sidecar_body(
        body, provider="omniroute", model_family="deepseek-v4-flash", api_key_digest="d", cache=cache
    )
    messages = body["messages"]
    assert isinstance(messages, list)
    assert messages[1]["reasoning_content"] == "thinking about Paris"


def test_non_streaming_capture_noop_without_tool_calls() -> None:
    cache = DeepSeekReasoningCache()
    response_body: dict[str, JsonValue] = {
        "choices": [{"message": {"role": "assistant", "content": "hi", "reasoning_content": "r"}}]
    }
    capture_reasoning_from_response(
        response_body,
        outgoing_messages=[{"role": "user", "content": "hi"}],
        provider="omniroute",
        model_family="deepseek-v4-flash",
        api_key_digest="d",
        cache=cache,
    )
    # Nothing cached -> re-injection finds nothing
    body: dict[str, JsonValue] = {"messages": [{"role": "user", "content": "hi"}, _assistant_turn()]}
    before = json.dumps(body, sort_keys=True)
    reinject_reasoning_into_sidecar_body(
        body, provider="omniroute", model_family="deepseek-v4-flash", api_key_digest="d", cache=cache
    )
    assert json.dumps(body, sort_keys=True) == before


# --------------------------------------------------------------------------
# Isolation across api key / provider / family
# --------------------------------------------------------------------------


def test_isolation_blocks_cross_context_reuse() -> None:
    cache = DeepSeekReasoningCache()
    outgoing = [{"role": "user", "content": "weather in Paris?"}]
    _seed_cache(
        cache,
        outgoing=outgoing,
        reasoning="k1-reasoning",
        provider="omniroute",
        model_family="deepseek-v4-flash",
        api_key_digest=api_key_hash("K1"),
    )

    def reinject_with(provider: str, family: str, digest: str) -> dict[str, JsonValue]:
        body: dict[str, JsonValue] = {
            "messages": [
                {"role": "user", "content": "weather in Paris?"},
                _assistant_turn(reasoning=None),
            ]
        }
        reinject_reasoning_into_sidecar_body(
            body, provider=provider, model_family=family, api_key_digest=digest, cache=cache
        )
        messages = body["messages"]
        assert isinstance(messages, list)
        return messages[1]

    # Same context -> repaired
    repaired = reinject_with("omniroute", "deepseek-v4-flash", api_key_hash("K1"))
    assert repaired.get("reasoning_content") == "k1-reasoning"
    # Different api key -> not repaired
    assert "reasoning_content" not in reinject_with("omniroute", "deepseek-v4-flash", api_key_hash("K2"))
    # Different provider -> not repaired
    assert "reasoning_content" not in reinject_with("openrouter", "deepseek-v4-flash", api_key_hash("K1"))
    # Different family -> not repaired
    assert "reasoning_content" not in reinject_with("omniroute", "deepseek-v4-pro", api_key_hash("K1"))


# --------------------------------------------------------------------------
# Streaming observer
# --------------------------------------------------------------------------


def _sse(obj: dict[str, JsonValue] | str) -> bytes:
    if obj == "[DONE]":
        return b"data: [DONE]\n\n"
    return f"data: {json.dumps(obj, separators=(',', ':'))}\n\n".encode("utf-8")


def _chunk(
    *,
    reasoning: str | None = None,
    content: str | None = None,
    tool_call: dict | None = None,
    finish: str | None = None,
) -> dict[str, JsonValue]:
    delta: dict[str, JsonValue] = {}
    if reasoning is not None:
        delta["reasoning_content"] = reasoning
    if content is not None:
        delta["content"] = content
    if tool_call is not None:
        delta["tool_calls"] = [tool_call]
    return {
        "object": "chat.completion.chunk",
        "model": "oc/deepseek-v4-flash-free",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }


async def _collect(observer_stream) -> list[bytes]:
    out: list[bytes] = []
    async for chunk in observer_stream:
        out.append(chunk)
    return out


async def _make_stream(chunks: list[bytes]):
    for c in chunks:
        yield c


def _tool_call_finish_stream() -> list[bytes]:
    return [
        _sse(_chunk(reasoning="step 1 ")),
        _sse(_chunk(reasoning="step 2")),
        _sse(
            _chunk(
                tool_call={
                    "index": 0,
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "get_weather", "arguments": '{"city":'},
                }
            )
        ),
        _sse(_chunk(tool_call={"index": 0, "function": {"arguments": '"Paris"}'}})),
        _sse(_chunk(finish="tool_calls")),
        _sse("[DONE]"),
    ]


@pytest.mark.asyncio
async def test_stream_accumulates_and_commits_on_clean_tool_call_finish() -> None:
    cache = DeepSeekReasoningCache()
    outgoing = [{"role": "user", "content": "weather in Paris?"}]
    chunks = _tool_call_finish_stream()
    observer = DeepSeekReasoningStreamObserver(
        _make_stream(chunks),
        outgoing_messages=outgoing,
        provider="omniroute",
        model_family="deepseek-v4-flash",
        api_key_digest="d",
        cache=cache,
    )
    forwarded = await _collect(observer.__aiter__())
    # Pass-through: every chunk forwarded unchanged and in order
    assert forwarded == chunks
    # Reasoning committed; reproduce the key the next request would compute
    body: dict[str, JsonValue] = {
        "messages": [
            {"role": "user", "content": "weather in Paris?"},
            _assistant_turn(reasoning=None),
            {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
        ]
    }
    reinject_reasoning_into_sidecar_body(
        body, provider="omniroute", model_family="deepseek-v4-flash", api_key_digest="d", cache=cache
    )
    messages = body["messages"]
    assert isinstance(messages, list)
    assert messages[1]["reasoning_content"] == "step 1 step 2"


def test_recorder_observes_raw_chunks_and_commits() -> None:
    # CLIProxyAPI path feeds raw (pre tool-name-reversal) chunks directly.
    cache = DeepSeekReasoningCache()
    outgoing = [{"role": "user", "content": "weather in Paris?"}]
    recorder = DeepSeekReasoningRecorder(
        outgoing_messages=outgoing,
        provider="claude",
        model_family="deepseek-v4-flash",
        api_key_digest="d",
        cache=cache,
    )
    for chunk in _tool_call_finish_stream():
        recorder.record(chunk)
    recorder.commit()
    body: dict[str, JsonValue] = {
        "messages": [
            {"role": "user", "content": "weather in Paris?"},
            _assistant_turn(reasoning=None),
            {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
        ]
    }
    reinject_reasoning_into_sidecar_body(
        body, provider="claude", model_family="deepseek-v4-flash", api_key_digest="d", cache=cache
    )
    messages = body["messages"]
    assert isinstance(messages, list)
    assert messages[1]["reasoning_content"] == "step 1 step 2"


def test_recorder_does_not_commit_on_interrupt() -> None:
    cache = DeepSeekReasoningCache()
    recorder = DeepSeekReasoningRecorder(
        outgoing_messages=[{"role": "user", "content": "hi"}],
        provider="claude",
        model_family="deepseek-v4-flash",
        api_key_digest="d",
        cache=cache,
    )
    # Reasoning + tool-call finish but no [DONE] (interrupted upstream).
    recorder.record(_sse(_chunk(reasoning="partial")))
    recorder.record(
        _sse(_chunk(tool_call={"index": 0, "id": "c", "function": {"name": "f", "arguments": "{}"}}))
    )
    recorder.record(_sse(_chunk(finish="tool_calls")))
    recorder.commit()
    # No [DONE] => no commit => re-injection finds nothing and leaves body intact.
    body: dict[str, JsonValue] = {
        "messages": [
            {"role": "user", "content": "hi"},
            _assistant_turn(reasoning=None),
            {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
        ]
    }
    reinject_reasoning_into_sidecar_body(
        body, provider="claude", model_family="deepseek-v4-flash", api_key_digest="d", cache=cache
    )
    messages = body["messages"]
    assert isinstance(messages, list)
    assert "reasoning_content" not in messages[1]


@pytest.mark.asyncio
async def test_stream_does_not_commit_without_done() -> None:
    cache = DeepSeekReasoningCache()
    chunks = [
        _sse(_chunk(reasoning="partial ")),
        _sse(_chunk(tool_call={"index": 0, "id": "call_1", "function": {"name": "f", "arguments": "{}"}})),
        _sse(_chunk(finish="tool_calls")),
        # No [DONE] -> interrupted
    ]
    observer = DeepSeekReasoningStreamObserver(
        _make_stream(chunks),
        outgoing_messages=[{"role": "user", "content": "hi"}],
        provider="omniroute",
        model_family="deepseek-v4-flash",
        api_key_digest="d",
        cache=cache,
    )
    forwarded = await _collect(observer.__aiter__())
    assert forwarded == chunks
    body: dict[str, JsonValue] = {"messages": [{"role": "user", "content": "hi"}, _assistant_turn(reasoning=None)]}
    reinject_reasoning_into_sidecar_body(
        body, provider="omniroute", model_family="deepseek-v4-flash", api_key_digest="d", cache=cache
    )
    messages = body["messages"]
    assert isinstance(messages, list)
    assert "reasoning_content" not in messages[1]


@pytest.mark.asyncio
async def test_stream_does_not_commit_without_tool_call_finish() -> None:
    cache = DeepSeekReasoningCache()
    chunks = [
        _sse(_chunk(reasoning="thinking", content="hello")),
        _sse(_chunk(finish="stop")),
        _sse("[DONE]"),
    ]
    observer = DeepSeekReasoningStreamObserver(
        _make_stream(chunks),
        outgoing_messages=[{"role": "user", "content": "hi"}],
        provider="omniroute",
        model_family="deepseek-v4-flash",
        api_key_digest="d",
        cache=cache,
    )
    forwarded = await _collect(observer.__aiter__())
    assert forwarded == chunks
    body: dict[str, JsonValue] = {"messages": [{"role": "user", "content": "hi"}, _assistant_turn(reasoning=None)]}
    reinject_reasoning_into_sidecar_body(
        body, provider="omniroute", model_family="deepseek-v4-flash", api_key_digest="d", cache=cache
    )
    messages = body["messages"]
    assert isinstance(messages, list)
    assert "reasoning_content" not in messages[1]


@pytest.mark.asyncio
async def test_stream_forwards_error_chunks_unchanged() -> None:
    cache = DeepSeekReasoningCache()
    error_chunk = b'data: {"error":{"message":"boom","code":"x"}}\n\n'
    chunks = [_sse(_chunk(reasoning="r")), error_chunk, _sse("[DONE]")]
    observer = DeepSeekReasoningStreamObserver(
        _make_stream(chunks),
        outgoing_messages=[{"role": "user", "content": "hi"}],
        provider="omniroute",
        model_family="deepseek-v4-flash",
        api_key_digest="d",
        cache=cache,
    )
    forwarded = await _collect(observer.__aiter__())
    assert forwarded == chunks


# --------------------------------------------------------------------------
# Multi-round chain (DeepSeek requires the complete reasoning chain)
# --------------------------------------------------------------------------


def _assistant_turn_n(call_id: str, name: str, args: str, reasoning: str | None = None) -> dict[str, JsonValue]:
    msg: dict[str, JsonValue] = {
        "role": "assistant",
        "content": None,
        "tool_calls": [{"id": call_id, "type": "function", "function": {"name": name, "arguments": args}}],
    }
    if reasoning is not None:
        msg["reasoning_content"] = reasoning
    return msg


def test_multi_round_chain_reinjects_every_prior_assistant_turn() -> None:
    cache = DeepSeekReasoningCache()
    kw = {"provider": "omniroute", "model_family": "deepseek-v4-flash", "api_key_digest": "d"}

    # --- Round 1 request: just the user turn ---
    round1_outgoing: list[JsonValue] = [{"role": "user", "content": "weather in Paris?"}]
    round1_response: dict[str, JsonValue] = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "reasoning_content": "R1: need weather",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "get_weather", "arguments": '{"city":"Paris"}'},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ]
    }
    capture_reasoning_from_response(round1_response, outgoing_messages=round1_outgoing, cache=cache, **kw)

    # --- Round 2 request: user, assistant_tc_1 (no reasoning from Cursor), tool_1, ... ---
    round2_messages: list[JsonValue] = [
        {"role": "user", "content": "weather in Paris?"},
        _assistant_turn_n("call_1", "get_weather", '{"city":"Paris"}'),
        {"role": "tool", "tool_call_id": "call_1", "content": '{"temp_c":18}'},
    ]
    round2_body: dict[str, JsonValue] = {"messages": [dict(m) for m in round2_messages]}
    # Snapshot outgoing BEFORE reinjection (as resolve_scope does)
    round2_outgoing = [dict(m) for m in round2_messages]
    reinject_reasoning_into_sidecar_body(round2_body, cache=cache, **kw)
    msgs2 = round2_body["messages"]
    assert isinstance(msgs2, list)
    assert msgs2[1]["reasoning_content"] == "R1: need weather"

    # Round 2 upstream returns a SECOND assistant tool-call turn with new reasoning
    round2_response: dict[str, JsonValue] = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "reasoning_content": "R2: convert units",
                    "tool_calls": [
                        {"id": "call_2", "type": "function", "function": {"name": "to_f", "arguments": '{"c":18}'}}
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ]
    }
    capture_reasoning_from_response(round2_response, outgoing_messages=round2_outgoing, cache=cache, **kw)

    # --- Round 3 request: full history, BOTH assistant turns lack reasoning ---
    round3_body: dict[str, JsonValue] = {
        "messages": [
            {"role": "user", "content": "weather in Paris?"},
            _assistant_turn_n("call_1", "get_weather", '{"city":"Paris"}'),
            {"role": "tool", "tool_call_id": "call_1", "content": '{"temp_c":18}'},
            _assistant_turn_n("call_2", "to_f", '{"c":18}'),
            {"role": "tool", "tool_call_id": "call_2", "content": '{"f":64}'},
        ]
    }
    reinject_reasoning_into_sidecar_body(round3_body, cache=cache, **kw)
    msgs3 = round3_body["messages"]
    assert isinstance(msgs3, list)
    # The complete multi-round reasoning chain is restored on BOTH assistant turns.
    assert msgs3[1]["reasoning_content"] == "R1: need weather"
    assert msgs3[3]["reasoning_content"] == "R2: convert units"
