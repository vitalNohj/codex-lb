from __future__ import annotations

from app.core.clients.claude_sidecar import ClaudeSidecarConfig, SidecarPrefix
from app.core.openai.chat_requests import ChatCompletionsRequest
from app.modules.proxy.claude_sidecar_dispatch import (
    _SIDECAR_MESSAGE_CONTINUATION,
    _SseUsageDecoder,
    build_sidecar_chat_payload,
    ensure_stream_usage_requested,
    extract_usage,
    sanitize_sidecar_chat_messages,
    sanitize_sidecar_chat_tool_ids,
    sanitize_sidecar_forward_payload,
)


def _config(
    *,
    enabled: bool = True,
    prefixes: tuple[SidecarPrefix, ...] = (
        SidecarPrefix(prefix="claude", strip=False),
        SidecarPrefix(prefix="anthropic", strip=False),
    ),
    default_reasoning_effort: str | None = None,
) -> ClaudeSidecarConfig:
    return ClaudeSidecarConfig(
        enabled=enabled,
        base_url="http://127.0.0.1:8317",
        api_key="key",
        prefixes=prefixes,
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
        default_reasoning_effort=default_reasoning_effort,
    )


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


def test_build_sidecar_chat_payload_injects_override_effort_when_absent() -> None:
    request = ChatCompletionsRequest.model_validate(
        {"model": "gpt-5.4", "messages": [{"role": "user", "content": "hi"}]}
    )

    payload = build_sidecar_chat_payload(
        request, "claude-sonnet-4-5", _config(default_reasoning_effort="medium")
    )

    assert payload.body["reasoning_effort"] == "medium"


def test_build_sidecar_chat_payload_override_replaces_client_effort() -> None:
    request = ChatCompletionsRequest.model_validate(
        {
            "model": "gpt-5.4",
            "messages": [{"role": "user", "content": "hi"}],
            "reasoning_effort": "low",
        }
    )

    payload = build_sidecar_chat_payload(
        request, "claude-sonnet-4-5", _config(default_reasoning_effort="medium")
    )

    assert payload.body["reasoning_effort"] == "medium"


def test_build_sidecar_chat_payload_override_replaces_nested_reasoning() -> None:
    request = ChatCompletionsRequest.model_validate(
        {
            "model": "gpt-5.4",
            "messages": [{"role": "user", "content": "hi"}],
            "reasoning": {"effort": "minimal"},
        }
    )

    payload = build_sidecar_chat_payload(
        request, "claude-sonnet-4-5", _config(default_reasoning_effort="medium")
    )

    assert payload.body["reasoning_effort"] == "medium"
    assert "reasoning" not in payload.body


def test_build_sidecar_chat_payload_model_suffix_effort_beats_override() -> None:
    request = ChatCompletionsRequest.model_validate(
        {"model": "gpt-5.4", "messages": [{"role": "user", "content": "hi"}]}
    )

    payload = build_sidecar_chat_payload(
        request, "claude-sonnet-4-5-high", _config(default_reasoning_effort="medium")
    )

    assert payload.body["reasoning_effort"] == "high"


def test_build_sidecar_chat_payload_sends_unprefixed_model_for_custom_alias() -> None:
    request = ChatCompletionsRequest.model_validate(
        {
            "model": "cp_claude-fable-5",
            "messages": [{"role": "user", "content": "hi"}],
        }
    )

    payload = build_sidecar_chat_payload(
        request,
        "claude-fable-5",
        _config(prefixes=(SidecarPrefix(prefix="cp-", strip=True),)),
    )

    assert payload.body["model"] == "claude-fable-5"


def test_sanitize_sidecar_forward_payload_normalizes_reasoning_and_drops_responses_fields() -> None:
    body = {
        "model": "claude-opus-4-7",
        "reasoning": {"effort": "high", "summary": "auto"},
        "reasoning_effort": "medium",
        "previous_response_id": "resp_123",
        "text": {"format": {"type": "text"}},
        "messages": [{"role": "user", "content": "hi"}],
    }

    sanitize_sidecar_forward_payload(body)

    assert body["reasoning_effort"] == "medium"
    assert "reasoning" not in body
    assert "previous_response_id" not in body
    assert "text" not in body


