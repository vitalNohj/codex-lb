"""Cross-layer chain tests: real client -> codex-lb -> real socket -> fake Go upstream.

What makes these different from the existing sidecar tests
----------------------------------------------------------
Every sidecar test in this repo installs a fake *client object* via monkeypatch
(``_install_fake_orcarouter`` and friends). That is the right tool for dispatch
and accounting questions, but it deletes the layer this task has to verify: no
HTTP request is built, no authentication header is chosen, no SSE bytes cross a
socket, and a disconnect is a Python exception rather than a closed connection.

These tests instead stand up the fake OpenCode Go upstream on a real loopback
port, point a codex-lb integration's ``base_url`` at it, and drive traffic in
through ``POST /v1/chat/completions`` exactly as an end user's client would. The
whole chain runs: FastAPI routing, API-key authentication, model routing,
the real ``aiohttp`` client, real request headers, real SSE framing, and real
request-log persistence.

Scope and honesty about what is verified
----------------------------------------
A native ``opencode_go`` provider does not exist on this branch yet; it is owned
by ``codexlb-opencode-go-integration``. So these tests drive the chain through
the existing OrcaRouter sidecar, which is the exact integration pattern the
coordination document names as the baseline for the new provider.

That makes them two things at once, and neither is overstated:

1. **Executable baseline invariants.** Behavior the new provider must also
   satisfy, pinned now so a regression introduced while adding Go is caught.
2. **Evidence about the chain's real wire behavior**, captured from bytes rather
   than from reading source. Where that evidence shows a gap the Go integration
   will have to close - most importantly the conversation/session header, see
   ``test_no_conversation_identity_reaches_the_upstream_today`` - the test
   records the gap as a fact rather than asserting a desired future.

**Nothing here is verification against the real opencode.ai.** No authenticated
request is made to any provider, and no test infers live provider behavior from
a fixture the test itself wrote. Claims about the live provider's per-endpoint
auth, usage windows, or model catalog remain exactly as unverified as the
prior-art report left them.
"""

from __future__ import annotations

import asyncio
import json

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.config.settings import get_settings
from app.db.models import RequestLog
from app.db.session import SessionLocal
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeyCreateData, ApiKeysService
from tests.fixtures.opencode_go_upstream import (
    FakeOpenCodeGoUpstream,
    build_sse_reader,
)

pytestmark = pytest.mark.integration

# The credential the *upstream* accepts. Deliberately shaped like a real key so
# the redaction assertions exercise the credential-bearing branch of the
# sanitizer rather than its "short alphabetic word" escape hatch.
UPSTREAM_KEY = "sk-orca-go-e2e-Zq7SvT2pLm9KdR4xHn8B"

# The routing prefix under which the fake upstream's models are reached. Carried
# through unchanged (strip=False) so the wire model the upstream receives is
# asserted exactly.
PREFIX = "orcarouter/"
WIRE_MODEL = f"{PREFIX}glm-5.3"
# What the upstream agrees to serve. With ``strip=False`` the prefix is part of
# the wire model, so the fixture's catalog holds the prefixed ids: that is what
# makes "the upstream received exactly this id" a real assertion instead of a
# fixture that answers to anything.
SERVED_MODEL_IDS = (WIRE_MODEL, f"{PREFIX}deepseek-v4-flash")

parse_sse = build_sse_reader()


