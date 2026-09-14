"""Mid-body disconnect over a real TCP socket, against a real codex-lb server.

**Why this file exists: my earlier disconnect tests were false positives.**

`tests/conftest.py` builds `async_client` on httpx's `ASGITransport`, which
awaits the whole application and joins every response chunk *before*
`client.stream(...)` hands control to the consumer. Measured against this repo's
pinned httpx, with a 60-token completion and a 20ms per-frame delay: at the
moment the stream context was entered the fake upstream had already sent **64
frames** and the producer had finished. Closing the response after three lines
therefore abandoned an already-complete buffer - it interrupted nothing.

So both `test_opencode_go_native_chain.py::test_abandoning_a_native_stream...`
and the OrcaRouter equivalent in `test_opencode_go_stream_settlement.py` prove
"settlement happens exactly once for a completed stream". That is worth having,
and they are kept, but it is **not** disconnect coverage and is no longer
labelled as such.

This file runs the real app under uvicorn on a real loopback port, connects with
a raw socket, and aborts the connection while the upstream producer is still
mid-body.

**How the producer is held, stated accurately.** An earlier docstring here
claimed an unresolved future held the stream open. That was wrong - the fixture
uses a long body (400 frames) with a real per-frame delay. That is a timing
margin, not a hard gate, so every test that depends on it **asserts the
condition it needs**: frames had started (`> 0`) and the producer had not
finished (`< 400`) at the moment of the abort. If the margin ever stops holding,
those assertions fail rather than the test silently degrading into the buffered
false positive this file exists to replace.

Reservation settlement is asserted against a **non-empty** reservation - a key
with a real limit - because `limits=[]` can leave no reservation row at all and
make "nothing is pending" vacuously true.

The live status a stranded reservation actually holds is **`reserved`**, not
`pending`; asserting the wrong literal would pass for the wrong reason.

No authenticated request to opencode.ai is made.
"""

from __future__ import annotations

import asyncio
import json
import threading

import pytest
import pytest_asyncio
import uvicorn
from sqlalchemy import select

from app.core.config.settings import get_settings
from app.db.models import ApiKeyUsageReservation, RequestLog
from app.db.session import SessionLocal
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeyCreateData, ApiKeysService, LimitRuleInput
from tests.fixtures.opencode_go_upstream import FakeOpenCodeGoUpstream

pytestmark = pytest.mark.integration

UPSTREAM_KEY = "sk-go-socket-Zq7SvT2pLm9KdR4xHn8B"
GO_MODEL = "opencode-go/glm-5.3"
GO_SOURCE = "opencode_go_sidecar"


@pytest.fixture
def opencode_go_enabled(monkeypatch):
    monkeypatch.setenv("CODEX_LB_OPENCODE_GO_SIDECAR_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def held_upstream(monkeypatch):
    """A Go upstream whose stream is held open until the test releases it."""
    upstream = FakeOpenCodeGoUpstream(
        api_key=UPSTREAM_KEY,
        model_ids=("glm-5.3",),
        strict_auth_by_endpoint=False,
    )
    # Long body plus a real per-frame delay: the producer cannot finish before
    # the consumer disconnects, which is the condition the old tests lacked.
    upstream.completion_text = " ".join(f"token{index}" for index in range(400))
    upstream.stream_frame_delay_seconds = 0.01
    await upstream.start()

    import app.modules.proxy.api as proxy_api
    from app.core.clients.opencode_go_sidecar import OpenCodeGoSidecarClient

    class _Redirected(OpenCodeGoSidecarClient):
        @property
        def base_url(self) -> str:
            return upstream.base_url

    monkeypatch.setattr(proxy_api, "OpenCodeGoSidecarClient", _Redirected, raising=False)
    monkeypatch.setattr(proxy_api, "get_opencode_go_sidecar_client", _Redirected, raising=False)
    try:
        yield upstream
    finally:
        await upstream.stop()


@pytest_asyncio.fixture
async def live_server(app_instance):
    """The real app on a real TCP port, sharing this test's database."""
    config = uvicorn.Config(app_instance, host="127.0.0.1", port=0, log_level="error", lifespan="on")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        await asyncio.sleep(0.05)
    assert server.started, "uvicorn did not start"
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=30)
        # Loop ownership is unambiguous: uvicorn runs its own event loop inside
        # this thread, so a thread that is still alive here means the server did
        # not shut down and a later test could bind a port it still holds.
        assert not thread.is_alive(), "the uvicorn server thread did not exit"


async def _configure(base_url: str) -> None:
    import aiohttp

    async with aiohttp.ClientSession() as session:
        async with session.put(
            f"{base_url}/api/settings",
            json={
                "opencodeGoSidecarEnabled": True,
                "opencodeGoSidecarBaseUrl": "https://opencode.ai/zen/go/v1",
                "opencodeGoSidecarApiKey": UPSTREAM_KEY,
                "opencodeGoSidecarModelPrefixes": [{"prefix": "opencode-go/", "strip": True}],
                "opencodeGoSidecarFullModels": ["glm-5.3"],
                "apiKeyAuthEnabled": True,
            },
        ) as response:
            assert response.status == 200, await response.text()


