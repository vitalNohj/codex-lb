"""Translate between the Responses API and chat-completions providers.

Claude, OpenRouter, OrcaRouter, Ollama, OpenAI-compatible endpoints, OmniRoute
and OpenCode Go only speak Chat Completions. A Responses request for one of
their models is rewritten into a chat request here, and the chat answer is
rewritten back into a Responses result or event stream.

Every Responses field either maps onto its chat equivalent or is rejected with
an HTTP 400 (:class:`~app.core.openai.exceptions.ClientPayloadError`). A field
is dropped only when it is a hint the chat side has no way to honour and that
cannot change what the client asked for (``text.verbosity``,
``reasoning.summary``) or opaque provider state no chat upstream can read
(encrypted ``reasoning`` items). Silently dropping anything else would run a
different turn from the one the client sent.

The mapping follows LiteLLM's Responses-to-chat bridge
(``litellm/responses/litellm_completion_transformation``) and CLIProxyAPI's
Responses translators (``internal/translator/*/openai/responses``):

- ``reasoning.effort`` -> ``reasoning_effort``; ``max_output_tokens`` ->
  ``max_tokens``; ``temperature`` and ``top_p`` as is; ``text.format`` ->
  ``response_format``.
- Chat ``prompt_tokens_details.cached_tokens`` and
  ``completion_tokens_details.reasoning_tokens`` -> Responses
  ``input_tokens_details.cached_tokens`` and
  ``output_tokens_details.reasoning_tokens``.
- ``previous_response_id``, ``conversation`` and ``store: true`` need
  server-side response storage that a chat upstream does not have, so they are
  rejected, as OpenRouter's Responses API does.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, cast

from pydantic import ValidationError

from app.core.openai.chat_requests import ChatCompletionsRequest
from app.core.openai.requests import ResponsesRequest
from app.core.types import JsonValue
from app.core.utils.json_guards import is_json_list, is_json_mapping
from app.modules.proxy.responses_chat_tools import (
    CUSTOM_TOOL_INPUT_FIELD,
    ChatToolShape,
    chat_bridge_error,
    chat_tool_wire_name,
    translate_responses_tool_choice,
    translate_responses_tools,
)

_Json = dict[str, JsonValue]

_OUTPUT_TEXT_TYPE = "output_text"
_REFUSAL_TYPE = "refusal"
_TEXT_PART_TYPES = frozenset({"input_text", "output_text", "text"})
_CHAT_ROLES = frozenset({"system", "developer", "user", "assistant", "tool"})
_CALL_ITEM_TYPES = frozenset({"function_call", "custom_tool_call"})
_CALL_OUTPUT_ITEM_TYPES = frozenset({"function_call_output", "custom_tool_call_output"})

# Input items carried for the upstream's own benefit that a chat upstream
# cannot read. ``reasoning`` holds encrypted chain-of-thought only the model
# that wrote it can decrypt (CLIProxyAPI's chat translators drop it too);
# ``web_search_call`` records a hosted search whose results are not in the
# item. Neither changes the visible conversation, which the surrounding
# message and tool items still carry, so they are omitted rather than
# rejected: rejecting them would break every session that switches to a chat
# model mid-conversation.
_OPAQUE_INPUT_ITEM_TYPES = frozenset({"reasoning", "web_search_call"})


@dataclass(frozen=True, slots=True)
class ResponsesChatTranslation:
    """A chat request built from a Responses request.

    ``tool_shapes`` maps each chat function name back to the Responses tool it
    stands for, so the answer's tool calls can be returned in their original
    shape. ``response_echo`` holds the request parameters a Responses object
    repeats back (``tools``, ``tool_choice``, ``parallel_tool_calls`` ...); the
    OpenAI SDK's ``Response`` model requires the first three.
    """

    chat_request: ChatCompletionsRequest
    tool_shapes: Mapping[str, ChatToolShape] = field(default_factory=dict)
    response_echo: Mapping[str, JsonValue] = field(default_factory=dict)


def translate_responses_to_chat(
    payload: ResponsesRequest,
    effective_model: str,
) -> ResponsesChatTranslation:
    """Translate a normalized Responses request into a chat request.

    Raises :class:`~app.core.openai.exceptions.ClientPayloadError` for any part
    of the request a chat-completions provider cannot serve.
    """

    model = effective_model.strip()
    _reject_stateful_fields(payload, model=model)

    input_items = payload.input if is_json_list(payload.input) else None
    declared_tools: list[JsonValue] = list(payload.tools)
    if input_items is not None:
        declared_tools.extend(_additional_tools(input_items))
    tools = translate_responses_tools(declared_tools, model=model)

    messages: list[JsonValue] = []
    instructions = payload.instructions.strip() if isinstance(payload.instructions, str) else ""
    if instructions:
        messages.append({"role": "system", "content": instructions})
    messages.extend(_input_to_messages(payload.input, model=model))
    if not messages:
        messages.append({"role": "user", "content": ""})

    data: _Json = {"model": model, "messages": messages}
    if tools.tools:
        data["tools"] = tools.tools
        if payload.tool_choice is not None:
            data["tool_choice"] = translate_responses_tool_choice(payload.tool_choice, shapes=tools.shapes)
        if payload.parallel_tool_calls is not None:
            data["parallel_tool_calls"] = payload.parallel_tool_calls
    elif payload.tool_choice not in (None, "auto", "none"):
        # Every declared tool was a cached web search, which is dropped. A
        # choice that forces a tool call cannot be met without tools.
        raise chat_bridge_error(
            f"tool_choice requires a tool, but no tool can be sent to model '{model}'.",
            param="tool_choice",
        )
    data.update(_sampling_fields(payload))
    if payload.service_tier is not None:
        data["service_tier"] = payload.service_tier
    if payload.stream is not None:
        data["stream"] = payload.stream
    prompt_cache_key = payload.prompt_cache_key.strip() if isinstance(payload.prompt_cache_key, str) else ""
    if prompt_cache_key:
        # The conversation's sticky identity: CLIProxyAPI credential routing
        # pins on it, and OpenAI-compatible upstreams use it for prompt caching.
        data["prompt_cache_key"] = prompt_cache_key
    try:
        chat_request = ChatCompletionsRequest.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0] if exc.errors() else None
        message = str(first.get("msg")) if first else str(exc)
        raise chat_bridge_error(
            f"The request cannot be sent to model '{model}': {message}",
            param=None,
            code="invalid_request_error",
        ) from exc
    return ResponsesChatTranslation(
        chat_request=chat_request,
        tool_shapes=dict(tools.shapes),
        response_echo=_response_echo(payload),
    )


def _response_echo(payload: ResponsesRequest) -> _Json:
    """Request parameters a Responses object repeats back, as the API does."""

    echo: _Json = {
        "tools": list(payload.tools),
        "tool_choice": payload.tool_choice if payload.tool_choice is not None else "auto",
        "parallel_tool_calls": payload.parallel_tool_calls if payload.parallel_tool_calls is not None else True,
        "store": False,
    }
    if isinstance(payload.instructions, str) and payload.instructions:
        echo["instructions"] = payload.instructions
    extra = payload.model_extra or {}
    for name in ("temperature", "top_p", "max_output_tokens"):
        value = extra.get(name)
        if value is not None:
            echo[name] = value
    if payload.text is not None:
        echo["text"] = payload.text.model_dump(mode="json", by_alias=True, exclude_none=True)
    if payload.reasoning is not None:
        echo["reasoning"] = payload.reasoning.model_dump(mode="json", exclude_none=True)
    return echo


_DEFAULT_RESPONSE_ECHO: Mapping[str, JsonValue] = {"tools": [], "tool_choice": "auto", "parallel_tool_calls": True}


def responses_to_chat_request(
    payload: ResponsesRequest,
    effective_model: str,
) -> ChatCompletionsRequest:
    """The chat request half of :func:`translate_responses_to_chat`."""

    return translate_responses_to_chat(payload, effective_model).chat_request


def _reject_stateful_fields(payload: ResponsesRequest, *, model: str) -> None:
    """Refuse fields that need server-side response storage.

    A chat upstream keeps no responses, so ``previous_response_id`` would run
    the turn without the history it names, and ``store: true`` would promise a
    stored response that can never be retrieved. Answering such a request
    anyway is the silent failure this rejects: the client would bill a full
    turn that has lost its context.
    """

    suffix = f"is not supported for model '{model}', which is served through a chat-completions provider."
    if payload.previous_response_id:
        raise chat_bridge_error(
            f"previous_response_id {suffix} Send the full conversation in input instead.",
            param="previous_response_id",
            code="unsupported_parameter",
        )
    if payload.conversation:
        raise chat_bridge_error(
            f"conversation {suffix} Send the full conversation in input instead.",
            param="conversation",
            code="unsupported_parameter",
        )
    if payload.client_requested_store:
        raise chat_bridge_error(
            f"store: true {suffix} Set store to false.",
            param="store",
            code="unsupported_parameter",
        )


def _sampling_fields(payload: ResponsesRequest) -> _Json:
    fields: _Json = {}
    reasoning = payload.reasoning
    if reasoning is not None and isinstance(reasoning.effort, str) and reasoning.effort.strip():
        fields["reasoning_effort"] = reasoning.effort.strip()
    extra = payload.model_extra or {}
    max_output_tokens = extra.get("max_output_tokens")
    if max_output_tokens is not None:
        if not isinstance(max_output_tokens, int) or isinstance(max_output_tokens, bool) or max_output_tokens < 1:
            raise chat_bridge_error("max_output_tokens must be a positive integer.", param="max_output_tokens")
        fields["max_tokens"] = max_output_tokens
    for name in ("temperature", "top_p"):
        value = extra.get(name)
        if value is None:
            continue
        if not isinstance(value, int | float) or isinstance(value, bool):
            raise chat_bridge_error(f"{name} must be a number.", param=name)
        fields[name] = value
    response_format = _response_format(payload)
    if response_format is not None:
        fields["response_format"] = response_format
    return fields


def _response_format(payload: ResponsesRequest) -> _Json | None:
    """Map ``text.format`` onto chat ``response_format``.

    Responses declares a JSON schema flat (``{"type": "json_schema", "name",
    "schema", "strict"}``); chat nests it under ``json_schema``.
    """

    if payload.text is None or payload.text.format is None:
        return None
    text_format = cast(_Json, payload.text.format.model_dump(mode="json", by_alias=True, exclude_none=True))
    format_type = text_format.get("type")
    if format_type in (None, "text"):
        return None
    if format_type == "json_object":
        return {"type": "json_object"}
    if format_type != "json_schema":
        raise chat_bridge_error(
            f"text.format type '{format_type}' is not supported by chat-completions providers.",
            param="text.format.type",
        )
    schema = text_format.get("schema")
    if not is_json_mapping(schema):
        raise chat_bridge_error("text.format.schema must be a JSON schema object.", param="text.format.schema")
    name = text_format.get("name")
    json_schema: _Json = {"name": name if isinstance(name, str) and name else "response", "schema": schema}
    for key in ("strict", "description"):
        value = text_format.get(key)
        if value is not None:
            json_schema[key] = value
    return {"type": "json_schema", "json_schema": json_schema}


def _additional_tools(input_items: list[JsonValue]) -> list[JsonValue]:
    """Tools declared inside the input by an ``additional_tools`` item.

    Codex declares tools this way for models served over Responses Lite. They
    are as real as top-level tools, so they join the chat ``tools`` list.
    """

    tools: list[JsonValue] = []
    for item in input_items:
        if is_json_mapping(item) and item.get("type") == "additional_tools":
            listed = item.get("tools")
            if is_json_list(listed):
                tools.extend(listed)
    return tools


def _input_to_messages(input_value: JsonValue, *, model: str) -> list[JsonValue]:
    if isinstance(input_value, str):
        text = input_value.strip()
        return [{"role": "user", "content": text}] if text else []
    if not is_json_list(input_value):
        return []
    messages: list[JsonValue] = []
    pending_tool_calls: list[JsonValue] = []
    for index, item in enumerate(input_value):
        param = f"input[{index}]"
        if not is_json_mapping(item):
            raise chat_bridge_error("Each input item must be an object.", param=param)
        item_type = item.get("type")
        if item_type in _CALL_ITEM_TYPES:
            pending_tool_calls.append(_call_item_to_tool_call(item, param=param))
            continue
        if item_type in _OPAQUE_INPUT_ITEM_TYPES or item_type == "additional_tools":
            continue
        _flush_pending_tool_calls(messages, pending_tool_calls)
        if item_type in _CALL_OUTPUT_ITEM_TYPES:
            messages.append(_call_output_to_message(item, param=param))
            continue
        if item_type in (None, "message"):
            message = _message_item_to_message(item, param=param)
        elif item_type == "agent_message":
            message = _agent_message_to_message(item, param=param)
        else:
            raise chat_bridge_error(
                f"Input item type '{item_type}' is not supported for model '{model}', which is "
                "served through a chat-completions provider.",
                param=param,
            )
        if message is not None:
            messages.append(message)
    _flush_pending_tool_calls(messages, pending_tool_calls)
    return messages


def _call_item_to_tool_call(item: Mapping[str, JsonValue], *, param: str) -> _Json:
    """Map a ``function_call`` or ``custom_tool_call`` onto a chat tool call.

    A custom tool call carries freeform ``input``; on the chat side the tool is
    a function taking ``{"input": <string>}``, so the input is wrapped the same
    way the tool was declared.
    """

    name = item.get("name")
    call_id = item.get("call_id")
    if not isinstance(name, str) or not name:
        raise chat_bridge_error("A tool call item must have a name.", param=f"{param}.name")
    if not isinstance(call_id, str) or not call_id:
        raise chat_bridge_error("A tool call item must have a call_id.", param=f"{param}.call_id")
    if item.get("type") == "custom_tool_call":
        tool_input = item.get("input")
        argument_text = json.dumps(
            {CUSTOM_TOOL_INPUT_FIELD: tool_input if isinstance(tool_input, str) else ""},
            ensure_ascii=False,
            separators=(",", ":"),
        )
    else:
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
        "function": {"name": chat_tool_wire_name(name, item.get("namespace")), "arguments": argument_text},
    }


def _call_output_to_message(item: Mapping[str, JsonValue], *, param: str) -> _Json:
    call_id = item.get("call_id")
    if not isinstance(call_id, str) or not call_id:
        raise chat_bridge_error("A tool output item must have a call_id.", param=f"{param}.call_id")
    return {"role": "tool", "tool_call_id": call_id, "content": _tool_output_content(item.get("output"))}


def _tool_output_content(output: JsonValue) -> JsonValue:
    """Chat content for a tool result.

    Text-only output keeps its parts (one part collapses to a string). Output
    with other parts (images) is serialized as JSON text, because a chat tool
    message accepts text only; that keeps every part visible to the model.
    """

    if isinstance(output, str):
        return output
    if output is None:
        return ""
    if is_json_list(output):
        texts = [_part_text(part) for part in output]
        if texts and all(text is not None for text in texts):
            return _text_content(cast(list[str], texts))
    return json.dumps(output, ensure_ascii=False, separators=(",", ":"))


def _part_text(part: JsonValue) -> str | None:
    if not is_json_mapping(part) or part.get("type") not in _TEXT_PART_TYPES:
        return None
    text = part.get("text")
    return text if isinstance(text, str) else None


def _text_content(texts: list[str]) -> JsonValue:
    """One text part stays a plain string; several stay separate parts.

    Joining parts would merge their text into one run ("part A" + "part B"
    became "part Apart B"). A single part is sent as a string so the common
    one-part turn is byte-identical to before and keeps its prompt-cache prefix.
    """

    if len(texts) == 1:
        return texts[0]
    return [{"type": "text", "text": text} for text in texts]


def _flush_pending_tool_calls(messages: list[JsonValue], pending: list[JsonValue]) -> None:
    """Attach accumulated tool calls to the preceding assistant turn.

    Chat completions put every tool call on the assistant message that
    requested them. Responses lists those calls as sibling items, so a run of
    call items is folded back onto that message. A call with no preceding
    assistant message becomes its own assistant turn.
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


