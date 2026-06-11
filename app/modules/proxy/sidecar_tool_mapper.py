from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import cast

from app.core.types import JsonValue
from app.core.utils.json_guards import is_json_mapping

logger = logging.getLogger(__name__)

# Cursor / OpenAI tool names mapped to Claude Code OAuth-compatible names (ungate-compatible).
_SIDECAR_TOOL_NAME_MAPPING: dict[str, str] = {
    "Shell": "Bash",
    "LS": "Glob",
    "Delete": "Edit",
    "StrReplace": "Edit",
    "EditNotebook": "NotebookEdit",
    "ReadLints": "Read",
    "SemanticSearch": "Grep",
    "read_file": "Read",
    "view_file": "Read",
    "write": "Write",
    "write_to_file": "Write",
    "write_file": "Write",
    "str_replace_editor": "Edit",
    "replace_in_file": "Edit",
    "list_files": "Glob",
    "list_dir": "Glob",
    "find_files": "Glob",
    "codebase_search": "Grep",
    "file_search": "Grep",
    "grep_search": "Grep",
    "search_files": "Grep",
    "execute_bash": "Bash",
    "execute_command": "Bash",
    "run_terminal_cmd": "Bash",
    "run_command": "Bash",
    "bash": "Bash",
    "terminal": "Bash",
    "web_search": "WebSearch",
    "search_web": "WebSearch",
    "search": "WebSearch",
    "fetch_web": "WebFetch",
    "web_fetch": "WebFetch",
    "fetch_url": "WebFetch",
    "http_request": "WebFetch",
    "create_task": "Task",
    "spawn_agent": "Task",
    "delegate_task": "Task",
    "todo": "TodoWrite",
    "task_list": "TodoWrite",
    "edit_notebook": "NotebookEdit",
    "notebook_edit": "NotebookEdit",
    "ask_user": "AskUserQuestion",
    "prompt_user": "AskUserQuestion",
    "browser_action": "WebFetch",
}

_VALID_CLAUDE_CODE_TOOLS = frozenset(
    {
        "Task",
        "TaskOutput",
        "Bash",
        "Glob",
        "Grep",
        "ExitPlanMode",
        "Read",
        "Edit",
        "Write",
        "NotebookEdit",
        "WebFetch",
        "TodoWrite",
        "WebSearch",
        "KillShell",
        "AskUserQuestion",
        "Skill",
        "EnterPlanMode",
        "CreatePlan",
        "AskQuestion",
        "SwitchMode",
    }
)

_SIDECAR_INPUT_TOOL_ITEM_TYPES = frozenset({"function_call", "custom_tool_call"})


@dataclass(frozen=True, slots=True)
class SidecarToolMapResult:
    reverse_tool_names: dict[str, str]


def map_sidecar_chat_tool_names(body: dict[str, JsonValue]) -> SidecarToolMapResult:
    used_names: set[str] = set()
    reverse_tool_names: dict[str, str] = {}
    forward_tool_names: dict[str, str] = {}

    tools = body.get("tools")
    if isinstance(tools, list):
        body["tools"] = _map_tools_array(
            tools,
            used_names=used_names,
            reverse_tool_names=reverse_tool_names,
            forward_tool_names=forward_tool_names,
        )

    messages = body.get("messages")
    if isinstance(messages, list):
        for message in messages:
            if is_json_mapping(message):
                _map_message_tool_names(
                    cast(dict[str, JsonValue], message),
                    used_names=used_names,
                    reverse_tool_names=reverse_tool_names,
                    forward_tool_names=forward_tool_names,
                )

    input_items = body.get("input")
    if isinstance(input_items, list):
        for item in input_items:
            if is_json_mapping(item):
                _map_input_item_tool_names(
                    cast(dict[str, JsonValue], item),
                    used_names=used_names,
                    reverse_tool_names=reverse_tool_names,
                    forward_tool_names=forward_tool_names,
                )

    return SidecarToolMapResult(reverse_tool_names=reverse_tool_names)


def reverse_sidecar_tool_names_in_response(
    payload: JsonValue,
    reverse_tool_names: dict[str, str],
) -> JsonValue:
    if not reverse_tool_names or not is_json_mapping(payload):
        return payload
    rewritten = cast(dict[str, JsonValue], json.loads(json.dumps(payload)))
    _reverse_tool_names_in_completion(cast(dict[str, JsonValue], rewritten), reverse_tool_names)
    return rewritten


