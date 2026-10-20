"""The chat body codex-lb sends CLIProxyAPI for Claude stays append-only across turns.

Anthropic caches a prompt prefix in the order tools -> system -> messages and
matches it byte for byte. Changing a tool definition invalidates the whole
cache, and changing ``output_config.effort`` (CLIProxyAPI derives it from
``reasoning_effort``) invalidates the messages part. So for an unchanged
conversation every turn must repeat the previous turn's body exactly and only
append messages. These tests build each turn through the same steps
``proxy_chat_to_sidecar`` takes (``translate_responses_to_chat`` for the
Responses route, then ``build_sidecar_chat_payload`` and
``ensure_stream_usage_requested``) and compare the bytes httpx puts on the wire.
"""

from __future__ import annotations

import copy
from typing import Any, cast

import httpx
import pytest

from app.core.clients.claude_sidecar import ClaudeSidecarConfig, SidecarPrefix
from app.core.openai.chat_requests import ChatCompletionsRequest
from app.core.openai.requests import ResponsesRequest
from app.core.types import JsonValue
from app.modules.proxy import api as proxy_api
from app.modules.proxy.claude_sidecar_dispatch import build_sidecar_chat_payload, ensure_stream_usage_requested
from app.modules.proxy.responses_chat_bridge import translate_responses_to_chat

pytestmark = pytest.mark.unit

_MODEL = "claude-sonnet-4-5-20250929"

_INSTRUCTIONS = "You are a careful coding agent. Read before you edit. Keep answers short."

# Not in alphabetical order, so a sort anywhere in the pipeline shows up.
# ``read_file`` maps to Claude Code's ``Read``, so the client's own ``Read``
# tool is renamed ``Read_1``; history must keep using exactly those names.
_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "bash",
        "description": "Run a shell command.",
        "parameters": {
            "type": "object",
            "properties": {"command": {"type": "array", "items": {"type": "string"}}, "workdir": {"type": "string"}},
            "required": ["command"],
        },
    },
    {
        "type": "function",
        "name": "read_file",
        "description": "Read a file.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    },
    {
        "type": "function",
        "name": "Read",
        "description": "Read a file the Claude Code way.",
        "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}}, "required": ["file_path"]},
    },
    {
        "type": "function",
        "name": "apply_patch",
        "description": "Apply a patch.",
        "parameters": {"type": "object", "properties": {"patch": {"type": "string"}}, "required": ["patch"]},
    },
]


def _config(*, default_reasoning_effort: str | None = None) -> ClaudeSidecarConfig:
    return ClaudeSidecarConfig(
        enabled=True,
        base_url="http://127.0.0.1:8317",
        api_key="key",
        prefixes=(SidecarPrefix(prefix="claude", strip=False),),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
        default_reasoning_effort=default_reasoning_effort,
    )


def _user(text: str) -> dict[str, Any]:
    return {"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}


def _assistant(text: str) -> dict[str, Any]:
    return {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]}


def _reasoning(n: int) -> dict[str, Any]:
    # Opaque to a chat provider and dropped, on every turn alike.
    return {"type": "reasoning", "id": f"rs_{n}", "summary": [], "encrypted_content": f"opaque-{n}"}


def _call(call_id: str, name: str, arguments: str) -> dict[str, Any]:
    return {"type": "function_call", "call_id": call_id, "name": name, "arguments": arguments}


def _output(call_id: str, output: str) -> dict[str, Any]:
    return {"type": "function_call_output", "call_id": call_id, "output": output}


# The input of each turn of one tool session: every turn is the previous
# turn's input plus what happened since. Call ids include characters
# Anthropic rejects, so they are rewritten on every turn.
_TURN_INPUTS: list[list[dict[str, Any]]] = []
_TURN_INPUTS.append([_user("Why does test_parse fail?")])
_TURN_INPUTS.append(
    [
        *_TURN_INPUTS[-1],
        _reasoning(1),
        _call("call:01/read", "read_file", '{"path":"app/parse.py"}'),
        _output("call:01/read", "def parse(s):\n    return int(s)\n"),
    ]
)
_TURN_INPUTS.append(
    [
        *_TURN_INPUTS[-1],
        _reasoning(2),
        _call("call:02/shell", "bash", '{"command":["pytest","-q","tests/test_parse.py"]}'),
        _call("call:03/read", "Read", '{"file_path":"tests/test_parse.py"}'),
        _output("call:02/shell", "1 failed: ValueError: invalid literal for int() with base 10: ' 7'"),
        _output("call:03/read", "def test_parse():\n    assert parse(' 7') == 7\n"),
    ]
)
_TURN_INPUTS.append(
    [
        *_TURN_INPUTS[-1],
        _assistant("parse does not strip whitespace. Strip it?"),
        _user("Yes, fix it."),
    ]
)
_TURN_INPUTS.append(
    [
        *_TURN_INPUTS[-1],
        _reasoning(3),
        _call("call:04/patch", "apply_patch", '{"patch":"-    return int(s)\\n+    return int(s.strip())"}'),
        _output("call:04/patch", "applied"),
    ]
)