def _message_item_to_message(item: Mapping[str, JsonValue], *, param: str) -> _Json | None:
    role = item.get("role")
    role_name = role if isinstance(role, str) and role in _CHAT_ROLES else "user"
    content = _message_content(item.get("content"), param=f"{param}.content")
    if content is None:
        return None
    return {"role": role_name, "content": content}


def _agent_message_to_message(item: Mapping[str, JsonValue], *, param: str) -> _Json | None:
    """A Codex multi-agent ``agent_message`` becomes a user turn.

    CLIProxyAPI's ``normalizeCodexAgentMessages`` does the same, so the
    delegated task text reaches the model instead of being dropped.
    """

    content = _message_content(item.get("content"), param=f"{param}.content")
    if content is None:
        return None
    return {"role": "user", "content": content}


def _message_content(content: JsonValue, *, param: str) -> JsonValue | None:
    """Translate a Responses message content value into chat content.

    Text-only content stays text (see :func:`_text_content`); content with an
    image or file is a chat content-parts array.
    """

    if isinstance(content, str):
        return content
    if is_json_mapping(content):
        content = [content]
    if not is_json_list(content):
        return None
    parts: list[_Json] = []
    for index, part in enumerate(content):
        parts.append(_content_part_to_chat(part, param=f"{param}[{index}]"))
    if not parts:
        return None
    if all(part.get("type") == "text" for part in parts):
        return _text_content([cast(str, part["text"]) for part in parts])
    return cast(JsonValue, parts)


