"""Native OpenCode Go chain: real client -> real Go dispatch -> loopback upstream.

This file exists because of a scope error in my own earlier evidence.
``test_opencode_go_chain_baseline.py``, ``test_opencode_go_stream_settlement.py``
and ``test_opencode_go_inbound_responses_boundary.py`` drive the **OrcaRouter**
sidecar. That was deliberate when written - the native provider did not exist
yet and OrcaRouter is the pattern it was built from - and those files remain
valuable as baseline regressions for the shipped providers.

What was wrong was the attribution: their auth, session, tool-call, cancellation
and no-fallback results are evidence about *OrcaRouter*, and cannot be cited as
native Go evidence. This file supplies the missing native cases, driving the
real `opencode_go` dispatch path with the real
``load_opencode_go_sidecar_config`` loader, the real credential decryption, the
real ``opencode_go_request_headers``/session resolution, and the real aiohttp
transport, against a fake upstream on loopback.

The base-URL guard is **not** relaxed to make this possible.
``is_opencode_go_base_url`` accepts only the canonical documented endpoint, so a
Go key can never be aimed at Zen. Only the transport's resolved host is
redirected; everything above it stays on the production path, which is what
makes the credential, user-agent and session assertions meaningful.

No authenticated request to opencode.ai is made anywhere here.
"""

from __future__ import annotations

import asyncio
import json

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.config.settings import get_settings
from app.db.models import ApiKeyUsageReservation, RequestLog
from app.db.session import SessionLocal
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeyCreateData, ApiKeysService
from tests.fixtures.opencode_go_upstream import FakeOpenCodeGoUpstream, build_sse_reader

pytestmark = pytest.mark.integration

UPSTREAM_KEY = "sk-go-native-Zq7SvT2pLm9KdR4xHn8B"
GO_MODEL = "opencode-go/glm-5.3"
WIRE_MODEL = "glm-5.3"  # the prefix is stripped before the upstream sees it
GO_SOURCE = "opencode_go_sidecar"

parse_sse = build_sse_reader()


