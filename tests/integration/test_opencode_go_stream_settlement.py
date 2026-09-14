"""Streaming settlement and cancellation, over a real socket.

``contract.md`` section 9 makes a table of promises about what the client sees
and what the log row records for each upstream failure, and states that
"Reservations are always settled or released exactly once, including on
cancellation". Those promises are the ones an operator's billing and quota
accounting rest on, and they are the hardest to get right because they live in a
``finally`` block that has to run while a stream is being torn down.

The baseline dispatcher this lane verifies (`orcarouter_sidecar_dispatch`) has
exactly the shape the contract says the Go dispatcher will copy: a streaming
iterator whose ``finally`` settles usage, finalizes-or-releases the reservation,
and writes one log row. So these tests pin that shape's observable behavior now.

Every case drives a real client through codex-lb to a real loopback upstream and
asserts on bytes and persisted rows - not on a mocked client object, which would
delete the teardown path under test.

Cases covered here that no other file in this lane covers:
  * mid-stream upstream failure after content has already been delivered
  * a stream that ends without its ``[DONE]`` terminator
  * client disconnect mid-stream (cancellation)
  * exactly-once log/settlement accounting on each of the above

No authenticated request to any real provider is made.
"""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.config.settings import get_settings
from app.db.models import RequestLog
from app.db.session import SessionLocal
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeyCreateData, ApiKeysService
from tests.fixtures.opencode_go_upstream import FakeOpenCodeGoUpstream, build_sse_reader

pytestmark = pytest.mark.integration

UPSTREAM_KEY = "sk-orca-go-stream-Zq7SvT2pLm9KdR4xHn8B"
PREFIX = "orcarouter/"
WIRE_MODEL = f"{PREFIX}glm-5.3"

parse_sse = build_sse_reader()