def _content_part_to_chat(part: JsonValue, *, param: str) -> _Json:
    if isinstance(part, str):
        return {"type": "text", "text": part}
    if not is_json_mapping(part):
        raise chat_bridge_error("Each content part must be an object.", param=param)
    part_type = part.get("type")
    if part_type in _TEXT_PART_TYPES or (part_type is None and isinstance(part.get("text"), str)):
        text = part.get("text")
        if not isinstance(text, str):
            raise chat_bridge_error("A text content part must have text.", param=f"{param}.text")
        return {"type": "text", "text": text}
    if part_type == _REFUSAL_TYPE:
        refusal = part.get("refusal")
        return {"type": "text", "text": refusal if isinstance(refusal, str) else ""}
    if part_type in ("input_image", "image_url"):
        return _image_part_to_chat(part, param=param)
    if part_type == "input_file":
        return _file_part_to_chat(part, param=param)
    raise chat_bridge_error(
        f"Content part type '{part_type}' is not supported by chat-completions providers.",
        param=param,
    )


def _image_part_to_chat(part: Mapping[str, JsonValue], *, param: str) -> _Json:
    """Map a Responses ``input_image``/``image_url`` part to a chat image part."""

    image_url = part.get("image_url")
    if isinstance(image_url, str):
        url: JsonValue = image_url
    elif is_json_mapping(image_url):
        url = image_url.get("url")
    else:
        url = None
    if not isinstance(url, str) or not url:
        if part.get("file_id"):
            raise chat_bridge_error(
                "input_image with a file_id is not supported by chat-completions providers; "
                "send the image as a URL or data URL.",
                param=f"{param}.file_id",
            )
        raise chat_bridge_error("An image content part must have an image_url.", param=f"{param}.image_url")
    image_payload: _Json = {"url": url}
    detail = part.get("detail")
    if isinstance(detail, str) and detail:
        image_payload["detail"] = detail
    elif is_json_mapping(image_url):
        detail_value = image_url.get("detail")
        if isinstance(detail_value, str) and detail_value:
            image_payload["detail"] = detail_value
    return {"type": "image_url", "image_url": image_payload}


