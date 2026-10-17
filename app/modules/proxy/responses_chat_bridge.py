from __future__ import annotations

import json
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from app.core.openai.chat_requests import ChatCompletionsRequest
from app.core.openai.requests import ResponsesRequest
from app.core.types import JsonObject, JsonValue
from app.core.utils.json_guards import is_json_list, is_json_mapping

_OUTPUT_TEXT_TYPE = "output_text"


def responses_to_chat_request(
    payload: ResponsesRequest,
    effective_model: str,
) -> ChatCompletionsRequest:
    """Translate a normalized Responses request into an OmniRoute chat request.

    OmniRoute only exposes an OpenAI-compatible ``/chat/completions`` endpoint,
    so the Responses ``instructions``/``input`` content is flattened into chat
    ``messages``. Codex-native, server-side continuity fields (``store``,
    ``previous_response_id``, ``conversation``, ``reasoning``) are intentionally
    dropped because OmniRoute is a stateless relay.
    """

    messages: list[JsonValue] = []
    instructions = payload.instructions.strip() if isinstance(payload.instructions, str) else ""
    if instructions:
        messages.append({"role": "system", "content": instructions})
    messages.extend(_input_items_to_messages(payload.input))
    if not messages:
        messages.append({"role": "user", "content": ""})

    data: JsonObject = {
        "model": effective_model.strip(),
        "messages": messages,
    }
    if payload.tools:
        data["tools"] = list(payload.tools)
    if payload.tool_choice is not None:
        data["tool_choice"] = payload.tool_choice
    if payload.parallel_tool_calls is not None:
        data["parallel_tool_calls"] = payload.parallel_tool_calls
    if payload.service_tier is not None:
        data["service_tier"] = payload.service_tier
    if payload.stream is not None:
        data["stream"] = payload.stream
    return ChatCompletionsRequest.model_validate(data)


def _input_items_to_messages(input_value: JsonValue) -> list[JsonValue]:
    if isinstance(input_value, str):
        text = input_value.strip()
        return [{"role": "user", "content": text}] if text else []
    if not is_json_list(input_value):
        return []
    messages: list[JsonValue] = []
    pending_tool_calls: list[JsonValue] = []
    for item in input_value:
        if _item_type(item) == "function_call":
            tool_call = _function_call_to_tool_call(item)
            if tool_call is not None:
                pending_tool_calls.append(tool_call)
            continue
        _flush_pending_tool_calls(messages, pending_tool_calls)
        if _item_type(item) == "function_call_output":
            tool_message = _function_call_output_to_message(item)
            if tool_message is not None:
                messages.append(tool_message)
            continue
        message = _input_item_to_message(item)
        if message is not None:
            messages.append(message)
    _flush_pending_tool_calls(messages, pending_tool_calls)
    return messages


def _item_type(item: JsonValue) -> str | None:
    if not is_json_mapping(item):
        return None
    item_type = item.get("type")
    return item_type if isinstance(item_type, str) else None


def _function_call_to_tool_call(item: JsonValue) -> JsonObject | None:
    """Map one Responses ``function_call`` item onto a chat ``tool_calls`` entry."""

    if not is_json_mapping(item):
        return None
    name = item.get("name")
    call_id = item.get("call_id")
    if not isinstance(name, str) or not name or not isinstance(call_id, str) or not call_id:
        return None
    arguments = item.get("arguments")
    if isinstance(arguments, str):
        argument_text = arguments
    elif arguments is None:
        argument_text = ""
    else:
        argument_text = json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": argument_text},
    }


def _function_call_output_to_message(item: JsonValue) -> JsonObject | None:
    """Map one Responses ``function_call_output`` item onto a chat tool message."""

    if not is_json_mapping(item):
        return None
    call_id = item.get("call_id")
    if not isinstance(call_id, str) or not call_id:
        return None
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "content": _tool_output_content(item.get("output")),
    }


def _tool_output_content(output: JsonValue) -> str:
    if isinstance(output, str):
        return output
    if output is None:
        return ""
    return json.dumps(output, ensure_ascii=False, separators=(",", ":"))


