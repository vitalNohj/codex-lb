from __future__ import annotations

import time
import uuid
from collections.abc import Mapping

from app.core.openai.chat_requests import ChatCompletionsRequest
from app.core.openai.requests import ResponsesRequest
from app.core.types import JsonObject, JsonValue
from app.core.utils.json_guards import is_json_list, is_json_mapping

_OUTPUT_TEXT_TYPE = "output_text"


def responses_to_omniroute_chat_request(
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
    for item in input_value:
        message = _input_item_to_message(item)
        if message is not None:
            messages.append(message)
    return messages


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


def omniroute_chat_to_responses_result(chat_body: JsonValue, *, model: str) -> JsonObject:
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


class ResponsesStreamSynthesizer:
    """Synthesize the minimal Responses event sequence from chat SSE deltas.

    Consumes parsed OmniRoute chat-completion chunk objects and ``[DONE]``
    sentinels (as produced by the shared SSE decoder) and yields Responses
    event mappings: ``response.created``, ``response.output_item.added``,
    ``response.output_text.delta`` (one per content delta),
    ``response.output_item.done``, and a terminal ``response.completed``.
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
                    "output_index": 0,
                    "content_index": 0,
                    "delta": delta_text,
                }
            )
        return out

    def finish(self) -> list[JsonObject]:
        return self._finish()

    def _finish(self) -> list[JsonObject]:
        if self._completed:
            return []
        self._completed = True
        out: list[JsonObject] = []
        if not self._created_emitted:
            out.append(self._response_created())
            self._created_emitted = True
        if not self._item_added:
            out.append(self._output_item_added())
            self._item_added = True
        out.append(self._output_item_done())
        out.append(self._response_completed())
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
            "output": [self._message_item()] if self._item_added else [],
        }
        if self._usage is not None:
            response["usage"] = self._usage
        return response

    def _response_created(self) -> JsonObject:
        return {"type": "response.created", "response": self._response_object("in_progress")}

    def _output_item_added(self) -> JsonObject:
        return {
            "type": "response.output_item.added",
            "output_index": 0,
            "item": {
                "id": self._item_id,
                "type": "message",
                "status": "in_progress",
                "role": "assistant",
                "content": [],
            },
        }

    def _output_item_done(self) -> JsonObject:
        return {"type": "response.output_item.done", "output_index": 0, "item": self._message_item()}

    def _response_completed(self) -> JsonObject:
        return {"type": "response.completed", "response": self._response_object("completed")}


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
