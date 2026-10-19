from __future__ import annotations

import pytest

from app.core.openai.requests import ResponsesRequest
from app.modules.proxy.responses_chat_bridge import (
    ResponsesStreamSynthesizer,
    chat_to_responses_result,
    responses_to_chat_request,
)

pytestmark = pytest.mark.unit


def _responses_request(**overrides) -> ResponsesRequest:
    data = {
        "model": "omniroute/test-chat",
        "instructions": "be helpful",
        "input": [
            {"role": "user", "content": [{"type": "input_text", "text": "hello"}]},
        ],
    }
    data.update(overrides)
    return ResponsesRequest.model_validate(data)


def test_request_translation_builds_messages_from_instructions_and_input():
    chat = responses_to_chat_request(_responses_request(), "omniroute/test-chat")

    assert chat.model == "omniroute/test-chat"
    assert chat.messages == [
        {"role": "system", "content": "be helpful"},
        {"role": "user", "content": "hello"},
    ]


def test_request_translation_handles_string_input():
    chat = responses_to_chat_request(
        _responses_request(instructions="", input="just text"),
        "omniroute/test-chat",
    )

    assert chat.messages == [{"role": "user", "content": "just text"}]


def test_request_translation_preserves_input_image_parts():
    request = _responses_request(
        instructions="",
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "describe this"},
                    {"type": "input_image", "image_url": "data:image/png;base64,AAAA"},
                ],
            }
        ],
    )

    chat = responses_to_chat_request(request, "omniroute/test-chat")

    assert chat.messages == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "describe this"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
            ],
        }
    ]


def test_request_translation_preserves_image_url_object_with_detail():
    request = _responses_request(
        instructions="",
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "look"},
                    {
                        "type": "input_image",
                        "image_url": {"url": "data:image/png;base64,BBBB", "detail": "high"},
                    },
                ],
            }
        ],
    )

    chat = responses_to_chat_request(request, "omniroute/test-chat")

    assert chat.messages[0]["content"][1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,BBBB", "detail": "high"},
    }


def test_request_translation_keeps_function_call_history():
    request = _responses_request(
        instructions="",
        input=[
            {"role": "user", "content": [{"type": "input_text", "text": "weather?"}]},
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "checking"}],
            },
            {
                "type": "function_call",
                "call_id": "call_1",
                "name": "lookup",
                "arguments": '{"city":"Seoul"}',
            },
            {
                "type": "function_call",
                "call_id": "call_2",
                "name": "lookup",
                "arguments": {"city": "Busan"},
            },
            {"type": "function_call_output", "call_id": "call_1", "output": "72F"},
            {"type": "function_call_output", "call_id": "call_2", "output": {"ok": True}},
        ],
    )

    chat = responses_to_chat_request(request, "omniroute/test-chat")

    assert chat.messages == [
        {"role": "user", "content": "weather?"},
        {
            "role": "assistant",
            "content": "checking",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "lookup", "arguments": '{"city":"Seoul"}'},
                },
                {
                    "id": "call_2",
                    "type": "function",
                    "function": {"name": "lookup", "arguments": '{"city":"Busan"}'},
                },
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "72F"},
        {"role": "tool", "tool_call_id": "call_2", "content": '{"ok":true}'},
    ]


def test_request_translation_function_call_without_assistant_text_is_its_own_turn():
    request = _responses_request(
        instructions="",
        input=[
            {"type": "function_call", "call_id": "call_1", "name": "lookup", "arguments": "{}"},
            {"type": "function_call_output", "call_id": "call_1", "output": "done"},
        ],
    )

    chat = responses_to_chat_request(request, "omniroute/test-chat")

    assert chat.messages[0]["role"] == "assistant"
    assert chat.messages[0]["tool_calls"][0]["id"] == "call_1"
    assert chat.messages[1] == {"role": "tool", "tool_call_id": "call_1", "content": "done"}
    assert all(message.get("content") != "" for message in chat.messages)


def test_request_translation_carries_tools_and_stream():
    request = _responses_request(
        stream=True,
        tools=[{"type": "function", "name": "lookup", "parameters": {"type": "object"}}],
    )
    chat = responses_to_chat_request(request, "omniroute/test-chat")

    assert chat.stream is True
    assert chat.tools == [{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}]


