from __future__ import annotations

import json
from typing import cast

import pytest

import app.modules.proxy.omniroute_sidecar_dispatch as dispatch
from app.core.clients.claude_sidecar import SidecarPrefix
from app.core.clients.omniroute_sidecar import OmniRouteSidecarClient, OmniRouteSidecarConfig
from app.core.openai.chat_requests import ChatCompletionsRequest
from app.modules.proxy.omniroute_sidecar_dispatch import build_omniroute_chat_payload


def _config(
    *,
    enabled: bool = True,
    full_models: tuple[str, ...] = ("omniroute/test-chat",),
) -> OmniRouteSidecarConfig:
    return OmniRouteSidecarConfig(
        enabled=enabled,
        base_url="http://127.0.0.1:20128/v1",
        api_key="key",
        full_models=full_models,
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
        prefixes=(SidecarPrefix(prefix="omni-", strip=True),),
    )


def test_build_omniroute_chat_payload_preserves_extra_fields_and_effective_model() -> None:
    request = ChatCompletionsRequest.model_validate(
        {
            "model": "gpt-5.4",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
            "temperature": 0.2,
            "custom_flag": "kept",
        }
    )

    payload = build_omniroute_chat_payload(request, "omniroute/test-chat")

    assert payload.body["model"] == "omniroute/test-chat"
    assert payload.body["messages"] == [{"role": "user", "content": "hi"}]
    assert payload.body["custom_flag"] == "kept"


def test_build_omniroute_chat_payload_injects_override_effort_when_absent() -> None:
    request = ChatCompletionsRequest.model_validate(
        {"model": "gpt-5.4", "messages": [{"role": "user", "content": "hi"}]}
    )

    payload = build_omniroute_chat_payload(request, "omniroute/test-chat", "high")

    assert payload.body["reasoning_effort"] == "high"


def test_build_omniroute_chat_payload_override_replaces_client_effort() -> None:
    request = ChatCompletionsRequest.model_validate(
        {
            "model": "gpt-5.4",
            "messages": [{"role": "user", "content": "hi"}],
            "reasoning_effort": "low",
        }
    )

    payload = build_omniroute_chat_payload(request, "omniroute/test-chat", "high")

    assert payload.body["reasoning_effort"] == "high"


class _ScriptedStream:
    """``OmniRouteSidecarClient.stream_chat_completion`` sending fixed byte chunks."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    def stream_chat_completion(self, payload):
        chunks = self._chunks

        class _Context:
            async def __aenter__(self):
                async def iterate():
                    for chunk in chunks:
                        yield chunk

                return iterate()

            async def __aexit__(self, *exc_info) -> None:
                return None

        return _Context()


# OmniRoute is a third-party gateway, so its line endings and chunk boundaries
# are not ours to choose: CRLF framing, and a character split across chunks.
_CRLF_STREAM = (
    b'data: {"id":"c1","object":"chat.completion.chunk",'
    + '"choices":[{"index":0,"delta":{"content":"café"}}]}\r\n\r\n'.encode()
    + b'data: {"id":"c2","object":"chat.completion.chunk","choices":[],'
    + b'"usage":{"prompt_tokens":10,"completion_tokens":5}}\r\n\r\n'
    + b"data: [DONE]\r\n\r\n"
)
_CUT = _CRLF_STREAM.index(b"\xc3") + 1


@pytest.fixture
def settlements(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    logged: list[dict[str, object]] = []

    async def record_log(**kwargs: object) -> None:
        logged.append(kwargs)

    async def finalize(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr(dispatch, "_log_omniroute_request", record_log)
    monkeypatch.setattr(dispatch, "_finalize_or_release_omniroute_reservation", finalize)
    return logged


def _scripted_client() -> OmniRouteSidecarClient:
    return cast(OmniRouteSidecarClient, _ScriptedStream([_CRLF_STREAM[:_CUT], _CRLF_STREAM[_CUT:]]))


@pytest.mark.asyncio
async def test_chat_stream_reads_usage_and_done_from_crlf_framed_split_chunks(settlements) -> None:
    body = b"".join(
        [
            chunk
            async for chunk in dispatch._omniroute_stream_iterator(
                {},
                api_key=None,
                reservation=None,
                model="omniroute/test-chat",
                started_at=0.0,
                client=_scripted_client(),
            )
        ]
    )

    assert body == _CRLF_STREAM
    assert len(settlements) == 1
    assert settlements[0]["status"] == "success"
    usage = settlements[0]["usage"]
    assert usage is not None
    assert (usage.input_tokens, usage.output_tokens) == (10, 5)


@pytest.mark.asyncio
async def test_responses_stream_keeps_a_character_split_across_chunks(settlements) -> None:
    body = b"".join(
        [
            chunk
            async for chunk in dispatch._omniroute_responses_stream_iterator(
                {},
                api_key=None,
                reservation=None,
                model="omniroute/test-chat",
                started_at=0.0,
                client=_scripted_client(),
            )
        ]
    )

    events = [json.loads(line[len(b"data: ") :]) for line in body.split(b"\n") if line.startswith(b"data: {")]
    completed = [event for event in events if event["type"] == "response.completed"]
    assert len(completed) == 1
    [message] = completed[0]["response"]["output"]
    assert message["content"][0]["text"] == "café"
    assert len(settlements) == 1
    assert settlements[0]["status"] == "success"
