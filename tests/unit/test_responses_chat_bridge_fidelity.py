"""Regression tests for the Responses -> chat-provider translation (audit PR-B).

Each test names the audit finding it pins (T2-T9). The streaming tests also
feed the synthesized events through the official ``openai`` SDK's Responses
stream accumulator, which raises on any event sequence it does not accept.
"""

from __future__ import annotations

import json
from typing import Any, cast

import pytest
from openai import omit
from openai.lib.streaming.responses._responses import ResponseStreamState
from openai.types.responses import Response, ResponseStreamEvent
from pydantic import TypeAdapter

from app.core.openai.exceptions import ClientPayloadError
from app.core.openai.requests import ResponsesRequest
from app.core.openai.v1_requests import V1ResponsesRequest
from app.modules.proxy.responses_chat_bridge import (
    ResponsesChatTranslation,
    ResponsesStreamSynthesizer,
    translate_responses_to_chat,
)
from app.modules.proxy.responses_chat_bridge import chat_to_responses_result as _chat_to_responses_result
from app.modules.proxy.responses_chat_tools import ChatToolShape, normalize_chat_function_tools

pytestmark = pytest.mark.unit

_MODEL = "openrouter/test-chat"
_EVENT_ADAPTER: TypeAdapter[ResponseStreamEvent] = TypeAdapter(ResponseStreamEvent)


def _request(**overrides: Any) -> ResponsesRequest:
    data: dict[str, Any] = {
        "model": _MODEL,
        "instructions": "be helpful",
        "input": [{"role": "user", "content": [{"type": "input_text", "text": "hello"}]}],
    }
    data.update(overrides)
    return ResponsesRequest.model_validate(data)


def _chat(**overrides: Any) -> dict[str, Any]:
    translation = translate_responses_to_chat(_request(**overrides), _MODEL)
    return translation.chat_request.model_dump(mode="json", exclude_none=True)


def chat_to_responses_result(
    chat_body: dict[str, Any], *, model: str, translation: ResponsesChatTranslation | None = None
) -> Any:
    return _chat_to_responses_result(chat_body, model=model, translation=translation)


class _Synth:
    """``ResponsesStreamSynthesizer`` with events typed loosely for assertions."""

    def __init__(self, *, model: str, translation: ResponsesChatTranslation | None = None) -> None:
        self._inner = ResponsesStreamSynthesizer(model=model, translation=translation)

    def feed(self, event: dict[str, Any] | str) -> list[Any]:
        return list(self._inner.feed(event))

    def fail(self, error: Any) -> list[Any]:
        return list(self._inner.fail(error))

    def finish(self) -> list[Any]:
        return list(self._inner.finish())


def _rejection(**overrides: Any) -> ClientPayloadError:
    with pytest.raises(ClientPayloadError) as exc_info:
        translate_responses_to_chat(_request(**overrides), _MODEL)
    error = exc_info.value
    # A bare ClientPayloadError renders as "Invalid request payload"; the
    # bridge always sets code and type so the client sees why.
    assert error.error_type == "invalid_request_error"
    assert error.code
    return error


def _sdk_replay(events: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> Response:
    """Run events through the SDK's stream state machine and return the final response."""

    state = ResponseStreamState(input_tools=cast(Any, tools or []), text_format=omit)
    for index, raw in enumerate(events):
        assert raw["sequence_number"] == index
        event = _EVENT_ADAPTER.validate_python(raw)
        state.handle_event(event)
    final = cast(Any, state)._completed_response
    assert final is not None, "stream never completed"
    return cast(Response, final)


# -- T2: tools ---------------------------------------------------------------


def test_t2_flat_function_tool_becomes_chat_function_tool():
    chat = _chat(
        tools=[
            {
                "type": "function",
                "name": "lookup",
                "description": "Look something up",
                "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
                "strict": True,
            }
        ],
        tool_choice={"type": "function", "name": "lookup"},
        parallel_tool_calls=False,
    )

    assert chat["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
                "description": "Look something up",
                "strict": True,
            },
        }
    ]
    assert chat["tool_choice"] == {"type": "function", "function": {"name": "lookup"}}
    assert chat["parallel_tool_calls"] is False


