"""Prove the fake Go upstream itself, before anything is asserted through it.

A verification harness that is never verified is just a second place bugs hide.
Every property the cross-layer tests will lean on is exercised here against the
real loopback socket: per-endpoint authentication, SSE frame ordering and
termination, the 404 for an id the catalog does not serve, Retry-After
passthrough, and the disconnect signal.

These tests deliberately drive the fixture with a plain ``aiohttp`` client
rather than through codex-lb, so a failure here localizes to the fixture.
"""

from __future__ import annotations

import asyncio
import json

import aiohttp
import pytest

from tests.fixtures.opencode_go_upstream import (
    LIVE_PROBED_ABSENT_MODEL_ID,
    LIVE_PROBED_MODEL_IDS,
    build_sse_reader,
    fake_opencode_go_upstream,
)

pytestmark = pytest.mark.integration

_KEY = "sk-fake-go-contract-key"
_MODEL = "glm-5.3"

parse_sse = build_sse_reader()


@pytest.mark.asyncio
async def test_models_requires_a_bearer_token_and_lists_the_probed_catalog():
    async with fake_opencode_go_upstream(api_key=_KEY) as upstream:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{upstream.base_url}/models") as unauthenticated:
                assert unauthenticated.status == 401
                # Byte-for-byte the live unauthenticated body recorded by the
                # reuse scout, so a consumer's error handling is exercised
                # against the real shape rather than a convenient one.
                assert await unauthenticated.json() == {
                    "type": "error",
                    "error": {"type": "AuthError", "message": "Missing API key."},
                }

            async with session.get(
                f"{upstream.base_url}/models",
                headers={"Authorization": f"Bearer {_KEY}"},
            ) as authenticated:
                assert authenticated.status == 200
                payload = await authenticated.json()

    served = [entry["id"] for entry in payload["data"]]
    assert served == list(LIVE_PROBED_MODEL_IDS)
    assert LIVE_PROBED_ABSENT_MODEL_ID not in served


@pytest.mark.asyncio
async def test_messages_takes_x_api_key_and_rejects_a_bearer_token_under_the_strict_rule():
    """Pins the *reported* per-endpoint auth split, not a verified contract.

    The claim (LiteLLM PR 39549, corroborated by routatic/proxy setting both
    headers) is that ``/messages`` authenticates with ``x-api-key`` while the
    OpenAI-shaped endpoints take a bearer token. The fixture's strict mode
    encodes that claim so a client which only ever sets ``Authorization`` fails
    here rather than passing against a permissive fake and breaking live.
    """
    async with fake_opencode_go_upstream(api_key=_KEY, strict_auth_by_endpoint=True) as upstream:
        body = {"model": _MODEL, "messages": [{"role": "user", "content": "hi"}]}
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{upstream.base_url}/messages",
                json=body,
                headers={"Authorization": f"Bearer {_KEY}"},
            ) as bearer_only:
                assert bearer_only.status == 401

            async with session.post(
                f"{upstream.base_url}/messages",
                json=body,
                headers={"x-api-key": _KEY},
            ) as api_key_auth:
                assert api_key_auth.status == 200
                assert (await api_key_auth.json())["type"] == "message"

            # The inverse half of the same rule: a bearer-only endpoint must not
            # silently accept x-api-key, or the split is untested in one
            # direction.
            async with session.post(
                f"{upstream.base_url}/chat/completions",
                json=body,
                headers={"x-api-key": _KEY},
            ) as chat_with_api_key:
                assert chat_with_api_key.status == 401


@pytest.mark.asyncio
async def test_permissive_auth_mode_accepts_either_header_on_either_endpoint():
    """The alternative world, so no test depends on the reported rule being true."""
    async with fake_opencode_go_upstream(api_key=_KEY, strict_auth_by_endpoint=False) as upstream:
        body = {"model": _MODEL, "messages": [{"role": "user", "content": "hi"}]}
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{upstream.base_url}/messages",
                json=body,
                headers={"Authorization": f"Bearer {_KEY}"},
            ) as response:
                assert response.status == 200