def _responses_turn(
    turn: int,
    *,
    effort: str | None = "high",
    tools: list[dict[str, Any]] | None = None,
    prompt_cache_key: str | None = "pck-session-1",
    stream: bool = True,
    extra: dict[str, Any] | None = None,
) -> ResponsesRequest:
    data: dict[str, Any] = {
        "model": _MODEL,
        "instructions": _INSTRUCTIONS,
        "input": copy.deepcopy(_TURN_INPUTS[turn]),
        "tools": copy.deepcopy(_TOOLS if tools is None else tools),
        "tool_choice": "auto",
        "parallel_tool_calls": True,
        "max_output_tokens": 4096,
        "store": False,
        "stream": stream,
    }
    if effort is not None:
        data["reasoning"] = {"effort": effort}
    if prompt_cache_key is not None:
        data["prompt_cache_key"] = prompt_cache_key
    data.update(extra or {})
    return ResponsesRequest.model_validate(data)


def _sidecar_body(
    payload: ResponsesRequest | ChatCompletionsRequest,
    *,
    config: ClaudeSidecarConfig | None = None,
) -> dict[str, JsonValue]:
    chat_request = (
        translate_responses_to_chat(payload, _MODEL).chat_request if isinstance(payload, ResponsesRequest) else payload
    )
    body = build_sidecar_chat_payload(chat_request, _MODEL, config or _config()).body
    if body.get("stream") is True:
        ensure_stream_usage_requested(body)
    return body


def _wire(value: object) -> bytes:
    """The bytes httpx sends for ``json=value``, as ``ClaudeSidecarClient`` posts it."""

    return httpx.Request("POST", "http://127.0.0.1:8317/v1/chat/completions", json=value).content


def _messages(body: dict[str, JsonValue]) -> list[JsonValue]:
    return cast(list[JsonValue], body["messages"])


def _assert_append_only(previous: dict[str, JsonValue], current: dict[str, JsonValue]) -> None:
    """``current`` repeats ``previous`` byte for byte and only appends messages."""

    assert list(current) == list(previous), "body key order changed"
    for key in previous:
        if key != "messages":
            assert _wire(current[key]) == _wire(previous[key]), f"{key} changed between turns"
    earlier = _messages(previous)
    later = _messages(current)
    assert len(later) > len(earlier)
    for index, message in enumerate(earlier):
        assert _wire(later[index]) == _wire(message), f"history message {index} changed between turns"
    # The serialized history is a byte prefix of the next turn's history.
    assert _wire(later).startswith(_wire(earlier)[:-1])
    assert _wire({**current, "messages": later[: len(earlier)]}) == _wire(previous)


def _history_tool_names(body: dict[str, JsonValue]) -> list[str]:
    names: list[str] = []
    for message in _messages(body):
        for tool_call in cast(dict[str, Any], message).get("tool_calls") or []:
            names.append(tool_call["function"]["name"])
    return names


def _defined_tool_names(body: dict[str, JsonValue]) -> list[str]:
    return [cast(dict[str, Any], tool)["function"]["name"] for tool in cast(list[JsonValue], body["tools"])]


@pytest.mark.parametrize("stream", [True, False])
def test_every_turn_of_a_tool_session_extends_the_previous_body(stream: bool) -> None:
    bodies = [_sidecar_body(_responses_turn(turn, stream=stream)) for turn in range(len(_TURN_INPUTS))]

    for previous, current in zip(bodies, bodies[1:]):
        _assert_append_only(previous, current)

    last = bodies[-1]
    assert last["model"] == _MODEL
    assert last["reasoning_effort"] == "high"
    assert last["prompt_cache_key"] == "pck-session-1"
    assert _messages(last)[0] == {"role": "system", "content": _INSTRUCTIONS}
    # Tools keep the client's order; ``Read`` is renamed so it does not collide
    # with ``read_file``'s Claude Code name.
    assert _defined_tool_names(last) == ["Bash", "Read", "Read_1", "apply_patch"]
    assert _history_tool_names(last) == ["Read", "Bash", "Read_1", "apply_patch"]
    assert set(_history_tool_names(last)) <= set(_defined_tool_names(last))