@pytest.fixture
def sidecar_capability_enabled(monkeypatch):
    monkeypatch.setenv("CODEX_LB_ORCAROUTER_SIDECAR_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def go_upstream():
    """A fake Go upstream on a real loopback port.

    Permissive auth mode: this fixture's purpose is the *chain*, and pinning the
    reported per-endpoint auth split belongs in the fixture's own contract tests
    where it is labelled as a third-party claim.
    """
    upstream = FakeOpenCodeGoUpstream(
        api_key=UPSTREAM_KEY,
        model_ids=SERVED_MODEL_IDS,
        strict_auth_by_endpoint=False,
    )
    await upstream.start()
    try:
        yield upstream
    finally:
        await upstream.stop()


async def _configure_chain(client, upstream: FakeOpenCodeGoUpstream) -> None:
    """Point the integration at the fake upstream through the real settings API."""
    response = await client.put(
        "/api/settings",
        json={
            "orcarouterSidecarEnabled": True,
            "orcarouterSidecarBaseUrl": upstream.base_url,
            "orcarouterSidecarApiKey": UPSTREAM_KEY,
            "orcarouterSidecarModelPrefixes": [{"prefix": PREFIX, "strip": False}],
            "apiKeyAuthEnabled": True,
        },
    )
    assert response.status_code == 200, response.text


async def _create_client_key(name: str, *, allowed_models: list[str] | None = None) -> str:
    async with SessionLocal() as session:
        service = ApiKeysService(ApiKeysRepository(session))
        created = await service.create_key(ApiKeyCreateData(name=name, allowed_models=allowed_models, limits=[]))
    return created.key


async def _request_logs() -> list[RequestLog]:
    async with SessionLocal() as session:
        result = await session.execute(select(RequestLog))
        return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Authentication: the caller's credential and the upstream's are separate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_client_auth_is_independent_of_upstream_auth(
    async_client, sidecar_capability_enabled, go_upstream
):
    """The caller's API key authenticates to codex-lb and never leaves it.

    The two credentials are different secrets with different lifetimes. A chain
    that forwarded the caller's key upstream, or that accepted the upstream key
    as a client credential, would collapse that separation - so both directions
    are asserted.
    """
    await _configure_chain(async_client, go_upstream)
    client_key = await _create_client_key("chain-auth-key")
    assert client_key != UPSTREAM_KEY

    response = await async_client.post(
        "/v1/chat/completions",
        json={"model": WIRE_MODEL, "messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": f"Bearer {client_key}"},
    )
    assert response.status_code == 200, response.text

    upstream_request = go_upstream.last_request
    # Direction 1: the upstream received the upstream credential, not the caller's.
    assert upstream_request.header("authorization") == f"Bearer {UPSTREAM_KEY}"
    assert client_key not in upstream_request.raw_body.decode()
    assert client_key not in json.dumps(dict(upstream_request.headers))

    # Direction 2: the upstream credential is not accepted as a client credential.
    rejected = await async_client.post(
        "/v1/chat/completions",
        json={"model": WIRE_MODEL, "messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": f"Bearer {UPSTREAM_KEY}"},
    )
    assert rejected.status_code == 401
    # And that rejection never became an upstream call.
    assert len(go_upstream.requests_for("/v1/chat/completions")) == 1


@pytest.mark.asyncio
async def test_a_caller_without_a_key_never_reaches_the_upstream(
    async_client, sidecar_capability_enabled, go_upstream
):
    await _configure_chain(async_client, go_upstream)

    response = await async_client.post(
        "/v1/chat/completions",
        json={"model": WIRE_MODEL, "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 401
    assert go_upstream.requests == []


# ---------------------------------------------------------------------------
# Routing: exact endpoint and exact wire model
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_reaches_the_exact_endpoint_with_the_exact_wire_model(
    async_client, sidecar_capability_enabled, go_upstream
):
    """Endpoint and model are asserted exactly, not by substring.

    The single most common Go bug in the surveyed prior art is a model sent to
    the wrong endpoint, so "some request arrived" is not an acceptable
    assertion here.
    """
    await _configure_chain(async_client, go_upstream)
    client_key = await _create_client_key("chain-routing-key")

    response = await async_client.post(
        "/v1/chat/completions",
        json={"model": WIRE_MODEL, "messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": f"Bearer {client_key}"},
    )
    assert response.status_code == 200

    assert [record.path for record in go_upstream.requests] == ["/v1/chat/completions"]
    # Not /messages, not /responses: with strip=False the configured prefix is
    # carried through verbatim rather than silently rewritten.
    assert go_upstream.requests_for("/v1/messages") == []
    assert go_upstream.requests_for("/v1/responses") == []
    assert go_upstream.last_request.body["model"] == WIRE_MODEL


@pytest.mark.asyncio
async def test_a_model_outside_this_integration_never_reaches_its_upstream(
    async_client, sidecar_capability_enabled, go_upstream
):
    """Provider isolation: an unrelated model must not be sent to this upstream."""
    await _configure_chain(async_client, go_upstream)
    client_key = await _create_client_key("chain-isolation-key")

    response = await async_client.post(
        "/v1/chat/completions",
        json={"model": "gpt-5.4", "messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": f"Bearer {client_key}"},
    )

    # It fails for want of an OpenAI upstream, which is the point: it failed
    # somewhere other than this integration.
    assert response.status_code in {401, 500, 502, 503}
    assert go_upstream.requests == []


@pytest.mark.asyncio
async def test_a_disabled_integration_is_not_reachable_at_all(
    async_client, sidecar_capability_enabled, go_upstream
):
    """Configured but switched off must mean no traffic, not degraded traffic."""
    await _configure_chain(async_client, go_upstream)
    disable = await async_client.put("/api/settings", json={"orcarouterSidecarEnabled": False})
    assert disable.status_code == 200
    client_key = await _create_client_key("chain-disabled-key")

    response = await async_client.post(
        "/v1/chat/completions",
        json={"model": WIRE_MODEL, "messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": f"Bearer {client_key}"},
    )

    assert response.status_code != 200
    assert go_upstream.requests == []


# ---------------------------------------------------------------------------
# Streaming: ordering, termination, usage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sse_frames_keep_their_order_and_terminate_through_the_whole_chain(
    async_client, sidecar_capability_enabled, go_upstream
):
    await _configure_chain(async_client, go_upstream)
    go_upstream.completion_text = "alpha beta gamma"
    client_key = await _create_client_key("chain-stream-key")

    response = await async_client.post(
        "/v1/chat/completions",
        json={
            "model": WIRE_MODEL,
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
            "stream_options": {"include_usage": True},
        },
        headers={"Authorization": f"Bearer {client_key}"},
    )

    assert response.status_code == 200
    body = response.text
    # Termination is asserted on the raw text: a client that never sees [DONE]
    # hangs, and a parsed-frame assertion would not catch a missing sentinel.
    assert body.rstrip().endswith("data: [DONE]")

    frames = parse_sse(body)
    content = "".join(
        frame["choices"][0]["delta"].get("content", "") for frame in frames if frame.get("choices")
    )
    assert content.strip() == "alpha beta gamma"

    finishes = [
        frame["choices"][0]["finish_reason"]
        for frame in frames
        if frame.get("choices") and frame["choices"][0].get("finish_reason")
    ]
    assert finishes == ["stop"], "exactly one terminal finish_reason, in order"

    usage_frames = [frame for frame in frames if frame.get("choices") == [] and "usage" in frame]
    assert len(usage_frames) == 1
    assert usage_frames[0]["usage"]["prompt_tokens"] == 11
    assert usage_frames[0]["usage"]["completion_tokens"] == 7


@pytest.mark.asyncio
async def test_two_turns_of_one_conversation_both_complete_over_the_same_chain(
    async_client, sidecar_capability_enabled, go_upstream
):
    """Session stability, measured as behavior rather than as a header claim.

    A second turn carrying the assistant's first reply must succeed and must
    carry the accumulated history upstream. This is the property an end user
    actually observes; what identifier travels with it is asserted separately in
    ``test_no_conversation_identity_reaches_the_upstream_today``.
    """
    await _configure_chain(async_client, go_upstream)
    client_key = await _create_client_key("chain-two-turn-key")
    headers = {
        "Authorization": f"Bearer {client_key}",
        "User-Agent": "opencode/1.0.0",
        "x-opencode-session": "ses_two_turn_fixture",
    }

    first = await async_client.post(
        "/v1/chat/completions",
        json={"model": WIRE_MODEL, "messages": [{"role": "user", "content": "turn one"}]},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    reply = first.json()["choices"][0]["message"]["content"]

    second = await async_client.post(
        "/v1/chat/completions",
        json={
            "model": WIRE_MODEL,
            "messages": [
                {"role": "user", "content": "turn one"},
                {"role": "assistant", "content": reply},
                {"role": "user", "content": "turn two"},
            ],
        },
        headers=headers,
    )
    assert second.status_code == 200, second.text

    chat_requests = go_upstream.requests_for("/v1/chat/completions")
    assert len(chat_requests) == 2
    assert [len(record.body["messages"]) for record in chat_requests] == [1, 3]
    assert chat_requests[1].body["messages"][-1]["content"] == "turn two"
    # Both turns used the same upstream credential; a second turn must not
    # silently fall back to an unauthenticated or different-credential path.
    assert {record.header("authorization") for record in chat_requests} == {f"Bearer {UPSTREAM_KEY}"}


# ---------------------------------------------------------------------------
# Tool calls
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_call_round_trip_survives_the_chain_in_both_directions(
    async_client, sidecar_capability_enabled, go_upstream
):
    await _configure_chain(async_client, go_upstream)
    go_upstream.tool_calls = [
        {
            "id": "call_chain_1",
            "type": "function",
            "function": {"name": "lookup_order", "arguments": json.dumps({"id": "A-42"})},
        }
    ]
    client_key = await _create_client_key("chain-tool-key")
    tools = [
        {
            "type": "function",
            "function": {
                "name": "lookup_order",
                "description": "Look an order up",
                "parameters": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}},
                    "required": ["id"],
                },
            },
        }
    ]

    response = await async_client.post(
        "/v1/chat/completions",
        json={
            "model": WIRE_MODEL,
            "messages": [{"role": "user", "content": "where is order A-42"}],
            "tools": tools,
            "tool_choice": "auto",
        },
        headers={"Authorization": f"Bearer {client_key}"},
    )

    assert response.status_code == 200, response.text
    # Outbound: the tool declaration reached the upstream intact.
    sent = go_upstream.last_request.body
    assert sent["tools"][0]["function"]["name"] == "lookup_order"
    assert sent["tool_choice"] == "auto"

    # Inbound: the tool call came back to the caller intact.
    choice = response.json()["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    call = choice["message"]["tool_calls"][0]
    assert call["id"] == "call_chain_1"
    assert call["function"]["name"] == "lookup_order"
    assert json.loads(call["function"]["arguments"]) == {"id": "A-42"}

    # And the caller can answer it: a tool result round-trips upstream.
    go_upstream.tool_calls = None
    follow_up = await async_client.post(
        "/v1/chat/completions",
        json={
            "model": WIRE_MODEL,
            "messages": [
                {"role": "user", "content": "where is order A-42"},
                {"role": "assistant", "content": None, "tool_calls": [call]},
                {"role": "tool", "tool_call_id": "call_chain_1", "content": "shipped"},
            ],
            "tools": tools,
        },
        headers={"Authorization": f"Bearer {client_key}"},
    )
    assert follow_up.status_code == 200, follow_up.text
    relayed = go_upstream.last_request.body["messages"]
    assert relayed[-1]["role"] == "tool"
    assert relayed[-1]["tool_call_id"] == "call_chain_1"


# ---------------------------------------------------------------------------
# Upstream failures: status, Retry-After, and no paid fallback
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [401, 403, 429])
@pytest.mark.asyncio
async def test_upstream_rejection_is_reported_and_never_silently_retried_elsewhere(
    async_client, sidecar_capability_enabled, go_upstream, status
):
    """A rejection must surface as a failure, not as a quiet failover.

    The captain's constraint is explicit: never route a Go failure to Zen or any
    other paid provider. The strong form of that is asserted here - after the
    rejection the caller gets an error AND exactly one upstream call was made,
    so no second provider was tried behind the user's back.
    """
    await _configure_chain(async_client, go_upstream)
    go_upstream.script(
        "/v1/chat/completions",
        status=status,
        body={"type": "error", "error": {"type": "UpstreamError", "message": f"upstream said {status}"}},
        headers={"Retry-After": "31"} if status == 429 else None,
        repeat=None,
    )
    client_key = await _create_client_key(f"chain-{status}-key")

    response = await async_client.post(
        "/v1/chat/completions",
        json={"model": WIRE_MODEL, "messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": f"Bearer {client_key}"},
    )

    assert response.status_code >= 400
    assert response.status_code != 200
    assert len(go_upstream.requests_for("/v1/chat/completions")) == 1
    # No other endpoint on this upstream was tried either.
    assert go_upstream.requests_for("/v1/messages") == []
    assert go_upstream.requests_for("/v1/responses") == []


