from __future__ import annotations

from app.core.clients.claude_sidecar import ClaudeSidecarConfig
from app.core.openai.chat_requests import ChatCompletionsRequest
from app.modules.proxy.claude_sidecar_dispatch import (
    _SIDECAR_MESSAGE_CONTINUATION,
    _SseUsageDecoder,
    build_sidecar_chat_payload,
    ensure_stream_usage_requested,
    extract_usage,
    is_sidecar_model,
    sanitize_sidecar_chat_messages,
    sanitize_sidecar_chat_tool_ids,
    sidecar_wire_model,
)


def _config(*, enabled: bool = True, prefixes: tuple[str, ...] = ("claude", "anthropic")) -> ClaudeSidecarConfig:
    return ClaudeSidecarConfig(
        enabled=enabled,
        base_url="http://127.0.0.1:8317",
        api_key="key",
        model_prefixes=prefixes,
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
    )


def test_is_sidecar_model_respects_enabled_prefix_and_case() -> None:
    enabled = _config()
    disabled = _config(enabled=False)

    assert is_sidecar_model("claude-sonnet-4-5", enabled) is True
    assert is_sidecar_model("Claude-Sonnet-4-5", enabled) is True
    assert is_sidecar_model("anthropic/claude-sonnet", enabled) is True
    assert is_sidecar_model("gpt-5.4", enabled) is False
    assert is_sidecar_model("claude-sonnet-4-5", disabled) is False


def test_is_sidecar_model_treats_dash_and_underscore_alias_prefixes_as_equivalent() -> None:
    enabled = _config(prefixes=("cp-",))

    assert is_sidecar_model("cp-claude-fable-5", enabled) is True
    assert is_sidecar_model("cp_claude-fable-5", enabled) is True


def test_sidecar_wire_model_strips_custom_alias_prefix_only() -> None:
    alias_config = _config(prefixes=("cp-",))
    claude_config = _config(prefixes=("claude",))

    assert sidecar_wire_model("cp-claude-fable-5", alias_config) == "claude-fable-5"
    assert sidecar_wire_model("cp_claude-fable-5", alias_config) == "claude-fable-5"
    assert sidecar_wire_model("claude-fable-5", claude_config) == "claude-fable-5"


def test_build_sidecar_chat_payload_preserves_extra_fields_and_effective_model() -> None:
    request = ChatCompletionsRequest.model_validate(
        {
            "model": "gpt-5.4",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
            "temperature": 0.2,
            "custom_flag": "kept",
        }
    )

    payload = build_sidecar_chat_payload(request, "claude-sonnet-4-5", _config())

    assert payload.body["model"] == "claude-sonnet-4-5"
    assert payload.body["messages"] == [{"role": "user", "content": "hi"}]
    assert payload.body["custom_flag"] == "kept"


def test_build_sidecar_chat_payload_sends_unprefixed_model_for_custom_alias() -> None:
    request = ChatCompletionsRequest.model_validate(
        {
            "model": "cp_claude-fable-5",
            "messages": [{"role": "user", "content": "hi"}],
        }
    )

    payload = build_sidecar_chat_payload(request, "cp_claude-fable-5", _config(prefixes=("cp-",)))

    assert payload.body["model"] == "claude-fable-5"


def test_build_sidecar_chat_payload_sanitizes_assistant_tool_use_ids() -> None:
    request = ChatCompletionsRequest.model_validate(
        {
            "model": "cp-claude-fable-5",
            "messages": [
                {"role": "user", "content": "hi"},
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "running tool"},
                        {
                            "type": "tool_use",
                            "id": "call:abc.def",
                            "name": "Shell",
                            "input": {"command": "pwd"},
                        },
                    ],
                },
            ],
        }
    )

    payload = build_sidecar_chat_payload(request, "cp-claude-fable-5", _config(prefixes=("cp-",)))

    tool_use = payload.body["messages"][1]["content"][1]
    assert tool_use["id"] == "call_abc_def"
    assert tool_use["name"] == "Bash"
    assert payload.reverse_tool_names == {"Bash": "Shell"}


def test_sanitize_sidecar_chat_tool_ids_keeps_tool_result_references_consistent() -> None:
    body = {
        "model": "claude-fable-5",
        "messages": [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "call:abc.def",
                        "name": "shell",
                        "input": {"command": "pwd"},
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "call:abc.def",
                        "content": "/tmp",
                    }
                ],
            },
        ],
    }

    sanitize_sidecar_chat_tool_ids(body)

    tool_use = body["messages"][0]["content"][0]
    tool_result = body["messages"][1]["content"][0]
    assert tool_use["id"] == "call_abc_def"
    assert tool_result["tool_use_id"] == "call_abc_def"