@pytest.mark.asyncio
async def test_streaming_frames_arrive_in_order_and_terminate_with_done():
    async with fake_opencode_go_upstream(api_key=_KEY) as upstream:
        upstream.completion_text = "one two three"
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{upstream.base_url}/chat/completions",
                json={
                    "model": _MODEL,
                    "messages": [{"role": "user", "content": "hi"}],
                    "stream": True,
                    "stream_options": {"include_usage": True},
                },
                headers={"Authorization": f"Bearer {_KEY}"},
            ) as response:
                assert response.status == 200
                assert response.headers["Content-Type"].startswith("text/event-stream")
                raw = await response.read()

    text = raw.decode()
    assert text.endswith("data: [DONE]\n\n")

    frames = parse_sse(raw)
    # Role frame first, content frames next, finish frame, then the usage frame
    # with an empty choices list. Any other order breaks OpenAI-protocol
    # clients, so order is asserted rather than membership.
    assert frames[0]["choices"][0]["delta"] == {"role": "assistant", "content": ""}
    content = "".join(frame["choices"][0]["delta"].get("content", "") for frame in frames if frame.get("choices"))
    assert content.strip() == "one two three"
    finish_frames = [f for f in frames if f.get("choices") and f["choices"][0].get("finish_reason")]
    assert [f["choices"][0]["finish_reason"] for f in finish_frames] == ["stop"]
    usage_frames = [f for f in frames if f.get("choices") == [] and "usage" in f]
    assert len(usage_frames) == 1
    assert usage_frames[0]["usage"]["total_tokens"] == 18
    # The usage frame is last before [DONE]; a client that stops at
    # finish_reason must still have seen every content frame by then.
    assert frames.index(usage_frames[0]) == len(frames) - 1


@pytest.mark.asyncio
async def test_stream_omits_usage_when_the_caller_did_not_opt_in():
    async with fake_opencode_go_upstream(api_key=_KEY) as upstream:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{upstream.base_url}/chat/completions",
                json={"model": _MODEL, "messages": [], "stream": True},
                headers={"Authorization": f"Bearer {_KEY}"},
            ) as response:
                frames = parse_sse(await response.read())

    assert not [f for f in frames if f.get("choices") == [] and "usage" in f]


@pytest.mark.asyncio
async def test_tool_call_round_trip_is_served_on_both_transports():
    tool_calls = [
        {
            "id": "call_fake_1",
            "type": "function",
            "function": {"name": "get_weather", "arguments": json.dumps({"city": "Oslo"})},
        }
    ]
    async with fake_opencode_go_upstream(api_key=_KEY) as upstream:
        upstream.tool_calls = tool_calls
        headers = {"Authorization": f"Bearer {_KEY}"}
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{upstream.base_url}/chat/completions",
                json={"model": _MODEL, "messages": [{"role": "user", "content": "weather?"}]},
                headers=headers,
            ) as blocking:
                payload = await blocking.json()

            async with session.post(
                f"{upstream.base_url}/chat/completions",
                json={"model": _MODEL, "messages": [], "stream": True},
                headers=headers,
            ) as streaming:
                frames = parse_sse(await streaming.read())

    choice = payload["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["tool_calls"][0]["function"]["name"] == "get_weather"
    assert json.loads(choice["message"]["tool_calls"][0]["function"]["arguments"]) == {"city": "Oslo"}

    streamed_tools = [f for f in frames if f.get("choices") and "tool_calls" in f["choices"][0]["delta"]]
    assert len(streamed_tools) == 1
    assert streamed_tools[0]["choices"][0]["delta"]["tool_calls"][0]["id"] == "call_fake_1"
    assert frames[-1]["choices"][0]["finish_reason"] == "tool_calls"


@pytest.mark.asyncio
async def test_an_id_outside_the_served_catalog_is_rejected_not_answered():
    """An unserved id must fail. A fixture that answers anything proves nothing."""
    async with fake_opencode_go_upstream(api_key=_KEY) as upstream:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{upstream.base_url}/chat/completions",
                json={"model": LIVE_PROBED_ABSENT_MODEL_ID, "messages": []},
                headers={"Authorization": f"Bearer {_KEY}"},
            ) as response:
                assert response.status == 400
                message = (await response.json())["error"]["message"]

    assert LIVE_PROBED_ABSENT_MODEL_ID in message
    assert "not supported for format oa-compat" in message


