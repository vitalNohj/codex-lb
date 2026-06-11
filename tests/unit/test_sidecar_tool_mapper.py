from __future__ import annotations

import json

from app.modules.proxy.sidecar_tool_mapper import (
    SidecarSseToolNameRewriter,
    map_sidecar_chat_tool_names,
    reverse_sidecar_tool_names_in_response,
)


def test_map_sidecar_chat_tool_names_maps_cursor_tools_and_drops_unknown_definitions() -> None:
    body = {
        "model": "claude-fable-5",
        "tools": [
            {"type": "function", "function": {"name": "Shell", "parameters": {"type": "object"}}},
            {"type": "function", "function": {"name": "SemanticSearch", "parameters": {"type": "object"}}},
            {"type": "function", "function": {"name": "UnknownTool", "parameters": {"type": "object"}}},
        ],
        "messages": [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "call_1",
                        "name": "Shell",
                        "input": {"command": "pwd"},
                    }
                ],
            }
        ],
    }

    result = map_sidecar_chat_tool_names(body)

    assert [tool["function"]["name"] for tool in body["tools"]] == ["Bash", "Grep"]
    assert body["messages"][0]["content"][0]["name"] == "Bash"
    assert result.reverse_tool_names == {"Bash": "Shell", "Grep": "SemanticSearch"}


def test_map_sidecar_chat_tool_names_keeps_valid_cursor_native_tools() -> None:
    body = {
        "tools": [{"type": "function", "function": {"name": "AskQuestion", "parameters": {"type": "object"}}}],
        "messages": [],
    }

    result = map_sidecar_chat_tool_names(body)

    assert body["tools"][0]["function"]["name"] == "AskQuestion"
    assert result.reverse_tool_names == {}


def test_reverse_sidecar_tool_names_in_response_restores_client_tool_names() -> None:
    reverse = {"Bash": "Shell"}
    response = {
        "choices": [
            {
                "index": 0,
                "delta": {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "Bash", "arguments": "{}"},
                        }
                    ]
                },
                "finish_reason": None,
            }
        ]
    }

    rewritten = reverse_sidecar_tool_names_in_response(response, reverse)

    assert rewritten["choices"][0]["delta"]["tool_calls"][0]["function"]["name"] == "Shell"


def test_sidecar_sse_tool_name_rewriter_rewrites_stream_chunks() -> None:
    reverse = {"Bash": "Shell"}
    rewriter = SidecarSseToolNameRewriter(reverse)
    chunk = (
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"name":"Bash","arguments":""}}]}}]}\n\n'
    ).encode("utf-8")

    rewritten = b"".join(rewriter.feed(chunk))
    payload = json.loads(rewritten.decode("utf-8").split("data: ", 1)[1].strip())

    assert payload["choices"][0]["delta"]["tool_calls"][0]["function"]["name"] == "Shell"