def test_t2_function_tool_without_parameters_gets_an_object_schema():
    chat = _chat(tools=[{"type": "function", "name": "ping"}])

    assert chat["tools"][0]["function"]["parameters"] == {"type": "object", "properties": {}}


def test_t2_custom_tool_is_a_function_taking_input_and_round_trips():
    tools = [
        {
            "type": "custom",
            "name": "apply_patch",
            "description": "Apply a patch",
            "format": {"type": "grammar", "syntax": "lark", "definition": "start: /.+/"},
        }
    ]
    translation = translate_responses_to_chat(_request(tools=tools), _MODEL)
    chat_tool: Any = translation.chat_request.tools[0]

    assert chat_tool == {
        "type": "function",
        "function": {
            "name": "apply_patch",
            "parameters": {
                "type": "object",
                "properties": {"input": {"type": "string"}},
                "required": ["input"],
                "additionalProperties": False,
            },
            "description": "Apply a patch\n\nThe `input` value must follow this lark grammar:\nstart: /.+/",
        },
    }
    assert translation.tool_shapes == {"apply_patch": ChatToolShape("custom", "apply_patch")}

    result = chat_to_responses_result(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "apply_patch", "arguments": '{"input":"*** Begin Patch"}'},
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        },
        model=_MODEL,
        translation=translation,
    )

    call = result["output"][0]
    assert call["type"] == "custom_tool_call"
    assert call["name"] == "apply_patch"
    assert call["call_id"] == "call_1"
    assert call["input"] == "*** Begin Patch"


def test_t2_namespace_tools_are_flattened_and_mapped_back():
    tools = [
        {
            "type": "namespace",
            "name": "mcp__docs",
            "description": "Docs server",
            "tools": [
                {"type": "function", "name": "search", "parameters": {"type": "object"}},
                {"type": "function", "name": "mcp__docs__fetch", "parameters": {"type": "object"}},
            ],
        }
    ]
    translation = translate_responses_to_chat(_request(tools=tools), _MODEL)
    names = [cast(Any, tool)["function"]["name"] for tool in translation.chat_request.tools]

    assert names == ["mcp__docs__search", "mcp__docs__fetch"]
    result = chat_to_responses_result(
        {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "c1",
                                "type": "function",
                                "function": {"name": "mcp__docs__search", "arguments": "{}"},
                            }
                        ]
                    }
                }
            ]
        },
        model=_MODEL,
        translation=translation,
    )
    assert result["output"][0]["name"] == "search"
    assert result["output"][0]["namespace"] == "mcp__docs"


def test_t2_cached_web_search_is_dropped_because_codex_sends_it_by_default():
    # Codex CLI's default web_search_mode is "cached", serialized as
    # external_web_access: false, and it is declared on every turn.
    chat = _chat(
        tools=[
            {"type": "web_search", "external_web_access": False},
            {"type": "function", "name": "lookup", "parameters": {"type": "object"}},
        ]
    )

    assert [tool["function"]["name"] for tool in chat["tools"]] == ["lookup"]


@pytest.mark.parametrize(
    "tool",
    [
        {"type": "web_search"},
        {"type": "web_search_preview"},
        {"type": "file_search", "vector_store_ids": ["vs_1"]},
        {"type": "code_interpreter", "container": {"type": "auto"}},
        {"type": "image_generation"},
        {"type": "local_shell"},
        {"type": "computer_use_preview", "display_width": 1, "display_height": 1, "environment": "linux"},
        {"type": "mcp", "server_label": "x", "server_url": "https://example.test"},
    ],
)
def test_t2_hosted_tools_are_rejected_instead_of_dropped(tool: dict[str, Any]):
    error = _rejection(tools=[tool])

    assert error.param == "tools[0]"


def test_t2_tool_choice_forcing_a_dropped_tool_is_rejected():
    error = _rejection(tools=[{"type": "web_search", "external_web_access": False}], tool_choice="required")

    assert error.param == "tool_choice"