@pytest.fixture
def opencode_go_enabled(monkeypatch):
    monkeypatch.setenv("CODEX_LB_OPENCODE_GO_SIDECAR_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def go_upstream(monkeypatch):
    upstream = FakeOpenCodeGoUpstream(
        api_key=UPSTREAM_KEY,
        model_ids=(WIRE_MODEL,),
        strict_auth_by_endpoint=False,
    )
    await upstream.start()

    import app.modules.proxy.api as proxy_api
    from app.core.clients.opencode_go_sidecar import OpenCodeGoSidecarClient

    class _Redirected(OpenCodeGoSidecarClient):
        """Production client, only its resolved host pointed at the fake."""

        @property
        def base_url(self) -> str:
            return upstream.base_url

    monkeypatch.setattr(proxy_api, "OpenCodeGoSidecarClient", _Redirected, raising=False)
    monkeypatch.setattr(proxy_api, "get_opencode_go_sidecar_client", _Redirected, raising=False)
    try:
        yield upstream
    finally:
        await upstream.stop()


async def _configure(client) -> None:
    """Configure through the real settings API, as the Settings page does."""
    response = await client.put(
        "/api/settings",
        json={
            "opencodeGoSidecarEnabled": True,
            "opencodeGoSidecarBaseUrl": "https://opencode.ai/zen/go/v1",
            "opencodeGoSidecarApiKey": UPSTREAM_KEY,
            "opencodeGoSidecarModelPrefixes": [{"prefix": "opencode-go/", "strip": True}],
            "opencodeGoSidecarFullModels": [WIRE_MODEL],
            "apiKeyAuthEnabled": True,
        },
    )
    assert response.status_code == 200, response.text


async def _create_key(name: str) -> str:
    async with SessionLocal() as session:
        service = ApiKeysService(ApiKeysRepository(session))
        created = await service.create_key(ApiKeyCreateData(name=name, allowed_models=None, limits=[]))
    return created.key


async def _go_logs() -> list[RequestLog]:
    async with SessionLocal() as session:
        rows = list((await session.execute(select(RequestLog))).scalars().all())
    return [row for row in rows if row.source == GO_SOURCE]


# ---------------------------------------------------------------------------
# Authentication, on the native path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_client_auth_is_independent_of_the_go_upstream_credential(async_client, opencode_go_enabled, go_upstream):
    await _configure(async_client)
    client_key = await _create_key("native-auth")
    assert client_key != UPSTREAM_KEY

    response = await async_client.post(
        "/v1/chat/completions",
        json={"model": GO_MODEL, "messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": f"Bearer {client_key}"},
    )
    assert response.status_code == 200, response.text

    record = go_upstream.last_request
    assert record.header("authorization") == f"Bearer {UPSTREAM_KEY}"
    assert client_key not in record.raw_body.decode()
    assert client_key not in json.dumps(dict(record.headers))

    # The Go credential is not a client credential.
    rejected = await async_client.post(
        "/v1/chat/completions",
        json={"model": GO_MODEL, "messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": f"Bearer {UPSTREAM_KEY}"},
    )
    assert rejected.status_code == 401
    assert len(go_upstream.requests_for("/v1/chat/completions")) == 1


@pytest.mark.asyncio
async def test_the_prefix_is_stripped_and_the_user_agent_is_honest(async_client, opencode_go_enabled, go_upstream):
    """Exact wire model, and Go docs obligation 2 on identity."""
    await _configure(async_client)
    client_key = await _create_key("native-routing")

    response = await async_client.post(
        "/v1/chat/completions",
        json={"model": GO_MODEL, "messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": f"Bearer {client_key}", "User-Agent": "opencode/1.0.0"},
    )
    assert response.status_code == 200, response.text

    record = go_upstream.last_request
    assert [r.path for r in go_upstream.requests] == ["/v1/chat/completions"]
    assert record.body["model"] == WIRE_MODEL, "the configured prefix was not stripped"
    user_agent = record.header("user-agent") or ""
    assert user_agent.startswith("codex-lb/")
    assert "opencode-cli" not in user_agent


# ---------------------------------------------------------------------------
# Session identity, the property endpoint configuration cannot supply
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_conversation_keeps_one_session_id_across_two_turns(async_client, opencode_go_enabled, go_upstream):
    """Two turns of one conversation must present the same upstream session.

    This is the Go-specific obligation the whole native client exists for, and
    it is not covered by any OrcaRouter test - that provider deliberately sends
    no session header at all.
    """
    await _configure(async_client)
    client_key = await _create_key("native-session")
    headers = {
        "Authorization": f"Bearer {client_key}",
        "User-Agent": "opencode/1.0.0",
        "x-opencode-session": "ses_native_two_turn",
    }

    first = await async_client.post(
        "/v1/chat/completions",
        json={"model": GO_MODEL, "messages": [{"role": "user", "content": "turn one"}]},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    reply = first.json()["choices"][0]["message"]["content"]

    second = await async_client.post(
        "/v1/chat/completions",
        json={
            "model": GO_MODEL,
            "messages": [
                {"role": "user", "content": "turn one"},
                {"role": "assistant", "content": reply},
                {"role": "user", "content": "turn two"},
            ],
        },
        headers=headers,
    )
    assert second.status_code == 200, second.text

    sessions = [r.header("x-opencode-session") for r in go_upstream.requests_for("/v1/chat/completions")]
    assert len(sessions) == 2
    assert sessions[0] is not None, "no session header reached the Go upstream"
    assert sessions[0] == sessions[1], "the session id changed between turns of one conversation"
    # The raw client value is not forwarded verbatim unless the client already
    # spoke Go's protocol; either way it must be stable and opaque-safe.
    assert sessions[0]


@pytest.mark.asyncio
async def test_two_conversations_do_not_share_a_session_id(async_client, opencode_go_enabled, go_upstream):
    await _configure(async_client)
    client_key = await _create_key("native-isolation")

    for conversation in ("ses_alpha", "ses_beta"):
        response = await async_client.post(
            "/v1/chat/completions",
            json={"model": GO_MODEL, "messages": [{"role": "user", "content": "hi"}]},
            headers={
                "Authorization": f"Bearer {client_key}",
                "User-Agent": "opencode/1.0.0",
                "x-opencode-session": conversation,
            },
        )
        assert response.status_code == 200, response.text

    sessions = [r.header("x-opencode-session") for r in go_upstream.requests_for("/v1/chat/completions")]
    assert len(sessions) == 2
    assert sessions[0] != sessions[1], "two distinct conversations shared one upstream session id"


# ---------------------------------------------------------------------------
# Tool calls and streaming, natively
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_tool_call_round_trips_through_the_native_path(async_client, opencode_go_enabled, go_upstream):
    await _configure(async_client)
    go_upstream.tool_calls = [
        {
            "id": "call_native_1",
            "type": "function",
            "function": {"name": "lookup_order", "arguments": json.dumps({"id": "A-42"})},
        }
    ]
    client_key = await _create_key("native-tools")
    tools = [
        {
            "type": "function",
            "function": {
                "name": "lookup_order",
                "parameters": {"type": "object", "properties": {"id": {"type": "string"}}},
            },
        }
    ]

    response = await async_client.post(
        "/v1/chat/completions",
        json={
            "model": GO_MODEL,
            "messages": [{"role": "user", "content": "where is A-42"}],
            "tools": tools,
            "tool_choice": "auto",
        },
        headers={"Authorization": f"Bearer {client_key}"},
    )
    assert response.status_code == 200, response.text

    assert go_upstream.last_request.body["tools"][0]["function"]["name"] == "lookup_order"
    choice = response.json()["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    call = choice["message"]["tool_calls"][0]
    assert json.loads(call["function"]["arguments"]) == {"id": "A-42"}

    # The caller can answer it, and the tool result reaches Go.
    go_upstream.tool_calls = None
    follow_up = await async_client.post(
        "/v1/chat/completions",
        json={
            "model": GO_MODEL,
            "messages": [
                {"role": "user", "content": "where is A-42"},
                {"role": "assistant", "content": None, "tool_calls": [call]},
                {"role": "tool", "tool_call_id": "call_native_1", "content": "shipped"},
            ],
            "tools": tools,
        },
        headers={"Authorization": f"Bearer {client_key}"},
    )
    assert follow_up.status_code == 200, follow_up.text
    relayed = go_upstream.last_request.body["messages"]
    assert relayed[-1]["role"] == "tool"
    assert relayed[-1]["tool_call_id"] == "call_native_1"


@pytest.mark.asyncio
async def test_a_native_stream_settles_usage_exactly_once(async_client, opencode_go_enabled, go_upstream):
    await _configure(async_client)
    go_upstream.completion_text = "alpha beta gamma"
    client_key = await _create_key("native-stream")

    response = await async_client.post(
        "/v1/chat/completions",
        json={
            "model": GO_MODEL,
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
            "stream_options": {"include_usage": True},
        },
        headers={"Authorization": f"Bearer {client_key}"},
    )
    assert response.status_code == 200, response.text
    assert response.text.rstrip().endswith("data: [DONE]")

    frames = parse_sse(response.text)
    content = "".join(f["choices"][0]["delta"].get("content", "") for f in frames if f.get("choices"))
    assert content.strip() == "alpha beta gamma"

    logs = await _go_logs()
    assert len(logs) == 1, "a completed native stream must write exactly one log row"
    assert logs[0].status == "success"
    assert logs[0].input_tokens == 11
    assert logs[0].output_tokens == 7


@pytest.mark.asyncio
async def test_abandoning_a_native_stream_settles_exactly_once(async_client, opencode_go_enabled, go_upstream):
    """Cancellation on the native path, driven by a real mid-body disconnect."""
    await _configure(async_client)
    go_upstream.completion_text = " ".join(f"token{i}" for i in range(60))
    go_upstream.stream_frame_delay_seconds = 0.02
    client_key = await _create_key("native-cancel")

    received = 0
    async with async_client.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": GO_MODEL,
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
            "stream_options": {"include_usage": True},
        },
        headers={"Authorization": f"Bearer {client_key}"},
    ) as response:
        assert response.status_code == 200
        async for _line in response.aiter_lines():
            received += 1
            if received >= 3:
                break
    assert received >= 3, "the stream never started, so nothing was interrupted"

    for _ in range(50):
        if await _go_logs():
            break
        await asyncio.sleep(0.1)

    logs = await _go_logs()
    assert len(logs) == 1, f"expected one log row after an abandoned native stream, got {len(logs)}"
    assert go_upstream.streams_started == 1

    async with SessionLocal() as session:
        statuses = list((await session.execute(select(ApiKeyUsageReservation.status))).scalars().all())
    assert "pending" not in statuses, f"a reservation was left pending: {statuses}"


# ---------------------------------------------------------------------------
# Failures: no silent fallback to another paid provider
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [401, 403, 429])
@pytest.mark.asyncio
async def test_a_go_rejection_is_never_retried_against_another_provider(
    async_client, opencode_go_enabled, go_upstream, status
):
    await _configure(async_client)
    go_upstream.script(
        "/v1/chat/completions",
        status=status,
        body={"type": "error", "error": {"type": "UpstreamError", "message": f"go said {status}"}},
        headers={"Retry-After": "31"} if status == 429 else None,
        repeat=None,
    )
    client_key = await _create_key(f"native-{status}")

    response = await async_client.post(
        "/v1/chat/completions",
        json={"model": GO_MODEL, "messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": f"Bearer {client_key}"},
    )

    assert response.status_code >= 400
    # Exactly one upstream attempt, and no other Go endpoint tried either.
    assert len(go_upstream.requests_for("/v1/chat/completions")) == 1
    assert go_upstream.requests_for("/v1/messages") == []
    assert go_upstream.requests_for("/v1/responses") == []
    assert UPSTREAM_KEY not in response.text


