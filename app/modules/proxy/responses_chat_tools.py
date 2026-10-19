"""Responses tool definitions mapped onto Chat Completions tools.

The Responses API declares function tools flat (``{"type": "function",
"name": ..., "parameters": ...}``) and adds tool kinds Chat Completions does not
have: freeform ``custom`` tools, ``namespace`` groups of tools, and hosted
built-ins (``web_search``, ``file_search``, ``local_shell`` ...). A chat
upstream only understands ``{"type": "function", "function": {...}}``.

This module turns a Responses tool list into chat function tools and records,
for each chat-facing name, which Responses tool it came from
(:class:`ChatToolShape`). The response translator uses that record to emit the
call back in its original shape: a ``custom_tool_call`` with freeform
``input`` for a custom tool, and a ``function_call`` carrying ``namespace``
for a namespace child.

A tool that cannot be expressed on a chat upstream raises
:class:`ClientPayloadError` (an HTTP 400) instead of being dropped, so a
client never runs a turn that silently lost a tool it declared.

Reference behaviour this follows:

- LiteLLM ``transform_responses_api_tools_to_chat_completion_tools``
  (litellm/responses/litellm_completion_transformation/transformation.py):
  flat function tool -> ``{"type": "function", "function": {name, description,
  parameters, strict}}``, with ``parameters`` defaulting to an object schema.
- CLIProxyAPI ``claude_openai-responses_request.go``: ``custom`` tools become a
  function taking ``{"input": string}``; ``namespace`` children are flattened
  as ``<namespace>__<child>`` (``qualifyResponsesNamespaceToolName``);
  ``web_search`` with ``external_web_access: false`` (Codex CLI's default
  cached mode) is dropped because only OpenAI's own index can serve it;
  ``image_generation``, ``file_search``, ``code_interpreter`` and
  ``computer_use_preview`` cannot run there. CLIProxyAPI drops those silently;
  this rejects them so the client learns the tool is unavailable.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, cast

from app.core.openai.exceptions import ClientPayloadError
from app.core.types import JsonValue
from app.core.utils.json_guards import is_json_list, is_json_mapping

_Json = dict[str, JsonValue]

ChatToolKind = Literal["function", "custom"]


def chat_bridge_error(message: str, *, param: str | None, code: str = "unsupported_value") -> ClientPayloadError:
    """A 400 for a Responses request a chat-completions provider cannot serve.

    ``code`` and ``error_type`` are always set so the client sees this message;
    a bare :class:`ClientPayloadError` is rendered as a generic
    "Invalid request payload".
    """

    return ClientPayloadError(message, param=param, code=code, error_type="invalid_request_error")


# A custom tool takes one freeform string. On a chat upstream it is declared as
# a function with a single required ``input`` string, the same schema
# CLIProxyAPI uses for Claude.
CUSTOM_TOOL_INPUT_FIELD = "input"
_CUSTOM_TOOL_PARAMETERS: _Json = {
    "type": "object",
    "properties": {CUSTOM_TOOL_INPUT_FIELD: {"type": "string"}},
    "required": [CUSTOM_TOOL_INPUT_FIELD],
    "additionalProperties": False,
}
_EMPTY_OBJECT_SCHEMA: _Json = {"type": "object", "properties": {}}
_NAMESPACE_SEPARATOR = "__"
_WEB_SEARCH_TOOL_TYPES = frozenset({"web_search", "web_search_preview"})


@dataclass(frozen=True, slots=True)
class ChatToolShape:
    """The Responses tool a chat-facing function name stands for."""

    kind: ChatToolKind
    name: str
    namespace: str | None = None


@dataclass(slots=True)
class ChatToolTranslation:
    """Chat tools built from a Responses tool list."""

    tools: list[JsonValue] = field(default_factory=list)
    shapes: dict[str, ChatToolShape] = field(default_factory=dict)


def translate_responses_tools(tools: list[JsonValue], *, model: str) -> ChatToolTranslation:
    """Convert Responses tool declarations into chat function tools.

    Raises :class:`ClientPayloadError` for a tool no chat upstream can run.
    """

    translation = ChatToolTranslation()
    for index, tool in enumerate(tools):
        _translate_tool(tool, param=f"tools[{index}]", model=model, translation=translation)
    return translation


def qualify_namespace_tool_name(namespace: str, child: str) -> str:
    """The flat chat name for a namespace child (CLIProxyAPI's rule)."""

    if not namespace or child.startswith("mcp__"):
        return child
    if child == namespace or child.startswith(namespace + _NAMESPACE_SEPARATOR):
        return child
    if namespace.endswith(_NAMESPACE_SEPARATOR):
        return namespace + child
    return namespace + _NAMESPACE_SEPARATOR + child


def chat_tool_wire_name(name: str, namespace: JsonValue) -> str:
    """The chat function name a Responses call item refers to."""

    if isinstance(namespace, str) and namespace:
        return qualify_namespace_tool_name(namespace, name)
    return name


def translate_responses_tool_choice(
    tool_choice: JsonValue,
    *,
    shapes: Mapping[str, ChatToolShape],
) -> JsonValue:
    """Map a Responses ``tool_choice`` onto the chat ``tool_choice`` shape."""

    if tool_choice is None or isinstance(tool_choice, str):
        return tool_choice
    if not is_json_mapping(tool_choice):
        raise chat_bridge_error("tool_choice must be a string or an object.", param="tool_choice")
    choice_type = tool_choice.get("type")
    if choice_type in ("function", "custom"):
        name = _choice_function_name(tool_choice)
        if name is None:
            raise chat_bridge_error("tool_choice must name the tool to call.", param="tool_choice")
        wire_name = chat_tool_wire_name(name, tool_choice.get("namespace"))
        return {"type": "function", "function": {"name": wire_name}}
    if choice_type == "allowed_tools":
        return _translate_allowed_tools_choice(tool_choice)
    raise chat_bridge_error(
        f"tool_choice type '{choice_type}' is not supported by chat-completions providers.",
        param="tool_choice",
    )


def normalize_chat_function_tools(body: dict[str, JsonValue]) -> None:
    """Rewrite flat Responses-style function tools in a chat body to chat shape.

    Chat clients sometimes send the Responses tool shape to
    ``/v1/chat/completions``. A strict chat upstream rejects it (``tools[0]``
    has no ``function``) or ignores the tool, so every chat provider builder
    normalizes it. Tools already in chat shape and non-function tools are left
    unchanged; this is idempotent.
    """

    tools = body.get("tools")
    if not is_json_list(tools):
        return
    body["tools"] = [_chat_function_tool_or_unchanged(tool) for tool in tools]


def _chat_function_tool_or_unchanged(tool: JsonValue) -> JsonValue:
    if not is_json_mapping(tool) or tool.get("type") != "function" or is_json_mapping(tool.get("function")):
        return tool
    name = tool.get("name")
    if not isinstance(name, str) or not name:
        return tool
    return _chat_function_tool(name, tool)


def _translate_tool(
    tool: JsonValue,
    *,
    param: str,
    model: str,
    translation: ChatToolTranslation,
) -> None:
    if not is_json_mapping(tool):
        raise chat_bridge_error("Each tool must be an object.", param=param)
    tool_type = tool.get("type")
    if tool_type in (None, "function"):
        _add_function_tool(tool, param=param, namespace=None, translation=translation)
        return
    if tool_type == "custom":
        _add_custom_tool(tool, param=param, namespace=None, translation=translation)
        return
    if tool_type == "namespace":
        _add_namespace_tools(tool, param=param, model=model, translation=translation)
        return
    if tool_type in _WEB_SEARCH_TOOL_TYPES:
        _drop_or_reject_web_search_tool(tool, param=param, model=model)
        return
    raise chat_bridge_error(
        f"Tool type '{tool_type}' is not supported for model '{model}', which is served "
        "through a chat-completions provider. Only function, custom, namespace and "
        "cached web_search tools can be translated.",
        param=param,
    )


def _add_function_tool(
    tool: Mapping[str, JsonValue],
    *,
    param: str,
    namespace: str | None,
    translation: ChatToolTranslation,
) -> None:
    function = tool.get("function")
    source = function if is_json_mapping(function) else tool
    name = _tool_name(source, param=param)
    wire_name = qualify_namespace_tool_name(namespace, name) if namespace else name
    if not _register_shape(translation, wire_name, ChatToolShape("function", name, namespace)):
        return
    translation.tools.append(_chat_function_tool(wire_name, source))


def _add_custom_tool(
    tool: Mapping[str, JsonValue],
    *,
    param: str,
    namespace: str | None,
    translation: ChatToolTranslation,
) -> None:
    name = _tool_name(tool, param=param)
    wire_name = qualify_namespace_tool_name(namespace, name) if namespace else name
    if not _register_shape(translation, wire_name, ChatToolShape("custom", name, namespace)):
        return
    description = tool.get("description")
    text = description if isinstance(description, str) else ""
    grammar = _custom_tool_format_note(tool.get("format"))
    if grammar:
        text = f"{text}\n\n{grammar}" if text else grammar
    function: _Json = {"name": wire_name, "parameters": dict(_CUSTOM_TOOL_PARAMETERS)}
    if text:
        function["description"] = text
    translation.tools.append({"type": "function", "function": function})


def _custom_tool_format_note(tool_format: JsonValue) -> str:
    """Carry a custom tool's grammar into the description.

    A chat function cannot enforce a Lark/regex grammar, so the definition is
    kept where the model can still read it rather than discarded.
    """

    if not is_json_mapping(tool_format) or tool_format.get("type") != "grammar":
        return ""
    definition = tool_format.get("definition")
    if not isinstance(definition, str) or not definition:
        return ""
    syntax = tool_format.get("syntax")
    label = syntax if isinstance(syntax, str) and syntax else "grammar"
    return f"The `{CUSTOM_TOOL_INPUT_FIELD}` value must follow this {label} grammar:\n{definition}"


def _add_namespace_tools(
    tool: Mapping[str, JsonValue],
    *,
    param: str,
    model: str,
    translation: ChatToolTranslation,
) -> None:
    namespace = tool.get("name")
    if not isinstance(namespace, str) or not namespace.strip():
        raise chat_bridge_error("A namespace tool must have a name.", param=f"{param}.name")
    namespace = namespace.strip()
    children = tool.get("tools")
    if not is_json_list(children):
        raise chat_bridge_error("A namespace tool must list its tools.", param=f"{param}.tools")
    for child_index, child in enumerate(children):
        child_param = f"{param}.tools[{child_index}]"
        if not is_json_mapping(child):
            raise chat_bridge_error("Each namespace tool must be an object.", param=child_param)
        child_type = child.get("type")
        if child_type in (None, "function"):
            _add_function_tool(child, param=child_param, namespace=namespace, translation=translation)
        elif child_type == "custom":
            _add_custom_tool(child, param=child_param, namespace=namespace, translation=translation)
        else:
            raise chat_bridge_error(
                f"Namespace tool type '{child_type}' is not supported for model '{model}'.",
                param=child_param,
            )


def _drop_or_reject_web_search_tool(tool: Mapping[str, JsonValue], *, param: str, model: str) -> None:
    """Handle a hosted web search tool.

    ``external_web_access: false`` is Codex CLI's default "cached" search mode:
    it reads OpenAI's pre-built index, which no other provider has, and Codex
    declares it on every turn to every provider. Rejecting it would fail every
    default Codex turn, so it is dropped, as CLIProxyAPI does. Live search has
    no chat-completions equivalent that every chat upstream honours (CLIProxyAPI's
    chat endpoint ignores ``web_search_options``), so it is rejected rather than
    silently turned off.
    """

    if tool.get("external_web_access") is False:
        return
    raise chat_bridge_error(
        f"Live web search is not supported for model '{model}', which is served through a "
        "chat-completions provider. Use cached web search or a native Responses model.",
        param=param,
    )


def _register_shape(translation: ChatToolTranslation, wire_name: str, shape: ChatToolShape) -> bool:
    existing = translation.shapes.get(wire_name)
    if existing is None:
        translation.shapes[wire_name] = shape
        return True
    if existing == shape:
        # The same tool declared twice; chat upstreams reject repeated names.
        return False
    raise chat_bridge_error(
        f"Two tools map to the chat function name '{wire_name}'. Rename one of them.",
        param="tools",
    )


def _chat_function_tool(wire_name: str, source: Mapping[str, JsonValue]) -> _Json:
    parameters = source.get("parameters")
    function: _Json = {
        "name": wire_name,
        "parameters": cast(JsonValue, dict(parameters)) if is_json_mapping(parameters) else dict(_EMPTY_OBJECT_SCHEMA),
    }
    description = source.get("description")
    if isinstance(description, str) and description:
        function["description"] = description
    strict = source.get("strict")
    if isinstance(strict, bool):
        function["strict"] = strict
    return {"type": "function", "function": function}


def _tool_name(tool: Mapping[str, JsonValue], *, param: str) -> str:
    name = tool.get("name")
    if not isinstance(name, str) or not name.strip():
        raise chat_bridge_error("Each function tool must have a name.", param=f"{param}.name")
    return name.strip()


def _choice_function_name(tool_choice: Mapping[str, JsonValue]) -> str | None:
    function = tool_choice.get("function")
    source = function if is_json_mapping(function) else tool_choice
    name = source.get("name")
    return name if isinstance(name, str) and name else None


def _translate_allowed_tools_choice(tool_choice: Mapping[str, JsonValue]) -> _Json:
    tools = tool_choice.get("tools")
    if not is_json_list(tools):
        raise chat_bridge_error("allowed_tools must list its tools.", param="tool_choice.tools")
    allowed: list[JsonValue] = []
    for index, entry in enumerate(tools):
        if not is_json_mapping(entry) or entry.get("type") not in ("function", "custom"):
            raise chat_bridge_error(
                "allowed_tools can only reference function or custom tools on chat-completions providers.",
                param=f"tool_choice.tools[{index}]",
            )
        name = _choice_function_name(entry)
        if name is None:
            raise chat_bridge_error("allowed_tools entries must name a tool.", param=f"tool_choice.tools[{index}]")
        allowed.append({"type": "function", "function": {"name": chat_tool_wire_name(name, entry.get("namespace"))}})
    mode = tool_choice.get("mode")
    return {
        "type": "allowed_tools",
        "allowed_tools": {"mode": mode if isinstance(mode, str) else "auto", "tools": allowed},
    }