def test_rewritten_tool_call_ids_are_the_same_on_every_turn() -> None:
    bodies = [_sidecar_body(_responses_turn(turn)) for turn in range(len(_TURN_INPUTS))]

    def call_ids(body: dict[str, JsonValue]) -> list[str]:
        ids: list[str] = []
        for message in _messages(body):
            message_dict = cast(dict[str, Any], message)
            ids.extend(tool_call["id"] for tool_call in message_dict.get("tool_calls") or [])
            if message_dict.get("role") == "tool":
                ids.append(message_dict["tool_call_id"])
        return ids

    assert call_ids(bodies[-1]) == [
        "call_01_read",
        "call_01_read",
        "call_02_shell",
        "call_03_read",
        "call_02_shell",
        "call_03_read",
        "call_04_patch",
        "call_04_patch",
    ]
    for previous, current in zip(bodies, bodies[1:]):
        assert call_ids(current)[: len(call_ids(previous))] == call_ids(previous)


def test_the_operator_effort_override_holds_when_the_client_changes_effort() -> None:
    config = _config(default_reasoning_effort="medium")
    efforts = ["high", "low", None, "xhigh", "high"]
    bodies = [
        _sidecar_body(_responses_turn(turn, effort=effort), config=config)
        for turn, effort in zip(range(len(_TURN_INPUTS)), efforts, strict=True)
    ]

    for previous, current in zip(bodies, bodies[1:]):
        _assert_append_only(previous, current)
    assert {body["reasoning_effort"] for body in bodies} == {"medium"}


def test_per_turn_client_metadata_never_reaches_the_body() -> None:
    def chat_turn(turn: int) -> ChatCompletionsRequest:
        history = _messages(_sidecar_body(_responses_turn(turn)))
        return ChatCompletionsRequest.model_validate(
            {
                "model": _MODEL,
                "messages": history,
                "tools": [
                    {"type": "function", "function": {"name": tool["name"], "parameters": tool["parameters"]}}
                    for tool in _TOOLS
                ],
                "reasoning_effort": "high",
                "stream": True,
                # Values a client changes on every request.
                "metadata": {"request_id": f"req-{turn}", "turn": str(turn)},
                "user": f"user-{turn}",
            }
        )

    bodies = [_sidecar_body(chat_turn(turn)) for turn in range(len(_TURN_INPUTS))]

    for previous, current in zip(bodies, bodies[1:]):
        _assert_append_only(previous, current)
    assert all("metadata" not in body and "user" not in body for body in bodies)


def test_the_derived_prompt_cache_key_is_the_same_on_every_turn() -> None:
    """A client that sends no ``prompt_cache_key`` still gets one stable key per conversation."""

    keys: list[str] = []
    bodies: list[dict[str, JsonValue]] = []
    for turn in range(len(_TURN_INPUTS)):
        payload = _responses_turn(turn, prompt_cache_key=None)
        assert proxy_api._derive_chat_provider_prompt_cache_key(payload, None) is True
        assert isinstance(payload.prompt_cache_key, str)
        keys.append(payload.prompt_cache_key)
        bodies.append(_sidecar_body(payload))

    assert len(set(keys)) == 1
    for previous, current in zip(bodies, bodies[1:]):
        _assert_append_only(previous, current)
    assert bodies[-1]["prompt_cache_key"] == keys[0]


# The check above must be able to fail: a client-side change to anything in the
# cached prefix is caught, so a codex-lb change that does the same is too.


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"tools": list(reversed(_TOOLS))}, "tools changed"),
        ({"effort": "low"}, "reasoning_effort changed"),
        ({"prompt_cache_key": "pck-session-2"}, "prompt_cache_key changed"),
    ],
)
def test_the_append_only_check_catches_a_changed_prefix(change: dict[str, Any], message: str) -> None:
    previous = _sidecar_body(_responses_turn(1))
    current = _sidecar_body(_responses_turn(2, **change))

    with pytest.raises(AssertionError, match=message):
        _assert_append_only(previous, current)


def test_the_append_only_check_catches_a_rewritten_history_message() -> None:
    previous = _sidecar_body(_responses_turn(1))
    current = _sidecar_body(_responses_turn(2))
    edited = copy.deepcopy(_messages(current))
    cast(dict[str, Any], edited[1])["content"] = "Why does test_parse fail? "

    with pytest.raises(AssertionError, match="history message 1 changed"):
        _assert_append_only(previous, {**current, "messages": edited})