def _file_part_to_chat(part: Mapping[str, JsonValue], *, param: str) -> _Json:
    """Map an ``input_file`` with inline data to a chat ``file`` part.

    Chat Completions accepts inline ``file_data`` (a base64 data URL) with a
    ``filename``; LiteLLM maps ``input_file`` the same way. A ``file_id``
    names an upload stored with OpenAI and a ``file_url`` asks the server to
    fetch the file; a chat upstream can do neither.
    """

    file_data = part.get("file_data")
    if isinstance(file_data, str) and file_data:
        file_payload: _Json = {"file_data": file_data}
        filename = part.get("filename")
        if isinstance(filename, str) and filename:
            file_payload["filename"] = filename
        return {"type": "file", "file": file_payload}
    unsupported = "file_id" if part.get("file_id") else "file_url" if part.get("file_url") else None
    if unsupported is not None:
        raise chat_bridge_error(
            f"input_file with a {unsupported} is not supported by chat-completions providers; "
            "send the file inline as file_data.",
            param=f"{param}.{unsupported}",
        )
    raise chat_bridge_error("An input_file content part must have file_data.", param=f"{param}.file_data")


# --------------------------------------------------------------------------
# Chat answer -> Responses result
# --------------------------------------------------------------------------


def chat_to_responses_result(
    chat_body: JsonValue,
    *,
    model: str,
    translation: ResponsesChatTranslation | None = None,
) -> _Json:
    """Wrap a chat-completion JSON body in a Responses result.

    ``translation`` is the request translation the answer belongs to; it maps
    tool calls back to their Responses shape and supplies the echoed request
    parameters.
    """

    shapes = translation.tool_shapes if translation is not None else {}
    choice = _first_choice(chat_body)
    message = choice.get("message") if choice is not None else None
    output: list[JsonValue] = []
    if is_json_mapping(message):
        content_parts = _message_output_parts(message)
        if content_parts:
            output.append(
                {
                    "id": f"msg_{uuid.uuid4().hex}",
                    "type": "message",
                    "status": "completed",
                    "role": "assistant",
                    "content": content_parts,
                }
            )
        raw_tool_calls = message.get("tool_calls")
        if is_json_list(raw_tool_calls):
            output.extend(_chat_tool_calls_to_output_items(raw_tool_calls, shapes))

    incomplete_reason = _incomplete_reason(choice.get("finish_reason") if choice is not None else None)
    result: _Json = {
        "id": _chat_response_id(chat_body),
        "object": "response",
        "created_at": int(time.time()),
        "status": "incomplete" if incomplete_reason else "completed",
        "model": model,
        "output": output,
        "incomplete_details": {"reason": incomplete_reason} if incomplete_reason else None,
        "error": None,
        **_echo(translation),
    }
    usage = _usage_to_responses_usage(chat_body.get("usage")) if is_json_mapping(chat_body) else None
    if usage is not None:
        result["usage"] = usage
    return result