def test_t2_chat_builders_normalize_flat_function_tools_and_leave_chat_tools_alone():
    body: dict[str, Any] = {
        "tools": [
            {"type": "function", "name": "flat", "parameters": {"type": "object"}},
            {"type": "function", "function": {"name": "nested", "parameters": {"type": "object"}}},
        ]
    }
    normalize_chat_function_tools(body)
    once = json.loads(json.dumps(body))
    normalize_chat_function_tools(body)

    assert body == once
    assert body["tools"] == [
        {"type": "function", "function": {"name": "flat", "parameters": {"type": "object"}}},
        {"type": "function", "function": {"name": "nested", "parameters": {"type": "object"}}},
    ]


# -- T3: stateful fields -------------------------------------------------------


def test_t3_previous_response_id_is_rejected():
    error = _rejection(previous_response_id="resp_123")

    assert error.param == "previous_response_id"
    assert error.code == "unsupported_parameter"


def test_t3_conversation_is_rejected():
    error = _rejection(conversation="conv_123")

    assert error.param == "conversation"


def test_t3_store_true_is_rejected_even_though_the_field_is_forced_false():
    request = _request(store=True)
    assert request.store is False
    assert request.client_requested_store is True

    with pytest.raises(ClientPayloadError) as exc_info:
        translate_responses_to_chat(request, _MODEL)
    assert exc_info.value.param == "store"


def test_t3_store_true_survives_the_v1_request_conversion():
    v1 = V1ResponsesRequest.model_validate({"model": _MODEL, "input": "hi", "store": True})

    assert v1.to_responses_request().client_requested_store is True


def test_t3_store_false_is_accepted():
    assert _chat(store=False)["messages"]


# -- T4: usage -----------------------------------------------------------------

_CHAT_USAGE = {
    "prompt_tokens": 1000,
    "completion_tokens": 50,
    "total_tokens": 1050,
    "prompt_tokens_details": {"cached_tokens": 900, "cached_creation_tokens": 64},
    "completion_tokens_details": {"reasoning_tokens": 30},
}
_RESPONSES_USAGE = {
    "input_tokens": 1000,
    "input_tokens_details": {"cached_tokens": 900, "cache_write_tokens": 64},
    "output_tokens": 50,
    "output_tokens_details": {"reasoning_tokens": 30},
    "total_tokens": 1050,
}


def test_t4_non_stream_usage_keeps_cached_and_reasoning_tokens():
    result = chat_to_responses_result(
        {"id": "x", "choices": [{"message": {"content": "hi"}}], "usage": _CHAT_USAGE},
        model=_MODEL,
    )

    assert result["usage"] == _RESPONSES_USAGE


def test_t4_stream_usage_keeps_cached_and_reasoning_tokens():
    synth = _Synth(model=_MODEL)
    events = synth.feed({"choices": [{"delta": {"content": "hi"}}]})
    events += synth.feed({"choices": [], "usage": _CHAT_USAGE})
    events += synth.feed("[DONE]")

    assert events[-1]["type"] == "response.completed"
    assert events[-1]["response"]["usage"] == _RESPONSES_USAGE
    assert _sdk_replay(events).usage is not None


def test_t4_usage_detail_objects_are_present_without_upstream_details():
    result = chat_to_responses_result(
        {"choices": [{"message": {"content": "hi"}}], "usage": {"prompt_tokens": 3, "completion_tokens": 2}},
        model=_MODEL,
    )

    assert result["usage"] == {
        "input_tokens": 3,
        "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
        "output_tokens": 2,
        "output_tokens_details": {"reasoning_tokens": 0},
        "total_tokens": 5,
    }


# -- T5 / T6: request parameters ----------------------------------------------------


def test_t5_t6_sampling_and_reasoning_fields_are_forwarded():
    chat = _chat(
        reasoning={"effort": "high", "summary": "auto"},
        max_output_tokens=512,
        temperature=0.2,
        top_p=0.9,
    )

    assert chat["reasoning_effort"] == "high"
    assert chat["max_tokens"] == 512
    assert chat["temperature"] == 0.2
    assert chat["top_p"] == 0.9
    assert "reasoning" not in chat


