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
a raw socket, and closes the connection *while the upstream producer is still
being held*. The upstream is held open by an unresolved future rather than by a
timing gamble, so "the client went away before EOF" is a fact the test
establishes rather than hopes for.

Reservation settlement is asserted against a **non-empty** reservation - a key
with a real limit - because `limits=[]` can leave no reservation row at all and
make "nothing is pending" vacuously true.

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
        thread.join(timeout=10)


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


@pytest.mark.asyncio
async def test_a_disconnected_stream_settles_its_reservation_exactly_once(
    live_server, opencode_go_enabled, held_upstream
):
    """Accounting after a real disconnect, against a non-empty reservation.

    **Was `xfail(strict=True)`; the marker is removed because the defect is
    fixed.** As reported, the composed tree produced `go_logs=0, all_logs=0,
    reservations=['reserved']` after the upstream confirmed the disconnect and
    300 polls over 30s - quota consumed with nothing recording why.

    Root cause: the stream iterator settled inside a `finally`, and a client
    disconnect closes the generator, so every `await` in that block is
    immediately re-cancelled and the settlement silently never ran. Terminal
    settlement is now detached onto its own task, off the dying call stack.

    The completed-stream control on the same transport always passed, which is
    what localized this to the abort path rather than the database or timing.
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
    writer.transport.abort()
    writer.close()

    await asyncio.wait_for(held_upstream.stream_disconnected.wait(), timeout=20)

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
    # Assert the ACTUAL terminal state, not the absence of a status that does
    # not exist. The schema only ever writes 'reserved', 'finalized' or
    # 'released', so the previous `"pending" not in statuses` was vacuously true
    # even while every reservation sat stranded at 'reserved' - which is exactly
    # the defect this test exists to catch.
    assert all(status in {"finalized", "released"} for status in statuses), (
        f"a reservation was stranded after a disconnect: {statuses}"
    )


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


@pytest.mark.asyncio
async def test_a_disconnected_responses_stream_also_settles_exactly_once(
    live_server, opencode_go_enabled, held_upstream
):
    """The same disconnect accounting on the Responses inbound protocol.

    The two protocols run separate stream iterators with separate ``finally``
    blocks, so fixing one says nothing about the other. Reported coverage was
    Chat-only; this pins Responses against the identical real-socket abort.
    """
    await _configure(live_server)
    client_key = await _create_key_with_a_real_limit("socket-settlement-responses")

    host, port = live_server.removeprefix("http://").split(":")
    body = json.dumps({"model": GO_MODEL, "input": "hi", "stream": True}).encode()
    request = (
        b"POST /v1/responses HTTP/1.1\r\n"
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
    writer.transport.abort()
    writer.close()

    await asyncio.wait_for(held_upstream.stream_disconnected.wait(), timeout=20)

    for _ in range(100):
        if await _go_logs():
            break
        await asyncio.sleep(0.1)

    logs = await _go_logs()
    assert len(logs) == 1, f"expected exactly one log row after a real disconnect, got {len(logs)}"

    reservations = await _reservations()
    assert reservations, "no reservation row exists, so the settlement assertion would be vacuous"
    statuses = [row.status for row in reservations]
    assert all(status in {"finalized", "released"} for status in statuses), (
        f"a reservation was stranded after a Responses disconnect: {statuses}"
    )