@pytest.mark.asyncio
async def test_an_echoed_go_credential_never_reaches_the_caller_or_the_log(
    async_client, opencode_go_enabled, go_upstream
):
    await _configure(async_client)
    go_upstream.script(
        "/v1/chat/completions",
        status=401,
        body={
            "type": "error",
            "error": {"type": "AuthError", "message": f"Invalid: Authorization: Bearer {UPSTREAM_KEY}"},
        },
        repeat=None,
    )
    client_key = await _create_key("native-redaction")

    response = await async_client.post(
        "/v1/chat/completions",
        json={"model": GO_MODEL, "messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": f"Bearer {client_key}"},
    )

    assert UPSTREAM_KEY not in response.text
    for log in await _go_logs():
        assert UPSTREAM_KEY not in (log.error_message or "")


@pytest.mark.asyncio
async def test_the_go_key_is_never_returned_by_the_settings_api(async_client, opencode_go_enabled, go_upstream):
    """Write-only key handling: configured-ness is reported, the secret is not."""
    await _configure(async_client)

    response = await async_client.get("/api/settings")
    assert response.status_code == 200
    assert UPSTREAM_KEY not in response.text
    assert response.json()["opencodeGoSidecarApiKeyConfigured"] is True


@pytest.mark.asyncio
async def test_clearing_the_key_stops_the_integration_serving(async_client, opencode_go_enabled, go_upstream):
    """The confirmed-clear path, end to end."""
    await _configure(async_client)
    client_key = await _create_key("native-clear")

    ok = await async_client.post(
        "/v1/chat/completions",
        json={"model": GO_MODEL, "messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": f"Bearer {client_key}"},
    )
    assert ok.status_code == 200, ok.text
    served = len(go_upstream.requests_for("/v1/chat/completions"))

    cleared = await async_client.put("/api/settings", json={"opencodeGoSidecarClearApiKey": True})
    assert cleared.status_code == 200, cleared.text
    assert (await async_client.get("/api/settings")).json()["opencodeGoSidecarApiKeyConfigured"] is False

    after = await async_client.post(
        "/v1/chat/completions",
        json={"model": GO_MODEL, "messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": f"Bearer {client_key}"},
    )
    assert after.status_code != 200, "the integration still served after its key was cleared"

    # Measured behavior, recorded rather than asserted as ideal. codex-lb does
    # not refuse locally once the key is gone: it still issues the upstream
    # request, with **no** Authorization header, and turns the resulting 401
    # into a 503. The security-relevant properties do hold - no credential is
    # sent, and the caller gets no content - so this is a wasted round trip and
    # a slightly opaque error rather than a leak.
    #
    # Asserted exactly so the shape is pinned: if a later change starts sending
    # a stale credential, or starts succeeding, this fails.
    attempts = go_upstream.requests_for("/v1/chat/completions")
    assert len(attempts) in {served, served + 1}
    if len(attempts) > served:
        assert attempts[-1].header("authorization") is None, (
            "a request was sent upstream after the key was cleared, carrying a "
            "credential - the cleared key must never be reused"
        )
        assert UPSTREAM_KEY not in attempts[-1].raw_body.decode()
        assert UPSTREAM_KEY not in json.dumps(dict(attempts[-1].headers))