def test_t6_json_schema_text_format_becomes_response_format():
    schema = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
    chat = _chat(text={"format": {"type": "json_schema", "name": "answer", "schema": schema, "strict": True}})

    assert chat["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "answer", "schema": schema, "strict": True},
    }


def test_t6_json_object_and_text_formats():
    assert _chat(input="reply in json", text={"format": {"type": "json_object"}})["response_format"] == {
        "type": "json_object"
    }
    assert "response_format" not in _chat(text={"format": {"type": "text"}})


@pytest.mark.parametrize("field,value", [("max_output_tokens", 0), ("max_output_tokens", "9"), ("temperature", "hot")])
def test_t6_invalid_sampling_values_are_rejected(field: str, value: Any):
    assert _rejection(**{field: value}).param == field


# -- T7: text parts ------------------------------------------------------------------


def test_t7_multiple_text_parts_are_not_glued_together():
    chat = _chat(
        input=[
            {
                "role": "user",
                "content": [{"type": "input_text", "text": "part A"}, {"type": "input_text", "text": "part B"}],
            }
        ]
    )

    assert chat["messages"][1] == {
        "role": "user",
        "content": [{"type": "text", "text": "part A"}, {"type": "text", "text": "part B"}],
    }


def test_t7_single_text_part_stays_a_string_so_the_cache_prefix_is_unchanged():
    assert _chat()["messages"] == [
        {"role": "system", "content": "be helpful"},
        {"role": "user", "content": "hello"},
    ]


def test_t7_multi_part_tool_output_keeps_its_parts():
    chat = _chat(
        input=[
            {"type": "function_call", "call_id": "c1", "name": "lookup", "arguments": "{}"},
            {
                "type": "function_call_output",
                "call_id": "c1",
                "output": [{"type": "input_text", "text": "one"}, {"type": "input_text", "text": "two"}],
            },
        ],
        tools=[{"type": "function", "name": "lookup"}],
    )

    assert chat["messages"][-1] == {
        "role": "tool",
        "tool_call_id": "c1",
        "content": [{"type": "text", "text": "one"}, {"type": "text", "text": "two"}],
    }


# -- T8: stream events -----------------------------------------------------------------


def test_t8_text_stream_has_the_full_event_sequence_and_passes_the_sdk_parser():
    synth = _Synth(model=_MODEL)
    events = synth.feed({"choices": [{"delta": {"role": "assistant", "content": "hel"}}]})
    events += synth.feed({"choices": [{"delta": {"content": "lo"}, "finish_reason": "stop"}]})
    events += synth.feed("[DONE]")

    assert [event["type"] for event in events] == [
        "response.created",
        "response.in_progress",
        "response.output_item.added",
        "response.content_part.added",
        "response.output_text.delta",
        "response.output_text.delta",
        "response.output_text.done",
        "response.content_part.done",
        "response.output_item.done",
        "response.completed",
    ]
    assert [event["sequence_number"] for event in events] == list(range(len(events)))
    final = _sdk_replay(events)
    assert final.output_text == "hello"