@pytest.fixture
def sidecar_capability_enabled(monkeypatch):
    monkeypatch.setenv("CODEX_LB_ORCAROUTER_SIDECAR_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def go_upstream():
    upstream = FakeOpenCodeGoUpstream(
        api_key=UPSTREAM_KEY,
        model_ids=(WIRE_MODEL,),
        strict_auth_by_endpoint=False,
    )
    await upstream.start()
    try:
        yield upstream
    finally:
        await upstream.stop()


async def _configure(client, upstream: FakeOpenCodeGoUpstream) -> None:
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


async def _create_key(name: str) -> str:
    async with SessionLocal() as session:
        service = ApiKeysService(ApiKeysRepository(session))
        created = await service.create_key(ApiKeyCreateData(name=name, allowed_models=None, limits=[]))
    return created.key


async def _sidecar_logs() -> list[RequestLog]:
    async with SessionLocal() as session:
        rows = list((await session.execute(select(RequestLog))).scalars().all())
    return [row for row in rows if row.source == "orcarouter_sidecar"]


def _stream_body(model: str = WIRE_MODEL, *, include_usage: bool = True) -> dict:
    body: dict = {
        "model": model,
        "messages": [{"role": "user", "content": "hi"}],
        "stream": True,
    }
    if include_usage:
        body["stream_options"] = {"include_usage": True}
    return body


@pytest.mark.asyncio
async def test_a_completed_stream_logs_success_exactly_once_with_usage(
    async_client, sidecar_capability_enabled, go_upstream
):
    """The control case. Everything below is a deviation from this."""
    await _configure(async_client, go_upstream)
    go_upstream.completion_text = "alpha beta"
    client_key = await _create_key("stream-success-key")

    response = await async_client.post(
        "/v1/chat/completions",
        json=_stream_body(),
        headers={"Authorization": f"Bearer {client_key}"},
    )
    assert response.status_code == 200
    assert response.text.rstrip().endswith("data: [DONE]")

    logs = await _sidecar_logs()
    assert len(logs) == 1, "a completed stream must write exactly one log row"
    log = logs[0]
    assert log.status == "success"
    assert log.error_code is None
    # Usage observed from the trailing SSE frame, not guessed.
    assert log.input_tokens == 11
    assert log.output_tokens == 7


@pytest.mark.asyncio
async def test_an_upstream_failure_before_any_content_is_reported_to_the_client(
    async_client, sidecar_capability_enabled, go_upstream
):
    """A stream that fails at startup must still terminate the SSE properly.

    A client that never receives ``[DONE]`` hangs. The dispatcher converts the
    upstream error into an error frame plus a terminator, and that is what makes
    the failure survivable for an OpenAI-protocol client.
    """
    await _configure(async_client, go_upstream)
    go_upstream.script(
        "/v1/chat/completions",
        status=500,
        body={"type": "error", "error": {"type": "UpstreamError", "message": "upstream exploded"}},
        repeat=None,
    )
    client_key = await _create_key("stream-startup-failure-key")

    response = await async_client.post(
        "/v1/chat/completions",
        json=_stream_body(),
        headers={"Authorization": f"Bearer {client_key}"},
    )

    # Either a non-200 with a structured body, or a 200 SSE carrying an error
    # frame; both are legitimate, and both must be terminated/structured.
    if response.status_code == 200:
        assert response.text.rstrip().endswith("data: [DONE]"), "an errored stream was not terminated"
        frames = parse_sse(response.text)
        assert any("error" in frame for frame in frames), "no error frame reached the client"
    else:
        assert response.status_code >= 400
        assert "error" in response.json()

    assert UPSTREAM_KEY not in response.text

    logs = await _sidecar_logs()
    assert len(logs) == 1, "exactly one log row for one failed stream"
    assert logs[0].status == "error"
    assert logs[0].failure_phase == "sidecar"


@pytest.mark.asyncio
async def test_a_stream_truncated_before_done_is_recorded_as_an_error_not_a_success(
    async_client, sidecar_capability_enabled, go_upstream
):
    """The silent-truncation case, and the reason ``completed`` is tracked.

    The upstream delivers real content and then the connection ends without the
    ``[DONE]`` terminator. The client got partial output. If this were logged as
    a success, an operator would have no signal that answers are being cut off,
    and the reservation would settle as though the work completed normally.

    ``contract.md`` section 9 names this exact case
    (``opencode_go_sidecar_stream_incomplete``); this pins the baseline it copies.
    """
    await _configure(async_client, go_upstream)
    client_key = await _create_key("stream-truncated-key")

    go_upstream.completion_text = "partial answer here"
    # Role frame + two content frames, then EOF. No finish frame, no [DONE].
    go_upstream.truncate_stream_after_frames = 3

    response = await async_client.post(
        "/v1/chat/completions",
        json=_stream_body(),
        headers={"Authorization": f"Bearer {client_key}"},
    )
    assert response.status_code == 200

    # Frame-level assertions on exactly what the client received. The upstream
    # wrote 3 frames and then EOF'd, and the body must reflect that truthfully.
    frames = parse_sse(response.text)
    assert len(frames) == 3, f"expected the 3 upstream frames relayed verbatim, got {len(frames)}"
    assert frames[0]["choices"][0]["delta"] == {"role": "assistant", "content": ""}
    delivered = "".join(frame["choices"][0]["delta"].get("content", "") for frame in frames)
    assert delivered.strip() == "partial answer", "the partial content was not relayed intact"

    # No frame carries a finish_reason: the generation was cut off, and nothing
    # downstream may invent a terminal one.
    assert all(frame["choices"][0].get("finish_reason") is None for frame in frames)

    # The distinguishing assertion. A truncated upstream is passed through as a
    # truncated stream: this build synthesizes NO terminator and NO error frame
    # on this path, so the client sees the truncation rather than a fabricated
    # clean ending. Exact counts, so a future change in either direction - a
    # synthesized [DONE] that would disguise truncation as success, or an added
    # error frame - fails here and gets reviewed deliberately.
    assert response.text.count("data: [DONE]") == 0, (
        "a [DONE] terminator appeared for a stream the upstream never terminated; "
        "if this is a deliberate downstream-synthesized terminator it must be "
        "reviewed, because it makes a truncated answer look complete to the client"
    )
    assert not any("error" in frame for frame in frames), (
        "an error frame was synthesized on the truncation path; update this test "
        "deliberately if that becomes intended behavior"
    )

    # And the server-side record does not call it a success.
    logs = await _sidecar_logs()
    assert len(logs) == 1, "exactly one log row for one truncated stream"
    log = logs[0]
    assert log.status == "error", (
        "a stream that ended without [DONE] was logged as a success; truncated "
        "answers would then be invisible to the operator"
    )
    assert log.error_code == "orcarouter_sidecar_stream_incomplete"

    # Limit, recorded rather than asserted: because no terminator is sent, a
    # strict OpenAI-protocol client waiting for [DONE] relies on connection
    # close to end the stream. Whether every such client handles that cleanly is
    # NOT exercised here and is not claimed.


@pytest.mark.asyncio
async def test_client_disconnect_mid_stream_settles_exactly_once(async_client, sidecar_capability_enabled, go_upstream):
    """Cancellation must not skip settlement, and must not double-settle.

    This is the promise that protects quota accounting: a user who abandons a
    long generation still consumed upstream work, so the reservation has to be
    resolved. The dispatcher's ``finally`` block is the only thing standing
    between that and a leaked reservation.

    **Why the disconnect is driven at the stream and not at the request task.**
    An earlier version of this test cancelled the ``client.post(...)`` future.
    That proved nothing: ``httpx`` with ``ASGITransport`` buffers the whole
    response before returning, so cancelling the post aborts the app *before the
    upstream is ever contacted*. Instrumented, the fake upstream reported
    ``streams_started = 0`` and zero frames - there was no stream to interrupt,
    and the resulting "no log row" was a harness artifact, not product behavior.
    Asserting on it would have been a false finding.

    Using ``client.stream(...)`` and closing the response mid-body makes the
    disconnect real: the upstream serves frames, codex-lb relays them, and the
    consumer goes away while bytes are still in flight.
    """
    await _configure(async_client, go_upstream)
    go_upstream.completion_text = " ".join(f"token{index}" for index in range(60))
    go_upstream.stream_frame_delay_seconds = 0.02
    client_key = await _create_key("stream-disconnect-key")

    received = 0
    async with async_client.stream(
        "POST",
        "/v1/chat/completions",
        json=_stream_body(),
        headers={"Authorization": f"Bearer {client_key}"},
    ) as response:
        assert response.status_code == 200
        async for _line in response.aiter_lines():
            received += 1
            if received >= 3:
                break  # abandon the stream mid-body

    assert received >= 3, "the stream never started, so nothing was interrupted"

    # Give the dispatcher's finally block room to run.
    for _ in range(50):
        if await _sidecar_logs():
            break
        await asyncio.sleep(0.1)

    logs = await _sidecar_logs()
    assert len(logs) == 1, (
        f"expected exactly one log row after an abandoned stream, got {len(logs)}; "
        "a leaked or duplicated settlement is a quota-accounting bug"
    )
    # The upstream really was engaged, so this exercised the teardown path.
    assert go_upstream.streams_started == 1


@pytest.mark.asyncio
async def test_a_reservation_is_not_left_outstanding_after_a_cancelled_stream(
    async_client, sidecar_capability_enabled, go_upstream
):
    """The accounting half of the previous test, asserted on reservation rows.

    A reservation stuck in ``pending`` silently consumes an API key's budget for
    work nobody is waiting on any more.
    """
    from app.db.models import ApiKeyUsageReservation

    await _configure(async_client, go_upstream)
    go_upstream.completion_text = " ".join(f"token{index}" for index in range(60))
    go_upstream.stream_frame_delay_seconds = 0.02
    client_key = await _create_key("stream-reservation-key")

    received = 0
    async with async_client.stream(
        "POST",
        "/v1/chat/completions",
        json=_stream_body(),
        headers={"Authorization": f"Bearer {client_key}"},
    ) as response:
        assert response.status_code == 200
        async for _line in response.aiter_lines():
            received += 1
            if received >= 3:
                break
    assert received >= 3

    for _ in range(50):
        if await _sidecar_logs():
            break
        await asyncio.sleep(0.1)

    async with SessionLocal() as session:
        statuses = list((await session.execute(select(ApiKeyUsageReservation.status))).scalars().all())

    assert "pending" not in statuses, (
        f"a reservation was left pending after a cancelled stream: {statuses}; "
        "it would keep consuming the key's budget for abandoned work"
    )


@pytest.mark.asyncio
async def test_stream_usage_is_requested_upstream_so_settlement_has_numbers(
    async_client, sidecar_capability_enabled, go_upstream
):
    """Settlement can only be accurate if usage was asked for on the wire.

    ``contract.md`` section 5 promises ``ensure_stream_usage_requested`` sets
    ``stream_options.include_usage`` before the request. Asserted at the socket:
    even when the caller omits it, the outbound body carries it.
    """
    await _configure(async_client, go_upstream)
    client_key = await _create_key("stream-usage-optin-key")

    response = await async_client.post(
        "/v1/chat/completions",
        json=_stream_body(include_usage=False),  # caller did NOT opt in
        headers={"Authorization": f"Bearer {client_key}"},
    )
    assert response.status_code == 200

    sent = go_upstream.last_request.body
    assert sent.get("stream") is True
    assert sent.get("stream_options", {}).get("include_usage") is True, (
        "codex-lb did not request usage on a streamed upstream call, so token "
        "accounting for this request could only be guessed"
    )

    logs = await _sidecar_logs()
    assert len(logs) == 1
    assert logs[0].input_tokens == 11
    assert logs[0].output_tokens == 7