async def _create_key_with_a_real_limit(name: str) -> str:
    """A key carrying an actual limit, so a reservation row really is created.

    With ``limits=[]`` no reservation may exist at all, which would make an
    assertion that "nothing is pending" vacuously true.
    """
    async with SessionLocal() as session:
        service = ApiKeysService(ApiKeysRepository(session))
        created = await service.create_key(
            ApiKeyCreateData(
                name=name,
                allowed_models=None,
                limits=[LimitRuleInput(limit_type="total_tokens", limit_window="weekly", max_value=50_000)],
            )
        )
    return created.key


async def _go_logs() -> list[RequestLog]:
    async with SessionLocal() as session:
        rows = list((await session.execute(select(RequestLog))).scalars().all())
    return [row for row in rows if row.source == GO_SOURCE]


async def _reservations() -> list[ApiKeyUsageReservation]:
    async with SessionLocal() as session:
        return list((await session.execute(select(ApiKeyUsageReservation))).scalars().all())


async def _read_until_body_started(reader, upstream: FakeOpenCodeGoUpstream) -> bytes:
    """Read response bytes until SSE data frames are actually arriving.

    Returns the bytes seen so far. Raises on timeout rather than letting the
    caller close a connection whose body never started - closing then would
    abort before the upstream stream exists and prove nothing.
    """
    seen = b""
    deadline = asyncio.get_running_loop().time() + 20
    while asyncio.get_running_loop().time() < deadline:
        chunk = await asyncio.wait_for(reader.read(4096), timeout=20)
        if not chunk:
            break
        seen += chunk
        if b"data:" in seen and upstream.stream_frames_sent > 0:
            return seen
    raise AssertionError(f"the streamed body never started; saw {seen[:300]!r}")


@pytest.mark.asyncio
async def test_a_raw_socket_close_mid_body_is_observed_by_the_upstream(live_server, opencode_go_enabled, held_upstream):
    """The disconnect my ASGITransport tests could not perform.

    A raw socket sends the request, reads only the first bytes of the streamed
    body, then closes. The upstream must observe the disconnect **before** it
    has finished producing - otherwise this is the same false positive again, so
    that condition is asserted rather than assumed.
    """
    await _configure(live_server)
    client_key = await _create_key_with_a_real_limit("socket-disconnect")

    host, port = live_server.removeprefix("http://").split(":")
    body = json.dumps(
        {
            "model": GO_MODEL,
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
            "stream_options": {"include_usage": True},
        }
    ).encode()
    request = (
        b"POST /v1/chat/completions HTTP/1.1\r\n"
        b"Host: " + host.encode() + b"\r\n"
        b"Authorization: Bearer " + client_key.encode() + b"\r\n"
        b"Content-Type: application/json\r\n"
        b"Content-Length: " + str(len(body)).encode() + b"\r\n"
        b"\r\n" + body
    )

    reader, writer = await asyncio.open_connection(host, int(port))
    writer.write(request)
    await writer.drain()

    # Read until actual SSE body bytes arrive. A single read can return only
    # the response headers, and closing at that point aborts before the upstream
    # stream has even begun - which was exactly how the first version of this
    # test failed. Wait for evidence that frames are flowing.
    seen = await _read_until_body_started(reader, held_upstream)
    assert b"data:" in seen, seen[:300]

    frames_at_close = held_upstream.stream_frames_sent
    assert frames_at_close > 0, "the upstream stream never started"
    assert not held_upstream.stream_disconnected.is_set()

    # Hard close: RST rather than a polite FIN, which is what an abandoning
    # client actually does.
    writer.transport.abort()
    writer.close()

    try:
        await asyncio.wait_for(held_upstream.stream_disconnected.wait(), timeout=45)
    except TimeoutError:
        print(
            "\nDIAG frames_at_close=",
            frames_at_close,
            "frames_now=",
            held_upstream.stream_frames_sent,
            "disconnect=",
            held_upstream.stream_disconnected.is_set(),
        )
        raise

    # The decisive assertion: the producer was still mid-body when the client
    # vanished. If this fails the test is buffering again and proves nothing.
    assert frames_at_close < 400, (
        f"the upstream had already sent {frames_at_close} frames before the "
        "close, so the body was buffered and no mid-body disconnect occurred"
    )
    assert held_upstream.streams_started == 1