def test_t8_function_call_stream_passes_the_sdk_parser():
    tools = [{"type": "function", "name": "lookup", "parameters": {"type": "object"}}]
    translation = translate_responses_to_chat(_request(tools=tools), _MODEL)
    synth = _Synth(model=_MODEL, translation=translation)
    events = synth.feed({"choices": [{"delta": {"content": "Checking."}}]})
    events += synth.feed(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {"index": 0, "id": "call_1", "function": {"name": "lookup", "arguments": '{"q":'}}
                        ]
                    }
                }
            ]
        }
    )
    events += synth.feed({"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '"x"}'}}]}}]})
    events += synth.feed({"choices": [{"delta": {}, "finish_reason": "tool_calls"}]})
    events += synth.feed("[DONE]")

    types = [event["type"] for event in events]
    assert types.index("response.function_call_arguments.done") < types.index("response.completed")
    done = next(event for event in events if event["type"] == "response.function_call_arguments.done")
    assert done["arguments"] == '{"q":"x"}'
    assert done["name"] == "lookup"
    final = _sdk_replay(events, tools)
    calls = [item for item in final.output if item.type == "function_call"]
    assert calls[0].arguments == '{"q":"x"}'
    assert calls[0].call_id == "call_1"


def test_t8_tool_call_before_text_closes_items_with_increasing_sequence_numbers():
    # The tool call takes output index 0 and the text index 1, so the closing
    # events must be numbered after sorting by output index, not before.
    tools = [{"type": "function", "name": "lookup", "parameters": {"type": "object"}}]
    translation = translate_responses_to_chat(_request(tools=tools), _MODEL)
    synth = _Synth(model=_MODEL, translation=translation)
    events = synth.feed(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "lookup", "arguments": "{}"}}]
                    }
                }
            ]
        }
    )
    events += synth.feed({"choices": [{"delta": {"content": "after the call"}}]})
    events += synth.feed({"choices": [{"delta": {}, "finish_reason": "tool_calls"}]})
    events += synth.feed("[DONE]")

    assert [event["sequence_number"] for event in events] == list(range(len(events)))
    done_indexes = [event["output_index"] for event in events if event["type"] == "response.output_item.done"]
    assert done_indexes == [0, 1]
    final = _sdk_replay(events, tools)
    assert [item.type for item in final.output] == ["function_call", "message"]