def _flush_pending_tool_calls(messages: list[JsonValue], pending: list[JsonValue]) -> None:
    """Attach accumulated function calls to the preceding assistant turn.

    Chat completions put every tool call on the assistant message that
    requested them. Responses lists those calls as sibling items, so a run of
    ``function_call`` items is folded back onto that message. A call with no
    preceding assistant message becomes its own assistant turn.
    """

    if not pending:
        return
    tool_calls = list(pending)
    pending.clear()
    if messages and is_json_mapping(messages[-1]) and messages[-1].get("role") == "assistant":
        previous = dict(messages[-1])
        existing = previous.get("tool_calls")
        if is_json_list(existing):
            previous["tool_calls"] = [*existing, *tool_calls]
        else:
            previous["tool_calls"] = tool_calls
        messages[-1] = previous
        return
    messages.append({"role": "assistant", "content": None, "tool_calls": tool_calls})


def _input_item_to_message(item: JsonValue) -> JsonValue | None:
    if not is_json_mapping(item):
        return None
    role = item.get("role")
    role_name = role if isinstance(role, str) and role else "user"
    if role_name not in ("system", "developer", "user", "assistant", "tool"):
        role_name = "user"
    content = _extract_item_content(item.get("content"))
    if content is None:
        return None
    return {"role": role_name, "content": content}


def _extract_item_content(content: JsonValue) -> JsonValue | None:
    """Translate a Responses content value into OpenAI chat content.

    Text-only content collapses to a plain string so simple turns stay
    compact, but multimodal content (images) is preserved as an OpenAI chat
    content-parts array (``text`` + ``image_url`` parts). Dropping the image
    parts here is what previously made images invisible to OmniRoute when a
    request arrived on the Responses endpoints.
    """

    if isinstance(content, str):
        return content
    if not is_json_list(content):
        return None
    text_parts: list[str] = []
    chat_parts: list[JsonValue] = []
    has_image = False
    for part in content:
        if not is_json_mapping(part):
            continue
        text_value = part.get("text")
        if isinstance(text_value, str):
            text_parts.append(text_value)
            chat_parts.append({"type": "text", "text": text_value})
            continue
        image_part = _responses_image_part_to_chat(part)
        if image_part is not None:
            has_image = True
            chat_parts.append(image_part)
    if has_image:
        return chat_parts
    if not text_parts:
        return None
    return "".join(text_parts)


def _responses_image_part_to_chat(part: Mapping[str, JsonValue]) -> JsonValue | None:
    """Map a Responses ``input_image``/``image_url`` part to a chat image part.

    Returns the OpenAI chat ``{"type": "image_url", "image_url": {...}}`` shape
    accepted by OmniRoute, or ``None`` when the part has no usable image URL.
    """

    part_type = part.get("type")
    if part_type not in ("input_image", "image_url"):
        return None
    image_url = part.get("image_url")
    if isinstance(image_url, str):
        url = image_url
    elif is_json_mapping(image_url):
        url = image_url.get("url")
    else:
        url = None
    if not isinstance(url, str) or not url:
        return None
    image_payload: JsonObject = {"url": url}
    detail = part.get("detail")
    if isinstance(detail, str) and detail:
        image_payload["detail"] = detail
    elif is_json_mapping(image_url):
        detail_value = image_url.get("detail")
        if isinstance(detail_value, str) and detail_value:
            image_payload["detail"] = detail_value
    return {"type": "image_url", "image_url": image_payload}


def chat_to_responses_result(chat_body: JsonValue, *, model: str) -> JsonObject:
    """Wrap an OmniRoute chat-completion JSON body in a Responses result."""

    message = _first_choice_message(chat_body)
    output_text = ""
    tool_calls: list[JsonValue] = []
    if message is not None:
        content = message.get("content")
        if isinstance(content, str):
            output_text = content
        raw_tool_calls = message.get("tool_calls")
        if is_json_list(raw_tool_calls):
            tool_calls = _chat_tool_calls_to_output_items(raw_tool_calls)

    output: list[JsonValue] = []
    if output_text:
        output.append(_message_output_item(output_text))
    output.extend(tool_calls)

    response_id = _chat_response_id(chat_body)
    result: JsonObject = {
        "id": response_id,
        "object": "response",
        "created_at": int(time.time()),
        "status": "completed",
        "model": model,
        "output": output,
    }
    usage = _responses_usage(chat_body)
    if usage is not None:
        result["usage"] = usage
    return result