def _echo(translation: ResponsesChatTranslation | None) -> Mapping[str, JsonValue]:
    if translation is None or not translation.response_echo:
        return _DEFAULT_RESPONSE_ECHO
    return translation.response_echo


def _message_output_parts(message: Mapping[str, JsonValue]) -> list[JsonValue]:
    parts: list[JsonValue] = []
    content = message.get("content")
    if isinstance(content, str) and content:
        parts.append(_output_text_part(content))
    elif is_json_list(content):
        for part in content:
            text = _part_text(part)
            if text:
                parts.append(_output_text_part(text))
    refusal = message.get("refusal")
    if isinstance(refusal, str) and refusal:
        parts.append({"type": _REFUSAL_TYPE, "refusal": refusal})
    return parts


def _output_text_part(text: str) -> _Json:
    return {"type": _OUTPUT_TEXT_TYPE, "text": text, "annotations": []}


def _chat_tool_calls_to_output_items(
    raw_tool_calls: list[JsonValue],
    shapes: Mapping[str, ChatToolShape],
) -> list[JsonValue]:
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
            _call_output_item(
                item_id=None,
                call_id=call_id if isinstance(call_id, str) and call_id else f"call_{uuid.uuid4().hex}",
                wire_name=name if isinstance(name, str) else "",
                arguments=arguments if isinstance(arguments, str) else "",
                shapes=shapes,
                status="completed",
            )
        )
    return items


def _call_output_item(
    *,
    item_id: str | None,
    call_id: str,
    wire_name: str,
    arguments: str,
    shapes: Mapping[str, ChatToolShape],
    status: str,
) -> _Json:
    """A Responses call item for a chat tool call, in the tool's own shape."""

    shape = shapes.get(wire_name)
    if shape is not None and shape.kind == "custom":
        item: _Json = {
            "id": item_id or f"ctc_{uuid.uuid4().hex}",
            "type": "custom_tool_call",
            "status": status,
            "call_id": call_id,
            "name": shape.name,
            "input": custom_tool_input(arguments),
        }
    else:
        item = {
            "id": item_id or f"fc_{uuid.uuid4().hex}",
            "type": "function_call",
            "status": status,
            "call_id": call_id,
            "name": shape.name if shape is not None else wire_name,
            "arguments": arguments,
        }
    if shape is not None and shape.namespace:
        item["namespace"] = shape.namespace
    return item


def custom_tool_input(arguments: str) -> str:
    """The freeform input of a custom tool call from its chat arguments.

    The model was given a function taking ``{"input": <string>}``. If it
    answered with something else, the raw arguments are passed on rather than
    discarded, so the tool can still report what it received.
    """

    try:
        parsed = json.loads(arguments) if arguments else {}
    except ValueError:
        return arguments
    if is_json_mapping(parsed):
        value = parsed.get(CUSTOM_TOOL_INPUT_FIELD)
        if isinstance(value, str):
            return value
    return arguments


def _incomplete_reason(finish_reason: JsonValue) -> str | None:
    if finish_reason == "length":
        return "max_output_tokens"
    if finish_reason == "content_filter":
        return "content_filter"
    return None


def _first_choice(chat_body: JsonValue) -> Mapping[str, JsonValue] | None:
    if not is_json_mapping(chat_body):
        return None
    choices = chat_body.get("choices")
    if not is_json_list(choices) or not choices:
        return None
    first = choices[0]
    return first if is_json_mapping(first) else None


def _chat_response_id(chat_body: JsonValue) -> str:
    if is_json_mapping(chat_body):
        raw_id = chat_body.get("id")
        if isinstance(raw_id, str) and raw_id:
            return f"resp_{raw_id}"
    return f"resp_{uuid.uuid4().hex}"


def _usage_to_responses_usage(usage: JsonValue) -> _Json | None:
    """Map chat usage onto Responses usage, keeping the token breakdowns.

    ``cached_tokens`` is how a client sees prompt-cache hits; without it a
    sticky-session regression that re-bills the whole prompt is invisible.
    Chat sends it in ``prompt_tokens_details`` and the reasoning count in
    ``completion_tokens_details``; Responses names them
    ``input_tokens_details`` and ``output_tokens_details``. Cache writes
    (``cache_write_tokens``, or CLIProxyAPI's ``cached_creation_tokens``) map to
    ``input_tokens_details.cache_write_tokens``. The detail objects are always
    present, as the Responses API sends them.
    """

    if not is_json_mapping(usage):
        return None
    prompt = _int_or_none(usage.get("prompt_tokens"))
    completion = _int_or_none(usage.get("completion_tokens"))
    total = _int_or_none(usage.get("total_tokens"))
    if prompt is None and completion is None and total is None:
        return None
    input_tokens = prompt or 0
    output_tokens = completion or 0
    prompt_details = usage.get("prompt_tokens_details")
    completion_details = usage.get("completion_tokens_details")
    cached = _detail_int(prompt_details, "cached_tokens")
    cache_write = _detail_int(prompt_details, "cache_write_tokens", "cached_creation_tokens", "cache_creation_tokens")
    reasoning = _detail_int(completion_details, "reasoning_tokens")
    return {
        "input_tokens": input_tokens,
        "input_tokens_details": {"cached_tokens": cached, "cache_write_tokens": cache_write},
        "output_tokens": output_tokens,
        "output_tokens_details": {"reasoning_tokens": reasoning},
        "total_tokens": total if total is not None else input_tokens + output_tokens,
    }