def test_non_streaming_result_wraps_assistant_text():
    chat_body = {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "model": "omniroute/test-chat",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi there"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
    }

    result = chat_to_responses_result(chat_body, model="omniroute/test-chat")

    assert result["object"] == "response"
    assert result["status"] == "completed"
    assert result["id"] == "resp_chatcmpl-1"
    assert result["output"][0]["type"] == "message"
    assert result["output"][0]["content"][0]["text"] == "hi there"
    assert result["usage"] == {
        "input_tokens": 7,
        "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
        "output_tokens": 3,
        "output_tokens_details": {"reasoning_tokens": 0},
        "total_tokens": 10,
    }


def test_non_streaming_result_maps_tool_calls():
    chat_body = {
        "id": "chatcmpl-2",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {"id": "call_1", "type": "function", "function": {"name": "lookup", "arguments": "{}"}}
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
    }

    result = chat_to_responses_result(chat_body, model="omniroute/test-chat")

    function_calls = [item for item in result["output"] if item["type"] == "function_call"]
    assert function_calls and function_calls[0]["call_id"] == "call_1"
    assert function_calls[0]["name"] == "lookup"


def test_stream_synthesizer_emits_created_then_completed():
    synth = ResponsesStreamSynthesizer(model="omniroute/test-chat")
    events: list = []
    events.extend(synth.feed({"choices": [{"delta": {"content": "hel"}}]}))
    events.extend(synth.feed({"choices": [{"delta": {"content": "lo"}}]}))
    events.extend(synth.feed("[DONE]"))

    types = [event["type"] for event in events]
    assert types[0] == "response.created"
    assert "response.output_text.delta" in types
    assert types[-1] == "response.completed"

    completed = events[-1]["response"]
    assert completed["output"][0]["content"][0]["text"] == "hello"


def test_stream_synthesizer_finish_is_idempotent():
    synth = ResponsesStreamSynthesizer(model="omniroute/test-chat")
    synth.feed({"choices": [{"delta": {"content": "x"}}]})
    first = synth.feed("[DONE]")
    second = synth.finish()

    assert first and first[-1]["type"] == "response.completed"
    assert second == []


def test_stream_synthesizer_emits_function_call_deltas():
    synth = ResponsesStreamSynthesizer(model="omniroute/test-chat")
    events: list = []
    events.extend(
        synth.feed(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {"name": "lookup", "arguments": '{"city":'},
                                }
                            ]
                        }
                    }
                ]
            }
        )
    )
    events.extend(
        synth.feed(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {"index": 0, "function": {"arguments": '"Seoul"}'}},
                                {
                                    "index": 1,
                                    "id": "call_2",
                                    "type": "function",
                                    "function": {"name": "lookup", "arguments": "{}"},
                                },
                            ]
                        }
                    }
                ]
            }
        )
    )
    events.extend(synth.feed("[DONE]"))

    types = [event["type"] for event in events]
    assert types[0] == "response.created"
    assert types.count("response.function_call_arguments.delta") == 3
    assert "response.function_call_arguments.done" in types
    assert "response.output_text.delta" not in types
    completed = events[-1]["response"]
    function_calls = [item for item in completed["output"] if item["type"] == "function_call"]
    assert [item["call_id"] for item in function_calls] == ["call_1", "call_2"]
    assert function_calls[0]["name"] == "lookup"
    assert function_calls[0]["arguments"] == '{"city":"Seoul"}'
    assert function_calls[1]["arguments"] == "{}"
    assert all(item["type"] != "message" for item in completed["output"])