@pytest.mark.asyncio
async def test_a_429_is_logged_as_an_error_but_the_upstream_status_is_not_recorded(
    async_client, sidecar_capability_enabled, go_upstream
):
    """Characterizes a real gap in the baseline the Go provider will copy.

    ``RequestLog`` has an ``upstream_status_code`` column, the dashboard's
    request table reads it, and the main proxy path populates it. The sidecar
    dispatchers never pass it, so an operator looking at a failed sidecar
    request sees ``error`` and a message but cannot tell a 429 from a 403 in the
    column built for exactly that.

    This is asserted as **current behavior**, not as desired behavior: weakening
    the test to "some log exists" would hide the gap, and asserting the fixed
    behavior would fail a branch that has not shipped the fix. The distinction
    matters for Go specifically, because 429 is the shape a subscription quota
    exhaustion arrives in and the Accounts card is meant to explain it.

    Reported to the backend owner; see report.md.
    """
    await _configure_chain(async_client, go_upstream)
    go_upstream.script(
        "/v1/chat/completions",
        status=429,
        body={"type": "error", "error": {"type": "RateLimitError", "message": "slow down"}},
        headers={"Retry-After": "31"},
        repeat=None,
    )
    client_key = await _create_client_key("chain-429-log-key")

    response = await async_client.post(
        "/v1/chat/completions",
        json={"model": WIRE_MODEL, "messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": f"Bearer {client_key}"},
    )
    assert response.status_code >= 400

    logs = [log for log in await _request_logs() if log.source == "orcarouter_sidecar"]
    assert len(logs) == 1
    log = logs[0]
    # What IS recorded, and is genuinely useful.
    assert log.status == "error"
    assert log.failure_phase == "sidecar"
    assert log.error_code == "orcarouter_sidecar_error"
    assert "slow down" in (log.error_message or "")
    # What is NOT, and should be. Pinned so the fix flips this assertion
    # deliberately rather than passing unnoticed.
    assert log.upstream_status_code is None, (
        "upstream_status_code is now populated on the sidecar path - update this "
        "characterization test to assert 429 and drop the recorded gap from report.md"
    )