def _int_or_none(value: JsonValue) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _detail_int(details: JsonValue, *keys: str) -> int:
    if not is_json_mapping(details):
        return 0
    for key in keys:
        value = _int_or_none(details.get(key))
        if value is not None:
            return value
    return 0


# --------------------------------------------------------------------------
# Chat stream -> Responses event stream
# --------------------------------------------------------------------------

_ContentKind = Literal["output_text", "refusal"]


@dataclass(slots=True)
class _StreamContentPart:
    kind: _ContentKind
    content_index: int
    text: str = ""


@dataclass(slots=True)
class _StreamToolCall:
    output_index: int
    item_id: str
    call_id: str
    name: str
    arguments: str = ""
    added: bool = False
    streamed_arguments: int = 0


@dataclass(slots=True)
class _StreamMessage:
    output_index: int
    item_id: str
    parts: list[_StreamContentPart] = field(default_factory=list)

    def part(self, kind: _ContentKind) -> _StreamContentPart | None:
        for part in self.parts:
            if part.kind == kind:
                return part
        return None


class ResponsesStreamSynthesizer:
    """Synthesize a Responses event stream from chat SSE chunks.

    Consumes parsed chat-completion chunk objects and ``[DONE]`` sentinels (as
    produced by the shared SSE decoder) and yields the event sequence the
    Responses API streams, in the order the OpenAI SDK's streaming parser
    expects:

    ``response.created``, ``response.in_progress``; per message
    ``response.output_item.added``, ``response.content_part.added``,
    ``response.output_text.delta`` ... ``response.output_text.done``,
    ``response.content_part.done``, ``response.output_item.done`` (and the
    ``response.refusal.*`` equivalents); per function call
    ``response.output_item.added``, ``response.function_call_arguments.delta``
    ... ``response.function_call_arguments.done``,
    ``response.output_item.done``; per custom tool call the
    ``response.custom_tool_call_input.*`` events; and one terminal
    ``response.completed``, ``response.incomplete`` or ``response.failed``.
    Every event carries a ``sequence_number`` counting from zero.
    """

    def __init__(self, *, model: str, translation: ResponsesChatTranslation | None = None) -> None:
        self._model = model
        self._tool_shapes: Mapping[str, ChatToolShape] = translation.tool_shapes if translation is not None else {}
        self._echo = _echo(translation)
        self._response_id = f"resp_{uuid.uuid4().hex}"
        self._created_at = int(time.time())
        self._sequence_number = 0
        self._created_emitted = False
        self._completed = False
        self._usage: _Json | None = None
        self._finish_reason: str | None = None
        self._message: _StreamMessage | None = None
        self._next_output_index = 0
        self._tool_calls: dict[int, _StreamToolCall] = {}

    def feed(self, event: Mapping[str, JsonValue] | str) -> list[_Json]:
        if event == "[DONE]":
            return self._finish()
        if not is_json_mapping(event) or self._completed:
            return []
        if "error" in event and "choices" not in event:
            # A chat provider reports a mid-stream failure as a bare error
            # chunk; finishing normally afterwards would call it completed.
            return self.fail(event.get("error"))
        out: list[_Json] = []
        self._ensure_created(out)
        mapped_usage = _usage_to_responses_usage(event.get("usage"))
        if mapped_usage is not None:
            self._usage = mapped_usage
        choice = _first_choice(event)
        if choice is None:
            return out
        finish_reason = choice.get("finish_reason")
        if isinstance(finish_reason, str) and finish_reason:
            self._finish_reason = finish_reason
        delta = choice.get("delta")
        if not is_json_mapping(delta):
            return out
        content = delta.get("content")
        if isinstance(content, str) and content:
            out.extend(self._content_delta(_OUTPUT_TEXT_TYPE, content))
        refusal = delta.get("refusal")
        if isinstance(refusal, str) and refusal:
            out.extend(self._content_delta(_REFUSAL_TYPE, refusal))
        tool_calls = delta.get("tool_calls")
        if is_json_list(tool_calls):
            for call in tool_calls:
                if is_json_mapping(call):
                    out.extend(self._tool_call_delta(call))
        return out

    def finish(self, *, upstream_completed: bool = True) -> list[_Json]:
        """Emit the terminal events for this response.

        ``upstream_completed`` must reflect whether the upstream actually sent
        its ``[DONE]`` sentinel. A stream that ended early - a truncated body, a
        dropped connection - is **not** a completed response, and saying so would
        tell the client its partial answer is the whole answer, with nothing in
        the payload to contradict it. That is worse than an explicit failure,
        because it is silent and indistinguishable from success.
        """

        return self._finish(upstream_completed=upstream_completed)

    def fail(self, error: JsonValue) -> list[_Json]:
        """Terminate the stream with ``response.failed`` for an upstream error.

        A chat provider reports a mid-stream failure as a bare ``{"error":
        ...}`` chunk. A Responses client waits for a terminal response event,
        so the error is carried in ``response.failed`` instead.
        """

        if self._completed:
            return []
        self._completed = True
        out: list[_Json] = []
        self._ensure_created(out)
        response = self._response_object("failed")
        response["error"] = _response_error(error)
        out.append(self._event({"type": "response.failed", "response": response}))
        return out

    def _finish(self, *, upstream_completed: bool = True) -> list[_Json]:
        if self._completed:
            return []
        self._completed = True
        out: list[_Json] = []
        self._ensure_created(out)
        if self._message is None and not self._tool_calls:
            # An answer with no content is still one empty assistant message.
            out.extend(self._open_content_part(_OUTPUT_TEXT_TYPE))
        # Items close in output order. Sort the open items before closing
        # them: closing assigns sequence numbers, so sorting the finished
        # event batches instead would emit decreasing numbers whenever a tool
        # call was opened before the assistant text.
        open_items: list[_StreamMessage | _StreamToolCall] = list(self._tool_calls.values())
        if self._message is not None:
            open_items.append(self._message)
        for item in sorted(open_items, key=lambda entry: entry.output_index):
            if isinstance(item, _StreamMessage):
                out.extend(self._close_message(item))
            else:
                out.extend(self._close_tool_call(item))
        incomplete_reason = "interrupted" if not upstream_completed else _incomplete_reason(self._finish_reason)
        if incomplete_reason is None:
            out.append(self._event({"type": "response.completed", "response": self._response_object("completed")}))
            return out
        # ``response.incomplete`` is the protocol's terminal event for a
        # response that stopped short. ``interrupted`` means the upstream
        # stream ended without ``[DONE]``; it deliberately does not claim a
        # cause this layer cannot observe. A chat ``finish_reason`` of
        # ``length`` or ``content_filter`` is reported as its Responses reason.
        response = self._response_object("incomplete")
        response["incomplete_details"] = {"reason": incomplete_reason}
        out.append(self._event({"type": "response.incomplete", "response": response}))
        return out

    # -- events -------------------------------------------------------------

    def _event(self, event: _Json) -> _Json:
        event["sequence_number"] = self._sequence_number
        self._sequence_number += 1
        return event

    def _ensure_created(self, out: list[_Json]) -> None:
        if self._created_emitted:
            return
        self._created_emitted = True
        out.append(self._event({"type": "response.created", "response": self._response_object("in_progress")}))
        out.append(self._event({"type": "response.in_progress", "response": self._response_object("in_progress")}))

    def _allocate_output_index(self) -> int:
        output_index = self._next_output_index
        self._next_output_index += 1
        return output_index

    def _content_delta(self, kind: _ContentKind, delta: str) -> list[_Json]:
        out = self._open_content_part(kind)
        message = cast(_StreamMessage, self._message)
        part = cast(_StreamContentPart, message.part(kind))
        part.text += delta
        event: _Json = {
            "type": "response.output_text.delta" if kind == _OUTPUT_TEXT_TYPE else "response.refusal.delta",
            "item_id": message.item_id,
            "output_index": message.output_index,
            "content_index": part.content_index,
            "delta": delta,
        }
        if kind == _OUTPUT_TEXT_TYPE:
            event["logprobs"] = []
        out.append(self._event(event))
        return out

    def _open_content_part(self, kind: _ContentKind) -> list[_Json]:
        out: list[_Json] = []
        if self._message is None:
            self._message = _StreamMessage(
                output_index=self._allocate_output_index(), item_id=f"msg_{uuid.uuid4().hex}"
            )
            out.append(
                self._event(
                    {
                        "type": "response.output_item.added",
                        "output_index": self._message.output_index,
                        "item": {
                            "id": self._message.item_id,
                            "type": "message",
                            "status": "in_progress",
                            "role": "assistant",
                            "content": [],
                        },
                    }
                )
            )
        message = self._message
        if message.part(kind) is None:
            part = _StreamContentPart(kind=kind, content_index=len(message.parts))
            message.parts.append(part)
            out.append(
                self._event(
                    {
                        "type": "response.content_part.added",
                        "item_id": message.item_id,
                        "output_index": message.output_index,
                        "content_index": part.content_index,
                        "part": _empty_content_part(kind),
                    }
                )
            )
        return out

    def _close_message(self, message: _StreamMessage) -> list[_Json]:
        out: list[_Json] = []
        for part in message.parts:
            done: _Json
            if part.kind == _OUTPUT_TEXT_TYPE:
                done = {
                    "type": "response.output_text.done",
                    "item_id": message.item_id,
                    "output_index": message.output_index,
                    "content_index": part.content_index,
                    "text": part.text,
                    "logprobs": [],
                }
            else:
                done = {
                    "type": "response.refusal.done",
                    "item_id": message.item_id,
                    "output_index": message.output_index,
                    "content_index": part.content_index,
                    "refusal": part.text,
                }
            out.append(self._event(done))
            out.append(
                self._event(
                    {
                        "type": "response.content_part.done",
                        "item_id": message.item_id,
                        "output_index": message.output_index,
                        "content_index": part.content_index,
                        "part": _content_part(part),
                    }
                )
            )
        out.append(
            self._event(
                {
                    "type": "response.output_item.done",
                    "output_index": message.output_index,
                    "item": _message_item(message),
                }
            )
        )
        return out

    def _tool_call_delta(self, call: Mapping[str, JsonValue]) -> list[_Json]:
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
            )
            self._tool_calls[index] = state
        elif not state.added:
            if call_id:
                state.call_id = call_id
            if name:
                state.name = name
        # Chat Completions streams argument fragments. Append them as sent.
        # A later fragment may start with the same text as the accumulated
        # arguments; that is still a new fragment, not a cumulative snapshot.
        state.arguments += _tool_call_arguments(call)
        out: list[_Json] = []
        if not state.added and state.name:
            out.extend(self._add_tool_call(state))
        if state.added and not self._is_custom(state):
            out.extend(self._stream_function_arguments(state))
        return out

    def _is_custom(self, call: _StreamToolCall) -> bool:
        shape = self._tool_shapes.get(call.name)
        return shape is not None and shape.kind == "custom"

    def _add_tool_call(self, call: _StreamToolCall) -> list[_Json]:
        """Announce a tool call once its name is known.

        The name decides the item type (a custom tool call or a function
        call), so the item is not announced before it arrives.
        """

        call.added = True
        if self._is_custom(call):
            call.item_id = f"ctc_{call.item_id.removeprefix('fc_')}"
        item = self._tool_call_item(call, status="in_progress")
        if item["type"] == "custom_tool_call":
            item["input"] = ""
        else:
            item["arguments"] = ""
        return [self._event({"type": "response.output_item.added", "output_index": call.output_index, "item": item})]

    def _stream_function_arguments(self, call: _StreamToolCall) -> list[_Json]:
        fragment = call.arguments[call.streamed_arguments :]
        if not fragment:
            return []
        call.streamed_arguments = len(call.arguments)
        return [
            self._event(
                {
                    "type": "response.function_call_arguments.delta",
                    "item_id": call.item_id,
                    "output_index": call.output_index,
                    "delta": fragment,
                }
            )
        ]

    def _close_tool_call(self, call: _StreamToolCall) -> list[_Json]:
        out: list[_Json] = []
        if not call.added:
            out.extend(self._add_tool_call(call))
        item = self._tool_call_item(call, status="completed")
        if item["type"] == "custom_tool_call":
            # The chat arguments are a JSON object around the freeform input,
            # so the input is only known once they are complete.
            tool_input = cast(str, item["input"])
            if tool_input:
                out.append(
                    self._event(
                        {
                            "type": "response.custom_tool_call_input.delta",
                            "item_id": call.item_id,
                            "output_index": call.output_index,
                            "delta": tool_input,
                        }
                    )
                )
            out.append(
                self._event(
                    {
                        "type": "response.custom_tool_call_input.done",
                        "item_id": call.item_id,
                        "output_index": call.output_index,
                        "input": tool_input,
                    }
                )
            )
        else:
            out.extend(self._stream_function_arguments(call))
            out.append(
                self._event(
                    {
                        "type": "response.function_call_arguments.done",
                        "item_id": call.item_id,
                        "output_index": call.output_index,
                        "name": item["name"],
                        "arguments": call.arguments,
                    }
                )
            )
        out.append(self._event({"type": "response.output_item.done", "output_index": call.output_index, "item": item}))
        return out

    def _tool_call_item(self, call: _StreamToolCall, *, status: str) -> _Json:
        return _call_output_item(
            item_id=call.item_id,
            call_id=call.call_id,
            wire_name=call.name,
            arguments=call.arguments,
            shapes=self._tool_shapes,
            status=status,
        )

    # -- snapshots ----------------------------------------------------------

    def _response_object(self, status: str) -> _Json:
        response: _Json = {
            "id": self._response_id,
            "object": "response",
            "created_at": self._created_at,
            "status": status,
            "model": self._model,
            "output": self._output_items() if status != "in_progress" else [],
            "incomplete_details": None,
            "error": None,
            **self._echo,
        }
        if self._usage is not None and status != "in_progress":
            response["usage"] = self._usage
        return response

    def _output_items(self) -> list[JsonValue]:
        ranked: list[tuple[int, _Json]] = []
        if self._message is not None:
            ranked.append((self._message.output_index, _message_item(self._message)))
        for call in self._tool_calls.values():
            ranked.append((call.output_index, self._tool_call_item(call, status="completed")))
        ranked.sort(key=lambda entry: entry[0])
        return [item for _, item in ranked]