def test_stream_synthesizer_appends_argument_fragments_that_share_a_prefix():
    """A fragment that starts with the accumulated arguments is still additive.

    Chat Completions ``delta.tool_calls[].function.arguments`` is a fragment.
    Treating a matching prefix as a cumulative snapshot drops valid JSON.
    """

    synth = ResponsesStreamSynthesizer(model="omniroute/test-chat")
    fragments = ['{"', '{"', ":1}"]
    for index, fragment in enumerate(fragments):
        function = {"name": "lookup", "arguments": fragment} if index == 0 else {"arguments": fragment}
        call: dict = {"index": 0, "function": function}
        if index == 0:
            call["id"] = "call_1"
        synth.feed({"choices": [{"delta": {"tool_calls": [call]}}]})
    completed = synth.feed("[DONE]")[-1]["response"]["output"][0]
    assert completed["arguments"] == '{"{":1}'

    repeated_prefix = ResponsesStreamSynthesizer(model="omniroute/test-chat")
    repeated_prefix.feed(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {"name": "lookup", "arguments": '{"a":'},
                            }
                        ]
                    }
                }
            ]
        }
    )
    events = repeated_prefix.feed(
        {
            "choices": [
                {"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '{"a":1}}'}}]}}
            ]
        }
    )
    deltas = [event["delta"] for event in events if event["type"] == "response.function_call_arguments.delta"]
    assert deltas == ['{"a":1}}']
    assert repeated_prefix.feed("[DONE]")[-1]["response"]["output"][0]["arguments"] == '{"a":{"a":1}}'


def test_stream_synthesizer_captures_usage():
    synth = ResponsesStreamSynthesizer(model="omniroute/test-chat")
    synth.feed({"choices": [{"delta": {"content": "hi"}}]})
    synth.feed({"choices": [], "usage": {"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5}})
    events = synth.feed("[DONE]")

    completed = events[-1]["response"]
    assert completed["usage"] == {
        "input_tokens": 4,
        "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
        "output_tokens": 1,
        "output_tokens_details": {"reasoning_tokens": 0},
        "total_tokens": 5,
    }


# --------------------------------------------------------------------------
# A truncated stream must not be reported as complete (PR 46 finding 2)
# --------------------------------------------------------------------------


class TestTerminalEventReflectsUpstreamCompletion:
    """``response.completed`` is a claim about the upstream, not about us.

    A clean EOF without the upstream's ``[DONE]`` means the response stopped
    short. Reporting it as completed tells the client its partial answer is the
    whole answer, with nothing in the payload to contradict it - silent and
    indistinguishable from success, which is worse than an explicit failure.
    """

    #: The terminal event is the last one emitted, by construction. Naming the
    #: candidates explicitly rather than pattern-matching on the type string
    #: keeps the assertion from quietly selecting some other event if the
    #: sequence changes.
    _TERMINAL_TYPES = {"response.completed", "response.incomplete", "response.failed"}

    @classmethod
    def _terminal(cls, events: list) -> str:
        terminal = [event["type"] for event in events if event["type"] in cls._TERMINAL_TYPES]
        assert len(terminal) == 1, f"expected exactly one terminal event, got {terminal}"
        assert events[-1]["type"] == terminal[0], "the terminal event must be last"
        return terminal[0]

    def test_a_genuinely_complete_stream_reports_completed(self) -> None:
        synth = ResponsesStreamSynthesizer(model="glm-5.3")
        synth.feed({"choices": [{"delta": {"content": "hello"}}]})

        events = synth.finish(upstream_completed=True)

        assert self._terminal(events) == "response.completed"
        assert events[-1]["response"]["status"] == "completed"

    def test_a_truncated_stream_reports_incomplete(self) -> None:
        synth = ResponsesStreamSynthesizer(model="glm-5.3")
        synth.feed({"choices": [{"delta": {"content": "hel"}}]})

        events = synth.finish(upstream_completed=False)

        assert self._terminal(events) == "response.incomplete"
        assert events[-1]["response"]["status"] == "incomplete"
        assert "response.completed" not in {event["type"] for event in events}

    def test_the_incomplete_event_names_a_reason_it_can_observe(self) -> None:
        """``interrupted``, not a guess at max-tokens or a content filter."""

        synth = ResponsesStreamSynthesizer(model="glm-5.3")
        synth.feed({"choices": [{"delta": {"content": "hel"}}]})

        events = synth.finish(upstream_completed=False)

        assert events[-1]["response"]["incomplete_details"] == {"reason": "interrupted"}

    def test_the_partial_text_is_still_delivered(self) -> None:
        """Incomplete is not empty: the client keeps what did arrive."""

        synth = ResponsesStreamSynthesizer(model="glm-5.3")
        synth.feed({"choices": [{"delta": {"content": "hel"}}]})

        events = synth.finish(upstream_completed=False)

        assert events[-1]["response"]["output"][0]["content"][0]["text"] == "hel"

    def test_the_default_preserves_the_completed_path(self) -> None:
        """Callers that pass nothing keep prior behaviour; both sites are explicit."""

        synth = ResponsesStreamSynthesizer(model="glm-5.3")
        synth.feed({"choices": [{"delta": {"content": "hi"}}]})

        assert self._terminal(synth.finish()) == "response.completed"