def _message_output_item(text: str) -> JsonObject:
    return {
        "id": f"msg_{uuid.uuid4().hex}",
        "type": "message",
        "status": "completed",
        "role": "assistant",
        "content": [{"type": _OUTPUT_TEXT_TYPE, "text": text, "annotations": []}],
    }


def _chat_tool_calls_to_output_items(raw_tool_calls: list[JsonValue]) -> list[JsonValue]:
    items: list[JsonValue] = []
    for call in raw_tool_calls:
        if not is_json_mapping(call):
            continue
        function = call.get("function")
        if not is_json_mapping(function):
            continue
        name = function.get("name")
        arguments = function.get("arguments")
        call_id = call.get("id")
        items.append(
            {
                "id": f"fc_{uuid.uuid4().hex}",
                "type": "function_call",
                "status": "completed",
                "call_id": call_id if isinstance(call_id, str) else f"call_{uuid.uuid4().hex}",
                "name": name if isinstance(name, str) else "",
                "arguments": arguments if isinstance(arguments, str) else "",
            }
        )
    return items


def _first_choice_message(chat_body: JsonValue) -> Mapping[str, JsonValue] | None:
    if not is_json_mapping(chat_body):
        return None
    choices = chat_body.get("choices")
    if not is_json_list(choices) or not choices:
        return None
    first = choices[0]
    if not is_json_mapping(first):
        return None
    message = first.get("message")
    return message if is_json_mapping(message) else None


def _chat_response_id(chat_body: JsonValue) -> str:
    if is_json_mapping(chat_body):
        raw_id = chat_body.get("id")
        if isinstance(raw_id, str) and raw_id:
            return f"resp_{raw_id}"
    return f"resp_{uuid.uuid4().hex}"


def _responses_usage(chat_body: JsonValue) -> JsonObject | None:
    if not is_json_mapping(chat_body):
        return None
    usage = chat_body.get("usage")
    return _usage_to_responses_usage(usage)


def _usage_to_responses_usage(usage: JsonValue) -> JsonObject | None:
    if not is_json_mapping(usage):
        return None
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    total = usage.get("total_tokens")
    result: JsonObject = {}
    if isinstance(prompt, int):
        result["input_tokens"] = prompt
    if isinstance(completion, int):
        result["output_tokens"] = completion
    if isinstance(total, int):
        result["total_tokens"] = total
    return result or None


@dataclass
class _StreamToolCall:
    output_index: int
    item_id: str
    call_id: str
    name: str
    arguments: str
    added: bool = False