def _empty_content_part(kind: _ContentKind) -> _Json:
    if kind == _OUTPUT_TEXT_TYPE:
        return _output_text_part("")
    return {"type": _REFUSAL_TYPE, "refusal": ""}


def _content_part(part: _StreamContentPart) -> _Json:
    if part.kind == _OUTPUT_TEXT_TYPE:
        return _output_text_part(part.text)
    return {"type": _REFUSAL_TYPE, "refusal": part.text}


def _message_item(message: _StreamMessage) -> _Json:
    return {
        "id": message.item_id,
        "type": "message",
        "status": "completed",
        "role": "assistant",
        "content": [_content_part(part) for part in message.parts],
    }


# ``response.error.code`` is a closed set in the Responses API (the OpenAI SDK
# rejects anything else). An upstream rate limit keeps its meaning; every other
# upstream failure is a server error from the client's point of view.
_RATE_LIMIT_ERROR_CODES = frozenset({"rate_limit_exceeded", "rate_limited", "rate_limit_error", "too_many_requests"})


def _response_error(error: JsonValue) -> _Json:
    upstream_code: str | None = None
    message = "Upstream provider error"
    if is_json_mapping(error):
        code = error.get("code") or error.get("type")
        upstream_code = code if isinstance(code, str) and code else None
        raw_message = error.get("message")
        if isinstance(raw_message, str) and raw_message:
            message = raw_message
    elif isinstance(error, str) and error:
        message = error
    if upstream_code is not None and upstream_code in _RATE_LIMIT_ERROR_CODES:
        return {"code": "rate_limit_exceeded", "message": message}
    if upstream_code is not None:
        message = f"{message} ({upstream_code})"
    return {"code": "server_error", "message": message}


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