class SidecarSseToolNameRewriter:
    def __init__(self, reverse_tool_names: dict[str, str]) -> None:
        self._reverse_tool_names = reverse_tool_names
        self._buffer = ""

    def feed(self, chunk: bytes) -> list[bytes]:
        if not self._reverse_tool_names:
            return [chunk]
        self._buffer += chunk.decode("utf-8", errors="ignore")
        outputs: list[bytes] = []
        while "\n\n" in self._buffer:
            raw_event, self._buffer = self._buffer.split("\n\n", 1)
            outputs.append(self._rewrite_event(raw_event))
        return outputs

    def flush(self) -> list[bytes]:
        if not self._buffer:
            return []
        if not self._reverse_tool_names:
            pending = self._buffer.encode("utf-8")
            self._buffer = ""
            return [pending]
        pending = self._rewrite_event(self._buffer)
        self._buffer = ""
        return [pending]

    def _rewrite_event(self, raw_event: str) -> bytes:
        data_lines: list[str] = []
        prefix_lines: list[str] = []
        for raw_line in raw_event.splitlines():
            if not raw_line or raw_line.startswith(":"):
                prefix_lines.append(raw_line)
                continue
            field, _, value = raw_line.partition(":")
            if field != "data":
                prefix_lines.append(raw_line)
                continue
            data_lines.append(value[1:] if value.startswith(" ") else value)

        if not data_lines:
            return (raw_event + "\n\n").encode("utf-8")

        data = "\n".join(data_lines)
        if data.strip() == "[DONE]":
            return (raw_event + "\n\n").encode("utf-8")

        try:
            parsed = json.loads(data)
        except json.JSONDecodeError:
            return (raw_event + "\n\n").encode("utf-8")

        if is_json_mapping(parsed):
            _reverse_tool_names_in_completion(cast(dict[str, JsonValue], parsed), self._reverse_tool_names)
            rewritten_data = json.dumps(parsed, ensure_ascii=True, separators=(",", ":"))
            lines = [*prefix_lines, f"data: {rewritten_data}"]
            return ("\n".join(lines) + "\n\n").encode("utf-8")

        return (raw_event + "\n\n").encode("utf-8")


def _map_tools_array(
    tools: list[JsonValue],
    *,
    used_names: set[str],
    reverse_tool_names: dict[str, str],
    forward_tool_names: dict[str, str],
) -> list[JsonValue]:
    mapped_tools: list[JsonValue] = []
    for tool in tools:
        if not is_json_mapping(tool):
            continue
        tool_dict = cast(dict[str, JsonValue], tool)
        original_name = _read_tool_definition_name(tool_dict)
        if original_name is None:
            mapped_tools.append(tool)
            continue
        wire_name = _resolve_forward_tool_name(
            original_name,
            used_names=used_names,
            reverse_tool_names=reverse_tool_names,
            forward_tool_names=forward_tool_names,
            allow_unknown=False,
        )
        if wire_name is None:
            continue
        mapped_tools.append(_write_tool_definition_name(tool_dict, wire_name))
    return mapped_tools


def _map_message_tool_names(
    message: dict[str, JsonValue],
    *,
    used_names: set[str],
    reverse_tool_names: dict[str, str],
    forward_tool_names: dict[str, str],
) -> None:
    content = message.get("content")
    if isinstance(content, list):
        for part in content:
            if not is_json_mapping(part):
                continue
            part_dict = cast(dict[str, JsonValue], part)
            if part_dict.get("type") == "tool_use":
                _rewrite_tool_name_field(
                    part_dict,
                    "name",
                    used_names=used_names,
                    reverse_tool_names=reverse_tool_names,
                    forward_tool_names=forward_tool_names,
                )

    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        for tool_call in tool_calls:
            if not is_json_mapping(tool_call):
                continue
            function = cast(dict[str, JsonValue], tool_call).get("function")
            if is_json_mapping(function):
                _rewrite_tool_name_field(
                    cast(dict[str, JsonValue], function),
                    "name",
                    used_names=used_names,
                    reverse_tool_names=reverse_tool_names,
                    forward_tool_names=forward_tool_names,
                )

    function_call = message.get("function_call")
    if is_json_mapping(function_call):
        _rewrite_tool_name_field(
            cast(dict[str, JsonValue], function_call),
            "name",
            used_names=used_names,
            reverse_tool_names=reverse_tool_names,
            forward_tool_names=forward_tool_names,
        )