@pytest.mark.asyncio
async def test_scripted_429_carries_retry_after_and_then_recovers():
    async with fake_opencode_go_upstream(api_key=_KEY) as upstream:
        upstream.script(
            "/v1/chat/completions",
            status=429,
            body={"type": "error", "error": {"type": "RateLimitError", "message": "slow down"}},
            headers={"Retry-After": "37"},
            repeat=1,
        )
        async with aiohttp.ClientSession() as session:
            headers = {"Authorization": f"Bearer {_KEY}"}
            body = {"model": _MODEL, "messages": []}
            async with session.post(f"{upstream.base_url}/chat/completions", json=body, headers=headers) as limited:
                assert limited.status == 429
                assert limited.headers["Retry-After"] == "37"

            async with session.post(f"{upstream.base_url}/chat/completions", json=body, headers=headers) as recovered:
                assert recovered.status == 200


@pytest.mark.asyncio
async def test_persistent_script_repeats_until_cleared():
    async with fake_opencode_go_upstream(api_key=_KEY) as upstream:
        upstream.script("/v1/usage", status=403, repeat=None)
        async with aiohttp.ClientSession() as session:
            for _ in range(3):
                async with session.get(
                    f"{upstream.base_url}/usage",
                    headers={"Authorization": f"Bearer {_KEY}"},
                ) as response:
                    assert response.status == 403


@pytest.mark.asyncio
async def test_usage_returns_the_third_party_window_shape_and_an_empty_unknown_state():
    """The window shape is corroborated third-party evidence, not a contract.

    Both branches matter: consumers must render the documented-by-parsers shape
    AND must keep "endpoint answered with nothing" distinct from "zero usage".
    """
    async with fake_opencode_go_upstream(api_key=_KEY) as upstream:
        headers = {"Authorization": f"Bearer {_KEY}"}
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{upstream.base_url}/usage", headers=headers) as populated:
                payload = await populated.json()

            upstream.usage_windows = None
            async with session.get(f"{upstream.base_url}/usage", headers=headers) as unknown:
                empty = await unknown.json()

    assert set(payload["usage"]) == {"rolling", "weekly", "monthly"}
    assert payload["usage"]["rolling"] == {"status": "ok", "percent": 42, "resetsAt": 1789360000000}
    assert empty == {}
    assert "usage" not in empty


@pytest.mark.asyncio
async def test_client_disconnect_mid_stream_is_observed_by_the_upstream():
    """Abandoning the response must reach the server, not drain invisibly."""
    async with fake_opencode_go_upstream(api_key=_KEY) as upstream:
        upstream.completion_text = " ".join(f"token{index}" for index in range(40))
        upstream.stream_frame_delay_seconds = 0.02
        async with aiohttp.ClientSession() as session:
            response = await session.post(
                f"{upstream.base_url}/chat/completions",
                json={"model": _MODEL, "messages": [], "stream": True},
                headers={"Authorization": f"Bearer {_KEY}"},
            )
            assert response.status == 200
            await response.content.readline()
            response.close()

        await asyncio.wait_for(upstream.stream_disconnected.wait(), timeout=5)

    assert upstream.streams_started == 1
    # The point of the assertion: the server stopped early rather than writing
    # every frame into a dead socket.
    assert upstream.stream_frames_sent < 40


@pytest.mark.asyncio
async def test_every_request_is_recorded_with_headers_and_parsed_body():
    async with fake_opencode_go_upstream(api_key=_KEY) as upstream:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{upstream.base_url}/chat/completions",
                json={"model": _MODEL, "messages": [{"role": "user", "content": "hi"}]},
                headers={"Authorization": f"Bearer {_KEY}", "x-opencode-session": "ses_abc"},
            ) as response:
                assert response.status == 200

    record = upstream.last_request
    assert record.method == "POST"
    assert record.path == "/v1/chat/completions"
    assert record.header("X-OpenCode-Session") == "ses_abc"  # lookup is case-insensitive
    assert record.body["model"] == _MODEL
    assert upstream.session_headers_seen() == ["ses_abc"]
    assert len(upstream.requests_for("/v1/chat/completions")) == 1


@pytest.mark.asyncio
async def test_an_unrouted_path_is_recorded_as_a_404_rather_than_silently_answered():
    async with fake_opencode_go_upstream(api_key=_KEY) as upstream:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{upstream.base_url}/embeddings",
                json={"model": _MODEL},
                headers={"Authorization": f"Bearer {_KEY}"},
            ) as response:
                assert response.status == 404

    assert upstream.last_request.path == "/v1/embeddings"