def test_sanitize_sidecar_forward_payload_promotes_reasoning_effort_and_drops_reasoning() -> None:
    body = {
        "model": "claude-opus-4-7",
        "reasoning": {"effort": "high"},
        "messages": [{"role": "user", "content": "hi"}],
    }

    sanitize_sidecar_forward_payload(body)

    assert body["reasoning_effort"] == "high"
    assert "reasoning" not in body


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

    payload = build_sidecar_chat_payload(
        request,
        "cp-claude-fable-5",
        _config(prefixes=(SidecarPrefix(prefix="cp-", strip=True),)),
    )

    assistant_message = payload.body["messages"][1]
    tool_call = assistant_message["tool_calls"][0]
    assert assistant_message["content"] == "running tool"
    assert tool_call["id"] == "call_abc_def"
    assert tool_call["function"]["name"] == "Bash"
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


def test_build_sidecar_chat_payload_normalizes_cursor_tool_history_for_sidecar() -> None:
    request = ChatCompletionsRequest.model_validate(
        {
            "model": "claude-sonnet-4-5",
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "call:abc.def",
                            "name": "Shell",
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
    )

    payload = build_sidecar_chat_payload(request, "claude-sonnet-4-5", _config())

    assistant_message = payload.body["messages"][0]
    tool_message = payload.body["messages"][1]
    assert assistant_message == {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_abc_def",
                "type": "function",
                "function": {"name": "Bash", "arguments": '{"command":"pwd"}'},
            }
        ],
    }
    assert tool_message == {
        "role": "tool",
        "tool_call_id": "call_abc_def",
        "content": "/tmp",
    }
    assert payload.reverse_tool_names == {"Bash": "Shell"}


def test_build_sidecar_chat_payload_drops_orphan_cursor_tool_result_after_normalization() -> None:
    request = ChatCompletionsRequest.model_validate(
        {
            "model": "claude-sonnet-4-5",
            "messages": [
                {"role": "user", "content": "run pwd"},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "call_missing",
                            "content": "orphan",
                        }
                    ],
                },
            ],
        }
    )

    payload = build_sidecar_chat_payload(request, "claude-sonnet-4-5", _config())

    assert payload.body["messages"] == [{"role": "user", "content": "run pwd"}]


def test_sanitize_sidecar_chat_messages_drops_orphan_cursor_tool_result_content_parts() -> None:
    body = {
        "messages": [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "call_1",
                        "name": "lookup",
                        "input": {"q": "abc"},
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "keep"},
                    {"type": "tool_result", "tool_use_id": "call_2", "content": "orphan"},
                    {"type": "tool_result", "tool_use_id": "call_1", "content": "ok"},
                ],
            },
        ]
    }

    sanitize_sidecar_chat_messages(body)

    assert body["messages"] == [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "call_1",
                    "name": "lookup",
                    "input": {"q": "abc"},
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "keep"},
                {"type": "tool_result", "tool_use_id": "call_1", "content": "ok"},
            ],
        },
    ]


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
            {"role": "user", "content": [{"type": "input_text", "text": ""}]},
            {"role": "user", "content": {"type": "input_text", "text": "   "}},
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


def test_extract_usage_reads_openrouter_cost_field() -> None:
    usage_with_cost = extract_usage(
        {
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "cost": 0.00123,
            }
        }
    )

    assert usage_with_cost is not None
    assert usage_with_cost.input_tokens == 100
    assert usage_with_cost.output_tokens == 50
    assert usage_with_cost.cost_usd == 0.00123


def test_extract_usage_handles_missing_cost_field() -> None:
    usage_without_cost = extract_usage(
        {
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
            }
        }
    )

    assert usage_without_cost is not None
    assert usage_without_cost.cost_usd is None


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