@pytest.mark.asyncio
async def test_an_unreachable_upstream_fails_cleanly_rather_than_hanging_or_500ing(
    async_client, sidecar_capability_enabled, go_upstream
):
    await _configure_chain(async_client, go_upstream)
    client_key = await _create_client_key("chain-down-key")
    # Stop the upstream: the configured port now refuses connections. This is a
    # real transport failure, not a simulated exception.
    await go_upstream.stop()

    response = await asyncio.wait_for(
        async_client.post(
            "/v1/chat/completions",
            json={"model": WIRE_MODEL, "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": f"Bearer {client_key}"},
        ),
        timeout=30,
    )

    assert response.status_code == 503
    assert response.json()["error"]["message"]


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_upstream_credential_never_reaches_the_caller_or_the_request_log(
    async_client, sidecar_capability_enabled, go_upstream
):
    """An upstream that echoes the credential must not get it persisted or returned."""
    await _configure_chain(async_client, go_upstream)
    go_upstream.script(
        "/v1/chat/completions",
        status=401,
        body={
            "type": "error",
            "error": {
                "type": "AuthError",
                # The exact hostile case: the upstream quotes the header back.
                "message": f"Invalid credentials: Authorization: Bearer {UPSTREAM_KEY}",
            },
        },
        repeat=None,
    )
    client_key = await _create_client_key("chain-redaction-key")

    response = await async_client.post(
        "/v1/chat/completions",
        json={"model": WIRE_MODEL, "messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": f"Bearer {client_key}"},
    )

    assert UPSTREAM_KEY not in response.text
    logs = [log for log in await _request_logs() if log.source == "orcarouter_sidecar"]
    assert logs, "the failed request was not logged at all"
    for log in logs:
        assert UPSTREAM_KEY not in (log.error_message or "")