class ResponsesStreamSynthesizer:
    """Synthesize the minimal Responses event sequence from chat SSE deltas.

    Consumes parsed OmniRoute chat-completion chunk objects and ``[DONE]``
    sentinels (as produced by the shared SSE decoder) and yields Responses
    event mappings: ``response.created``, ``response.output_item.added``,
    ``response.output_text.delta`` (one per content delta),
    ``response.function_call_arguments.delta`` (one per tool-call argument
    fragment), ``response.output_item.done``, and a terminal
    ``response.completed``.
    """

    def __init__(self, *, model: str) -> None:
        self._model = model
        self._response_id = f"resp_{uuid.uuid4().hex}"
        self._item_id = f"msg_{uuid.uuid4().hex}"
        self._created_emitted = False
        self._item_added = False
        self._completed = False
        self._text_parts: list[str] = []
        self._usage: JsonObject | None = None
        self._message_output_index: int | None = None
        self._next_output_index = 0
        self._tool_calls: dict[int, _StreamToolCall] = {}

    def feed(self, event: JsonObject | str) -> list[JsonObject]:
        if event == "[DONE]":
            return self._finish()
        if not isinstance(event, dict):
            return []
        out: list[JsonObject] = []
        if not self._created_emitted:
            out.append(self._response_created())
            self._created_emitted = True
        usage = event.get("usage")
        mapped_usage = _usage_to_responses_usage(usage)
        if mapped_usage is not None:
            self._usage = mapped_usage
        delta_text = _chat_chunk_delta_text(event)
        if delta_text:
            if not self._item_added:
                out.append(self._output_item_added())
                self._item_added = True
            self._text_parts.append(delta_text)
            out.append(
                {
                    "type": "response.output_text.delta",
                    "response_id": self._response_id,
                    "item_id": self._item_id,
                    "output_index": self._message_output_index,
                    "content_index": 0,
                    "delta": delta_text,
                }
            )
        out.extend(self._feed_tool_calls(event))
        return out

    def finish(self, *, upstream_completed: bool = True) -> list[JsonObject]:
        """Emit the terminal events for this response.

        ``upstream_completed`` must reflect whether the upstream actually sent
        its ``[DONE]`` sentinel. A stream that ended early - a truncated body, a
        dropped connection - is **not** a completed response, and saying so would
        tell the client its partial answer is the whole answer, with nothing in
        the payload to contradict it. That is worse than an explicit failure,
        because it is silent and indistinguishable from success.
        """

        return self._finish(upstream_completed=upstream_completed)

    def _finish(self, *, upstream_completed: bool = True) -> list[JsonObject]:
        if self._completed:
            return []
        self._completed = True
        out: list[JsonObject] = []
        if not self._created_emitted:
            out.append(self._response_created())
            self._created_emitted = True
        if not self._item_added and not self._tool_calls:
            out.append(self._output_item_added())
            self._item_added = True
        closers: list[tuple[int, list[JsonObject]]] = []
        if self._item_added:
            message_index = 0 if self._message_output_index is None else self._message_output_index
            closers.append((message_index, [self._output_item_done()]))
        for call in self._tool_calls.values():
            call_events: list[JsonObject] = []
            if not call.added:
                call_events.append(self._function_call_added(call))
                call.added = True
            call_events.append(self._function_call_arguments_done(call))
            call_events.append(self._function_call_done(call))
            closers.append((call.output_index, call_events))
        for _, call_events in sorted(closers, key=lambda item: item[0]):
            out.extend(call_events)
        # ``response.incomplete`` is the protocol's existing terminal event for
        # a response that stopped short; this repo's own converters already
        # recognize it (app/core/openai/chat_responses.py) and map it to a
        # non-``stop`` finish reason, so no new vocabulary is invented here.
        out.append(self._response_completed() if upstream_completed else self._response_incomplete())
        return out

    def _message_item(self) -> JsonObject:
        return {
            "id": self._item_id,
            "type": "message",
            "status": "completed",
            "role": "assistant",
            "content": [{"type": _OUTPUT_TEXT_TYPE, "text": "".join(self._text_parts), "annotations": []}],
        }

    def _response_object(self, status: str) -> JsonObject:
        response: JsonObject = {
            "id": self._response_id,
            "object": "response",
            "status": status,
            "model": self._model,
            "output": self._completed_output_items(),
        }
        if self._usage is not None:
            response["usage"] = self._usage
        return response

    def _response_created(self) -> JsonObject:
        return {"type": "response.created", "response": self._response_object("in_progress")}

    def _output_item_added(self) -> JsonObject:
        output_index = self._allocate_output_index()
        self._message_output_index = output_index
        return {
            "type": "response.output_item.added",
            "output_index": output_index,
            "item": {
                "id": self._item_id,
                "type": "message",
                "status": "in_progress",
                "role": "assistant",
                "content": [],
            },
        }

    def _output_item_done(self) -> JsonObject:
        output_index = 0 if self._message_output_index is None else self._message_output_index
        return {"type": "response.output_item.done", "output_index": output_index, "item": self._message_item()}

    def _allocate_output_index(self) -> int:
        output_index = self._next_output_index
        self._next_output_index += 1
        return output_index

    def _feed_tool_calls(self, event: JsonObject) -> list[JsonObject]:
        out: list[JsonObject] = []
        for call in _chat_chunk_tool_calls(event):
            chat_index = call.get("index")
            index = chat_index if isinstance(chat_index, int) else 0
            state = self._tool_calls.get(index)
            name = _tool_call_name(call)
            call_id = _tool_call_id(call)
            if state is None:
                state = _StreamToolCall(
                    output_index=self._allocate_output_index(),
                    item_id=f"fc_{uuid.uuid4().hex}",
                    call_id=call_id or f"call_{uuid.uuid4().hex}",
                    name=name or "",
                    arguments="",
                )
                self._tool_calls[index] = state
            elif not state.added:
                if call_id:
                    state.call_id = call_id
                if name:
                    state.name = name
            elif name and not state.name:
                state.name = name
            if not state.added:
                out.append(self._function_call_added(state))
                state.added = True
            fragment = _new_argument_text(state.arguments, _tool_call_arguments(call))
            if fragment:
                state.arguments += fragment
                out.append(
                    {
                        "type": "response.function_call_arguments.delta",
                        "response_id": self._response_id,
                        "item_id": state.item_id,
                        "output_index": state.output_index,
                        "delta": fragment,
                    }
                )
        return out

    def _function_call_added(self, call: _StreamToolCall) -> JsonObject:
        return {
            "type": "response.output_item.added",
            "output_index": call.output_index,
            "item": {
                "id": call.item_id,
                "type": "function_call",
                "status": "in_progress",
                "call_id": call.call_id,
                "name": call.name,
                "arguments": "",
            },
        }

    def _function_call_arguments_done(self, call: _StreamToolCall) -> JsonObject:
        return {
            "type": "response.function_call_arguments.done",
            "response_id": self._response_id,
            "item_id": call.item_id,
            "output_index": call.output_index,
            "arguments": call.arguments,
        }

    def _function_call_done(self, call: _StreamToolCall) -> JsonObject:
        return {
            "type": "response.output_item.done",
            "output_index": call.output_index,
            "item": self._function_call_item(call),
        }

    def _function_call_item(self, call: _StreamToolCall) -> JsonObject:
        return {
            "id": call.item_id,
            "type": "function_call",
            "status": "completed",
            "call_id": call.call_id,
            "name": call.name,
            "arguments": call.arguments,
        }

    def _completed_output_items(self) -> list[JsonValue]:
        ranked: list[tuple[int, JsonObject]] = []
        if self._item_added and self._message_output_index is not None:
            ranked.append((self._message_output_index, self._message_item()))
        for call in self._tool_calls.values():
            ranked.append((call.output_index, self._function_call_item(call)))
        ranked.sort(key=lambda item: item[0])
        return [item for _, item in ranked]

    def _response_completed(self) -> JsonObject:
        return {"type": "response.completed", "response": self._response_object("completed")}

    def _response_incomplete(self) -> JsonObject:
        """Terminal event for a stream that ended without upstream completion.

        ``incomplete_details.reason`` is ``"interrupted"``: the upstream stopped
        mid-response. It is deliberately not ``"max_output_tokens"`` or a content
        filter, which would assert a cause this layer cannot observe.
        """

        response = self._response_object("incomplete")
        response["incomplete_details"] = {"reason": "interrupted"}
        return {"type": "response.incomplete", "response": response}