def test_t8_custom_tool_call_stream_passes_the_sdk_parser():
    tools = [{"type": "custom", "name": "apply_patch"}]
    translation = translate_responses_to_chat(_request(tools=tools), _MODEL)
    synth = _Synth(model=_MODEL, translation=translation)
    events = synth.feed(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {"index": 0, "id": "call_9", "function": {"name": "apply_patch", "arguments": '{"input":'}}
                        ]
                    }
                }
            ]
        }
    )
    events += synth.feed({"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '"diff"}'}}]}}]})
    events += synth.feed("[DONE]")

    types = [event["type"] for event in events]
    assert "response.function_call_arguments.delta" not in types
    assert "response.custom_tool_call_input.done" in types
    final = _sdk_replay(events)
    call = final.output[0]
    assert call.type == "custom_tool_call"
    assert call.input == "diff"
    assert call.call_id == "call_9"


def test_t8_refusal_stream_passes_the_sdk_parser():
    synth = _Synth(model=_MODEL)
    events = synth.feed({"choices": [{"delta": {"refusal": "I can't"}}]})
    events += synth.feed("[DONE]")

    assert "response.refusal.done" in [event["type"] for event in events]
    final = _sdk_replay(events)
    assert final.output[0].type == "message"
    assert final.output[0].content[0].type == "refusal"


def test_t8_length_finish_is_an_incomplete_response():
    synth = _Synth(model=_MODEL)
    events = synth.feed({"choices": [{"delta": {"content": "cut"}, "finish_reason": "length"}]})
    events += synth.feed("[DONE]")

    assert events[-1]["type"] == "response.incomplete"
    assert events[-1]["response"]["incomplete_details"] == {"reason": "max_output_tokens"}
    for raw in events:
        _EVENT_ADAPTER.validate_python(raw)


def test_t8_upstream_error_ends_the_stream_with_response_failed():
    synth = _Synth(model=_MODEL)
    events = synth.feed({"choices": [{"delta": {"content": "par"}}]})
    events += synth.fail({"code": "rate_limited", "message": "slow down"})

    assert events[-1]["type"] == "response.failed"
    assert events[-1]["response"]["error"] == {"code": "rate_limit_exceeded", "message": "slow down"}
    for raw in events:
        _EVENT_ADAPTER.validate_python(raw)
    assert synth.finish() == []


def test_t8_error_chunk_fed_to_the_synthesizer_fails_the_response():
    # OmniRoute and OpenCode Go feed every decoded chunk, error chunks included.
    synth = _Synth(model=_MODEL)
    events = synth.feed({"choices": [{"delta": {"content": "par"}}]})
    events += synth.feed({"error": {"code": "rate_limit_exceeded", "message": "slow"}})
    events += synth.feed("[DONE]")

    assert [event["type"] for event in events][-1] == "response.failed"
    assert sum(event["type"].startswith("response.") and "response" in event for event in events[-1:]) == 1


def test_t8_upstream_error_code_outside_the_responses_set_is_a_server_error():
    synth = _Synth(model=_MODEL)
    events = synth.fail({"code": "sidecar_error", "message": "boom"})

    assert events[-1]["response"]["error"] == {"code": "server_error", "message": "boom (sidecar_error)"}
    for raw in events:
        _EVENT_ADAPTER.validate_python(raw)


def test_t8_empty_stream_still_yields_one_valid_message():
    synth = _Synth(model=_MODEL)
    events = synth.feed("[DONE]")

    final = _sdk_replay(events)
    assert final.output_text == ""


def test_t8_non_stream_result_validates_as_an_sdk_response():
    result = chat_to_responses_result(
        {
            "id": "c",
            "choices": [{"message": {"content": "hi", "refusal": None}, "finish_reason": "length"}],
            "usage": _CHAT_USAGE,
        },
        model=_MODEL,
    )

    assert result["status"] == "incomplete"
    assert result["incomplete_details"] == {"reason": "max_output_tokens"}
    parsed = Response.model_validate(result)
    assert parsed.output_text == "hi"


# -- T9: input items ------------------------------------------------------------------


def test_t9_custom_tool_call_history_is_sent_as_a_tool_call():
    chat = _chat(
        tools=[{"type": "custom", "name": "apply_patch"}],
        input=[
            {"role": "user", "content": "patch it"},
            {"type": "custom_tool_call", "call_id": "c1", "name": "apply_patch", "input": "*** Begin Patch"},
            {"type": "custom_tool_call_output", "call_id": "c1", "output": "Done"},
        ],
    )

    assert chat["messages"][2] == {
        "role": "assistant",
        "tool_calls": [
            {
                "id": "c1",
                "type": "function",
                "function": {"name": "apply_patch", "arguments": '{"input":"*** Begin Patch"}'},
            }
        ],
    }
    assert chat["messages"][3] == {"role": "tool", "tool_call_id": "c1", "content": "Done"}


def test_t9_namespaced_function_call_history_uses_the_flat_name():
    chat = _chat(
        tools=[{"type": "namespace", "name": "mcp__docs", "tools": [{"type": "function", "name": "search"}]}],
        input=[
            {"type": "function_call", "call_id": "c1", "name": "search", "namespace": "mcp__docs", "arguments": "{}"},
            {"type": "function_call_output", "call_id": "c1", "output": "ok"},
        ],
    )

    assert chat["messages"][1]["tool_calls"][0]["function"]["name"] == "mcp__docs__search"


def test_t9_input_file_with_inline_data_becomes_a_chat_file_part():
    chat = _chat(
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "summarize"},
                    {"type": "input_file", "filename": "a.pdf", "file_data": "data:application/pdf;base64,QUJD"},
                ],
            }
        ]
    )

    assert chat["messages"][1]["content"] == [
        {"type": "text", "text": "summarize"},
        {"type": "file", "file": {"file_data": "data:application/pdf;base64,QUJD", "filename": "a.pdf"}},
    ]


@pytest.mark.parametrize(
    "part,param",
    [
        ({"type": "input_file", "file_id": "file_1"}, "input[0].content[0].file_id"),
        ({"type": "input_file", "file_url": "https://example.test/a.pdf"}, "input[0].content[0].file_url"),
        ({"type": "input_image", "file_id": "file_2"}, "input[0].content[0].file_id"),
        ({"type": "input_audio", "input_audio": {"data": "x", "format": "wav"}}, "input[0].content[0]"),
    ],
)
def test_t9_unmappable_content_parts_are_rejected(part: dict[str, Any], param: str):
    error = _rejection(instructions="", input=[{"role": "user", "content": [part]}])

    assert error.param == param