def _map_input_item_tool_names(
    item: dict[str, JsonValue],
    *,
    used_names: set[str],
    reverse_tool_names: dict[str, str],
    forward_tool_names: dict[str, str],
) -> None:
    item_type = item.get("type")
    if isinstance(item_type, str) and item_type in _SIDECAR_INPUT_TOOL_ITEM_TYPES:
        _rewrite_tool_name_field(
            item,
            "name",
            used_names=used_names,
            reverse_tool_names=reverse_tool_names,
            forward_tool_names=forward_tool_names,
        )
        custom = item.get("custom")
        if is_json_mapping(custom):
            _rewrite_tool_name_field(
                cast(dict[str, JsonValue], custom),
                "name",
                used_names=used_names,
                reverse_tool_names=reverse_tool_names,
                forward_tool_names=forward_tool_names,
            )


def _read_tool_definition_name(tool: dict[str, JsonValue]) -> str | None:
    function = tool.get("function")
    if is_json_mapping(function):
        name = function.get("name")
        if isinstance(name, str) and name:
            return name
    name = tool.get("name")
    if isinstance(name, str) and name:
        return name
    return None


def _write_tool_definition_name(tool: dict[str, JsonValue], wire_name: str) -> dict[str, JsonValue]:
    rewritten = dict(tool)
    function = rewritten.get("function")
    if is_json_mapping(function):
        function_dict = dict(cast(dict[str, JsonValue], function))
        function_dict["name"] = wire_name
        rewritten["function"] = function_dict
    if "name" in rewritten:
        rewritten["name"] = wire_name
    return rewritten


def _rewrite_tool_name_field(
    container: dict[str, JsonValue],
    field: str,
    *,
    used_names: set[str],
    reverse_tool_names: dict[str, str],
    forward_tool_names: dict[str, str],
) -> None:
    value = container.get(field)
    if not isinstance(value, str) or not value:
        return
    wire_name = _resolve_forward_tool_name(
        value,
        used_names=used_names,
        reverse_tool_names=reverse_tool_names,
        forward_tool_names=forward_tool_names,
        allow_unknown=True,
    )
    if wire_name is not None and wire_name != value:
        container[field] = wire_name


def _resolve_forward_tool_name(
    original_name: str,
    *,
    used_names: set[str],
    reverse_tool_names: dict[str, str],
    forward_tool_names: dict[str, str],
    allow_unknown: bool,
) -> str | None:
    cached = forward_tool_names.get(original_name)
    if cached is not None:
        return cached
    if original_name in _VALID_CLAUDE_CODE_TOOLS:
        wire_name = _unique_tool_name(original_name, used_names=used_names)
        if wire_name != original_name:
            reverse_tool_names[wire_name] = original_name
        forward_tool_names[original_name] = wire_name
        return wire_name

    mapped_name = _SIDECAR_TOOL_NAME_MAPPING.get(original_name)
    if mapped_name is not None:
        wire_name = _unique_tool_name(mapped_name, used_names=used_names)
        reverse_tool_names[wire_name] = original_name
        forward_tool_names[original_name] = wire_name
        if wire_name != original_name:
            logger.debug("mapped sidecar tool %s -> %s", original_name, wire_name)
        return wire_name

    if allow_unknown:
        forward_tool_names[original_name] = original_name
        return original_name
    return None


def _unique_tool_name(base_name: str, *, used_names: set[str]) -> str:
    if base_name not in used_names:
        used_names.add(base_name)
        return base_name
    suffix = 1
    while f"{base_name}_{suffix}" in used_names:
        suffix += 1
    unique_name = f"{base_name}_{suffix}"
    used_names.add(unique_name)
    return unique_name


def _reverse_tool_names_in_completion(payload: dict[str, JsonValue], reverse_tool_names: dict[str, str]) -> None:
    choices = payload.get("choices")
    if not isinstance(choices, list):
        return
    for choice in choices:
        if not is_json_mapping(choice):
            continue
        choice_dict = cast(dict[str, JsonValue], choice)
        delta = choice_dict.get("delta")
        if is_json_mapping(delta):
            _reverse_tool_calls_in_container(cast(dict[str, JsonValue], delta), reverse_tool_names)
        message = choice_dict.get("message")
        if is_json_mapping(message):
            _reverse_tool_calls_in_container(cast(dict[str, JsonValue], message), reverse_tool_names)


def _reverse_tool_calls_in_container(
    container: dict[str, JsonValue],
    reverse_tool_names: dict[str, str],
) -> None:
    tool_calls = container.get("tool_calls")
    if not isinstance(tool_calls, list):
        return
    for tool_call in tool_calls:
        if not is_json_mapping(tool_call):
            continue
        function = cast(dict[str, JsonValue], tool_call).get("function")
        if not is_json_mapping(function):
            continue
        name = function.get("name")
        if isinstance(name, str):
            client_name = reverse_tool_names.get(name)
            if client_name is not None:
                function["name"] = client_name