@pytest.mark.asyncio
async def test_the_configured_key_is_never_returned_by_the_settings_api(
    async_client, sidecar_capability_enabled, go_upstream
):
    await _configure_chain(async_client, go_upstream)

    response = await async_client.get("/api/settings")

    assert response.status_code == 200
    assert UPSTREAM_KEY not in response.text
    # Configured-ness is still reported, so the UI can show a disabled/keyed
    # state without ever handling the secret.
    assert response.json()["orcarouterSidecarApiKeyConfigured"] is True


# ---------------------------------------------------------------------------
# Recorded gap: conversation identity at hop 1
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_conversation_identity_reaches_the_upstream_today(
    async_client, sidecar_capability_enabled, go_upstream
):
    """Executable evidence for the session-header gap, captured from the wire.

    The prior-art report predicted this from reading source; this test measures
    it. codex-lb already extracts a conversation id from inbound OpenCode
    headers for request logging, but the sidecar clients build a fixed header
    dict with no per-request merge point, so nothing identifying the
    conversation reaches the upstream.

    That is **correct today** for the existing integrations - forwarding a
    client's session id to arbitrary third-party upstreams is the exact leak
    OmniRoute's maintainer scoped against - and it is the concrete piece of work
    an OpenCode Go provider has to do, for that one provider only. The test
    therefore asserts the current, safe behavior; when the Go provider lands, it
    needs its own positive test that the header is forwarded **only** on the Go
    path, and this test keeps guarding every other provider.
    """
    await _configure_chain(async_client, go_upstream)
    client_key = await _create_client_key("chain-session-key")

    response = await async_client.post(
        "/v1/chat/completions",
        json={"model": WIRE_MODEL, "messages": [{"role": "user", "content": "hi"}]},
        headers={
            "Authorization": f"Bearer {client_key}",
            "User-Agent": "opencode/1.0.0",
            "x-opencode-session": "ses_client_supplied_value",
            "x-session-affinity": "ses_client_supplied_value",
        },
    )
    assert response.status_code == 200, response.text

    record = go_upstream.last_request
    for header in ("x-opencode-session", "x-session-affinity", "x-session-id", "x-parent-session-id"):
        assert record.header(header) is None, (
            f"{header} reached a non-OpenCode upstream; forwarding a client session id "
            "to arbitrary third-party providers is the leak this assertion guards"
        )
    assert "ses_client_supplied_value" not in record.raw_body.decode()

    # Second recorded gap, measured on the same request. codex-lb extracts an
    # inbound conversation id by user-agent prefix and stores it on the request
    # log, which is what the dashboard's conversation grouping and its
    # ``?conversation_id=`` filter are built on. The sidecar dispatchers never
    # pass ``conversation_id`` (nor ``useragent``) to ``add_log``, so every
    # sidecar request is an ungrouped orphan in that view even though the client
    # sent a perfectly good identifier.
    #
    # This compounds the header gap rather than duplicating it: a Go provider
    # that fixes only the outbound header would still leave its own traffic
    # unattributable in the operator's own dashboard.
    logs = [log for log in await _request_logs() if log.source == "orcarouter_sidecar"]
    assert len(logs) == 1
    assert logs[0].conversation_id is None, (
        "sidecar request logs now carry conversation_id - update this "
        "characterization test and drop the recorded gap from report.md"
    )
    assert logs[0].useragent is None


@pytest.mark.asyncio
async def test_the_outbound_user_agent_identifies_codex_lb_rather_than_impersonating_a_client(
    async_client, sidecar_capability_enabled, go_upstream
):
    """OpenCode Go's stated obligation is that a client identify itself honestly.

    The surveyed prior art impersonates ``opencode-cli`` to dodge free-tier UA
    gating. That is the behavior this assertion exists to prevent inheriting.
    """
    await _configure_chain(async_client, go_upstream)
    client_key = await _create_client_key("chain-ua-key")

    response = await async_client.post(
        "/v1/chat/completions",
        json={"model": WIRE_MODEL, "messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": f"Bearer {client_key}", "User-Agent": "opencode/1.0.0"},
    )
    assert response.status_code == 200

    user_agent = go_upstream.last_request.header("user-agent") or ""
    assert user_agent.startswith("codex-lb/")
    assert "opencode-cli" not in user_agent