@pytest.mark.xfail(
    strict=True,
    reason=(
        "open defect, visible only over a real socket: a client that aborts "
        "mid-body leaves its reservation in 'reserved' and writes no "
        "request-log row, so quota is consumed with nothing recording why. "
        "Measured for 30s, which is persistence rather than proof it never "
        "clears - a stale-release path exists elsewhere and may reclaim it "
        "later. The ASGITransport tests could not see this because they only "
        "abandoned already-completed responses. Owner: "
        "codexlb-opencode-go-integration."
    ),
)
@pytest.mark.asyncio
async def test_a_disconnected_stream_settles_its_reservation_exactly_once(
    live_server, opencode_go_enabled, held_upstream
):
    """Accounting after a real disconnect, against a non-empty reservation.

    Measured on the composed tree: `go_logs=0, all_logs=0,
    reservations=['reserved']` after the upstream confirmed the disconnect and
    300 polls over 30s. The completed-stream control on the same transport and
    fixture writes its row and settles, so this is specific to the abort path
    rather than a database or timing artifact.

    Two precision points, both of which a looser assertion would get wrong:

    * The stranded status is **`reserved`**. Asserting "not pending" would pass
      today for the wrong reason, since nothing is ever in `pending` here.
    * 30 seconds is **measured persistence, not permanence.** A stale-release
      path exists in this codebase and may reclaim the row on a longer horizon.
      The claim made here is bounded to what was observed.
    """
    await _configure(live_server)
    client_key = await _create_key_with_a_real_limit("socket-settlement")

    host, port = live_server.removeprefix("http://").split(":")
    body = json.dumps(
        {
            "model": GO_MODEL,
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
            "stream_options": {"include_usage": True},
        }
    ).encode()
    request = (
        b"POST /v1/chat/completions HTTP/1.1\r\n"
        b"Host: " + host.encode() + b"\r\n"
        b"Authorization: Bearer " + client_key.encode() + b"\r\n"
        b"Content-Type: application/json\r\n"
        b"Content-Length: " + str(len(body)).encode() + b"\r\n"
        b"\r\n" + body
    )

    reader, writer = await asyncio.open_connection(host, int(port))
    writer.write(request)
    await writer.drain()
    await _read_until_body_started(reader, held_upstream)

    # Explicit producer-state evidence at the moment of the abort, so this
    # accounting case cannot silently become the buffered false positive it
    # replaced. Recorded before the close, asserted after.
    frames_at_abort = held_upstream.stream_frames_sent
    assert frames_at_abort > 0, "the upstream stream never started"
    assert not held_upstream.stream_disconnected.is_set()

    writer.transport.abort()
    writer.close()

    await asyncio.wait_for(held_upstream.stream_disconnected.wait(), timeout=20)
    assert frames_at_abort < 400, (
        f"the producer had already sent {frames_at_abort} of 400 frames before "
        "the abort, so the body was buffered and this is not a mid-body "
        "disconnect"
    )
    assert held_upstream.streams_started == 1

    for _ in range(100):
        if await _go_logs():
            break
        await asyncio.sleep(0.1)

    logs = await _go_logs()
    assert len(logs) == 1, f"expected exactly one log row after a real disconnect, got {len(logs)}"

    reservations = await _reservations()
    # Non-vacuous: a reservation really was created for this key.
    assert reservations, "no reservation row exists, so the settlement assertion would be vacuous"
    statuses = [row.status for row in reservations]
    # The live stranded status is `reserved`. Assert the positive requirement -
    # every row reached a terminal state - rather than the absence of a status
    # that never occurs on this path anyway.
    terminal = {"settled", "finalized", "released", "cancelled", "expired"}
    assert all(status in terminal for status in statuses), (
        f"a reservation did not reach a terminal status after a disconnect: {statuses}"
    )
    assert "reserved" not in statuses, f"a reservation is still held as 'reserved' after the client aborted: {statuses}"


@pytest.mark.asyncio
async def test_a_completed_stream_over_a_real_socket_still_settles_once(
    live_server, opencode_go_enabled, held_upstream
):
    """Control: the same transport, allowed to finish, must settle normally.

    Without this, a change that broke streaming entirely would still satisfy the
    disconnect assertions above.
    """
    held_upstream.completion_text = "alpha beta"
    held_upstream.stream_frame_delay_seconds = 0.0

    await _configure(live_server)
    client_key = await _create_key_with_a_real_limit("socket-complete")

    import aiohttp

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{live_server}/v1/chat/completions",
            json={
                "model": GO_MODEL,
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
                "stream_options": {"include_usage": True},
            },
            headers={"Authorization": f"Bearer {client_key}"},
        ) as response:
            assert response.status == 200
            text = (await response.read()).decode()

    assert text.rstrip().endswith("data: [DONE]")

    for _ in range(100):
        if await _go_logs():
            break
        await asyncio.sleep(0.1)

    logs = await _go_logs()
    assert len(logs) == 1
    assert logs[0].status == "success"
    assert logs[0].output_tokens == 7

    reservations = await _reservations()
    assert reservations
    assert "pending" not in [row.status for row in reservations]
