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


def test_request_translation_carries_tools_and_stream():
    request = _responses_request(
        stream=True,
        tools=[{"type": "function", "name": "lookup", "parameters": {"type": "object"}}],
    )
    chat = responses_to_chat_request(request, "omniroute/test-chat")

    assert chat.stream is True
    assert chat.tools and chat.tools[0]["name"] == "lookup"


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
    assert result["usage"] == {"input_tokens": 7, "output_tokens": 3, "total_tokens": 10}


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


def test_stream_synthesizer_captures_usage():
    synth = ResponsesStreamSynthesizer(model="omniroute/test-chat")
    synth.feed({"choices": [{"delta": {"content": "hi"}}]})
    synth.feed({"choices": [], "usage": {"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5}})
    events = synth.feed("[DONE]")

    completed = events[-1]["response"]
    assert completed["usage"] == {"input_tokens": 4, "output_tokens": 1, "total_tokens": 5}


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