def test_build_sidecar_chat_payload_appends_user_continuation_after_trailing_assistant() -> None:
    request = ChatCompletionsRequest.model_validate(
        {
            "model": "claude-sonnet-4-5",
            "messages": [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "partial reply"},
            ],
        }
    )

    payload = build_sidecar_chat_payload(request, "claude-sonnet-4-5", _config())

    assert payload.body["messages"][-2] == {"role": "assistant", "content": "partial reply"}
    assert payload.body["messages"][-1] == {
        "role": "user",
        "content": _SIDECAR_MESSAGE_CONTINUATION,
    }


def test_build_sidecar_chat_payload_appends_user_continuation_after_assistant_tool_calls() -> None:
    request = ChatCompletionsRequest.model_validate(
        {
            "model": "claude-sonnet-4-5",
            "messages": [
                {"role": "user", "content": "run pwd"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "Shell", "arguments": "{}"},
                        }
                    ],
                },
            ],
        }
    )

    payload = build_sidecar_chat_payload(request, "claude-sonnet-4-5", _config())

    assert payload.body["messages"][-1] == {
        "role": "user",
        "content": _SIDECAR_MESSAGE_CONTINUATION,
    }


def test_sanitize_sidecar_chat_messages_drops_empty_messages() -> None:
    body = {
        "messages": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": ""},
            {"role": "user", "content": "   "},
            {"role": "assistant", "content": [{"type": "text", "text": "ok"}]},
        ]
    }

    sanitize_sidecar_chat_messages(body)

    assert body["messages"] == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": [{"type": "text", "text": "ok"}]},
        {"role": "user", "content": _SIDECAR_MESSAGE_CONTINUATION},
    ]


def test_sanitize_sidecar_chat_messages_drops_orphan_tool_messages() -> None:
    body = {
        "messages": [
            {"role": "user", "content": "hi"},
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
            {"role": "tool", "tool_call_id": "call_2", "content": "orphan"},
            {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
        ]
    }

    sanitize_sidecar_chat_messages(body)

    assert body["messages"] == [
        {"role": "user", "content": "hi"},
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
        {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
    ]


def test_build_sidecar_chat_payload_sanitizes_openai_tool_call_ids() -> None:
    request = ChatCompletionsRequest.model_validate(
        {
            "model": "claude-sonnet-4-5",
            "messages": [
                {"role": "user", "content": "hi"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call:1.2",
                            "type": "function",
                            "function": {"name": "lookup", "arguments": "{}"},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call:1.2", "content": "ok"},
            ],
        }
    )

    payload = build_sidecar_chat_payload(request, "claude-sonnet-4-5", _config())

    assert payload.body["messages"][1]["tool_calls"][0]["id"] == "call_1_2"
    assert payload.body["messages"][2]["tool_call_id"] == "call_1_2"


def test_ensure_stream_usage_requested_sets_or_overrides_include_usage() -> None:
    payload = {"model": "claude-sonnet", "stream_options": {"include_usage": False, "other": "value"}}

    ensure_stream_usage_requested(payload)

    assert payload["stream_options"] == {"include_usage": True, "other": "value"}


def test_extract_usage_supports_chat_and_responses_usage_shapes() -> None:
    chat_usage = extract_usage(
        {
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "prompt_tokens_details": {"cached_tokens": 2},
            }
        }
    )
    responses_usage = extract_usage(
        {
            "usage": {
                "input_tokens": 11,
                "output_tokens": 6,
                "input_tokens_details": {"cached_tokens": 3},
            }
        }
    )

    assert chat_usage is not None
    assert chat_usage.input_tokens == 10
    assert chat_usage.output_tokens == 5
    assert chat_usage.cached_input_tokens == 2
    assert responses_usage is not None
    assert responses_usage.input_tokens == 11
    assert responses_usage.output_tokens == 6
    assert responses_usage.cached_input_tokens == 3


def test_sse_decoder_extracts_usage_from_split_chunks() -> None:
    decoder = _SseUsageDecoder()

    first = decoder.feed('data: {"id":"one","usage":{"prompt_tokens":')
    second = decoder.feed('12,"completion_tokens":4}}\n\ndata: [DONE]\n\n')

    assert first == []
    assert len(second) == 2
    usage = extract_usage(second[0])
    assert usage is not None
    assert usage.input_tokens == 12
    assert usage.output_tokens == 4
    assert second[1] == "[DONE]"