@pytest.mark.parametrize(
    "item",
    [
        {"type": "item_reference", "id": "msg_1"},
        {"type": "local_shell_call", "call_id": "c", "status": "completed", "action": {"type": "exec"}},
        {"type": "compaction", "encrypted_content": "abc"},
        {"type": "image_generation_call", "id": "ig", "status": "completed", "result": "x"},
    ],
)
def test_t9_unmappable_input_items_are_rejected(item: dict[str, Any]):
    error = _rejection(input=[item])

    assert error.param == "input[0]"


def test_t9_reasoning_and_web_search_call_items_are_omitted():
    chat = _chat(
        input=[
            {"role": "user", "content": "q"},
            {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "opaque"},
            {"type": "web_search_call", "id": "ws_1", "status": "completed"},
            {"role": "assistant", "content": [{"type": "output_text", "text": "a"}]},
        ]
    )

    assert chat["messages"][1:] == [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]


def test_t9_additional_tools_item_declares_tools():
    chat = _chat(
        input=[
            {"type": "additional_tools", "role": "developer", "tools": [{"type": "function", "name": "extra"}]},
            {"role": "user", "content": "go"},
        ]
    )

    assert [tool["function"]["name"] for tool in chat["tools"]] == ["extra"]
    assert chat["messages"][1:] == [{"role": "user", "content": "go"}]


def test_t2_identical_duplicate_tool_is_sent_once():
    tool = {"type": "function", "name": "extra", "parameters": {"type": "object"}}
    chat = _chat(
        tools=[tool],
        input=[
            {"type": "additional_tools", "role": "developer", "tools": [dict(tool)]},
            {"role": "user", "content": "go"},
        ],
    )

    assert [entry["function"]["name"] for entry in chat["tools"]] == ["extra"]


@pytest.mark.parametrize(
    "second",
    [
        {"type": "function", "name": "extra", "parameters": {"type": "object", "required": ["q"]}},
        {"type": "function", "name": "extra", "parameters": {"type": "object"}, "strict": True},
        {"type": "function", "name": "extra", "parameters": {"type": "object"}, "description": "other"},
        {"type": "custom", "name": "extra"},
    ],
)
def test_t2_conflicting_duplicate_tools_are_rejected_instead_of_dropped(second: dict[str, Any]):
    first = {"type": "function", "name": "extra", "parameters": {"type": "object"}}
    error = _rejection(
        tools=[first],
        input=[
            {"type": "additional_tools", "role": "developer", "tools": [second]},
            {"role": "user", "content": "go"},
        ],
    )

    assert "extra" in str(error)


def test_t2_conflicting_custom_tool_grammars_are_rejected():
    def custom(definition: str) -> dict[str, Any]:
        return {
            "type": "custom",
            "name": "apply_patch",
            "format": {"type": "grammar", "syntax": "lark", "definition": definition},
        }

    _rejection(tools=[custom("start: A"), custom("start: B")])


def test_t9_agent_message_text_is_kept():
    chat = _chat(
        input=[
            {
                "type": "agent_message",
                "author": "lead",
                "recipient": "worker",
                "content": [{"type": "input_text", "text": "do the task"}],
            }
        ]
    )

    assert chat["messages"][1:] == [{"role": "user", "content": "do the task"}]


def test_tool_output_image_reaches_chat_provider_as_image_part():
    image = "data:image/png;base64,AAAA"
    chat = _chat(
        input=[
            {"type": "function_call", "call_id": "c1", "name": "lookup", "arguments": "{}"},
            {
                "type": "function_call_output",
                "call_id": "c1",
                "output": [
                    {"type": "input_text", "text": "shot"},
                    {"type": "input_image", "image_url": image, "detail": "low"},
                ],
            },
        ],
        tools=[{"type": "function", "name": "lookup"}],
    )

    assert chat["messages"][-1] == {
        "role": "tool",
        "tool_call_id": "c1",
        "content": [
            {"type": "text", "text": "shot"},
            {"type": "image_url", "image_url": {"url": image, "detail": "low"}},
        ],
    }