def _chat_chunk_tool_calls(event: JsonObject) -> list[Mapping[str, JsonValue]]:
    choices = event.get("choices")
    if not is_json_list(choices) or not choices:
        return []
    first = choices[0]
    if not is_json_mapping(first):
        return []
    delta = first.get("delta")
    if not is_json_mapping(delta):
        return []
    tool_calls = delta.get("tool_calls")
    if not is_json_list(tool_calls):
        return []
    return [call for call in tool_calls if is_json_mapping(call)]


def _tool_call_id(call: Mapping[str, JsonValue]) -> str | None:
    call_id = call.get("id")
    if isinstance(call_id, str) and call_id:
        return call_id
    return None


def _tool_call_name(call: Mapping[str, JsonValue]) -> str | None:
    function = call.get("function")
    if not is_json_mapping(function):
        return None
    name = function.get("name")
    if isinstance(name, str) and name:
        return name
    return None


def _tool_call_arguments(call: Mapping[str, JsonValue]) -> str:
    function = call.get("function")
    if not is_json_mapping(function):
        return ""
    arguments = function.get("arguments")
    return arguments if isinstance(arguments, str) else ""


def _new_argument_text(current: str, incoming: str) -> str:
    """Return only the argument bytes this chunk adds.

    Chat streams usually send an argument fragment. Some providers resend the
    accumulated string. A prefix of what we already stored is that snapshot,
    so only the new tail is a Responses delta.
    """

    if not incoming:
        return ""
    if incoming.startswith(current):
        return incoming[len(current) :]
    return incoming


def _chat_chunk_delta_text(event: JsonObject) -> str:
    choices = event.get("choices")
    if not is_json_list(choices) or not choices:
        return ""
    first = choices[0]
    if not is_json_mapping(first):
        return ""
    delta = first.get("delta")
    if not is_json_mapping(delta):
        return ""
    content = delta.get("content")
    return content if isinstance(content, str) else ""
