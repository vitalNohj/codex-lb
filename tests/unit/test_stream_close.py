from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from starlette.types import Message, Scope

from app.core.utils.sse import inject_sse_keepalives
from app.core.utils.stream_close import ClosingStreamingResponse, SettlingStream

pytestmark = pytest.mark.unit

_SCOPE: Scope = {"type": "http", "asgi": {"spec_version": "2.3"}}


class _Request:
    """A streamed request whose settling generator records how it ended."""

    def __init__(self) -> None:
        self.settled = False
        self.abandoned = 0
        self.stream = SettlingStream(self._body(), abandon=self._abandon)

    async def _body(self) -> AsyncIterator[str]:
        try:
            yield "one"
            yield "two"
        finally:
            self.settled = True

    async def _abandon(self) -> None:
        self.abandoned += 1


async def _never_disconnects() -> Message:
    await asyncio.Event().wait()
    raise AssertionError("unreachable")


async def _disconnects() -> Message:
    return {"type": "http.disconnect"}


async def _send_ok(message: Message) -> None:
    return None


async def _blocked_start(message: Message) -> None:
    # The response start is still being written when the disconnect is seen.
    await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_a_body_that_finished_settles_once_and_is_not_abandoned() -> None:
    request = _Request()
    response = ClosingStreamingResponse(request.stream, settling=request.stream)

    await response(_SCOPE, _never_disconnects, _send_ok)

    assert request.settled
    assert request.abandoned == 0


@pytest.mark.asyncio
async def test_a_body_left_mid_stream_settles_in_its_own_finally() -> None:
    request = _Request()
    response = ClosingStreamingResponse(request.stream, settling=request.stream)
    first_chunk_sent = asyncio.Event()

    async def send(message: Message) -> None:
        if message.get("body") == b"one":
            first_chunk_sent.set()
            await asyncio.Event().wait()  # the client stops reading

    async def receive() -> Message:
        await first_chunk_sent.wait()
        return {"type": "http.disconnect"}

    await response(_SCOPE, receive, send)

    assert request.settled
    assert request.abandoned == 0


@pytest.mark.asyncio
async def test_a_body_that_never_started_is_abandoned_once() -> None:
    request = _Request()
    response = ClosingStreamingResponse(request.stream, settling=request.stream)

    await response(_SCOPE, _disconnects, _blocked_start)

    # Closing a generator that never started skips its ``finally``.
    assert not request.settled
    assert request.abandoned == 1
    # It is closed, so a later garbage collection cannot start it either.
    with pytest.raises(StopAsyncIteration):
        await anext(request.stream)
    await request.stream.aclose()
    assert request.abandoned == 1


@pytest.mark.asyncio
async def test_a_wrapper_that_closes_before_its_first_pull_still_abandons() -> None:
    """``inject_sse_keepalives`` starts, then is closed while waiting for its first chunk."""

    request = _Request()
    pulled = asyncio.Event()

    async def slow_start() -> AsyncIterator[str]:
        pulled.set()
        await asyncio.Event().wait()  # the first chunk has not arrived
        async for chunk in request.stream:
            yield chunk  # pragma: no cover - never reached

    wrapper = inject_sse_keepalives(slow_start(), 30)
    response = ClosingStreamingResponse(wrapper, settling=request.stream)

    async def receive() -> Message:
        await pulled.wait()
        return {"type": "http.disconnect"}

    await response(_SCOPE, receive, _send_ok)

    assert not request.settled
    assert request.abandoned == 1


@pytest.mark.asyncio
async def test_a_wrapper_that_passes_its_close_on_leaves_nothing_for_the_response() -> None:
    request = _Request()
    wrapper = inject_sse_keepalives(request.stream, 30)
    response = ClosingStreamingResponse(wrapper, settling=request.stream)

    await response(_SCOPE, _disconnects, _blocked_start)

    assert not request.settled
    assert request.abandoned == 1


@pytest.mark.asyncio
async def test_abandon_finishes_under_repeated_cancellation_and_the_request_stays_cancelled() -> None:
    abandon_started = asyncio.Event()
    abandon_finished = asyncio.Event()

    async def body() -> AsyncIterator[str]:
        yield ""  # pragma: no cover - never started

    async def abandon() -> None:
        abandon_started.set()
        await asyncio.sleep(0.05)
        abandon_finished.set()

    stream = SettlingStream(body(), abandon=abandon)
    response = ClosingStreamingResponse(stream, settling=stream)

    task = asyncio.create_task(response(_SCOPE, _never_disconnects, _blocked_start))
    await asyncio.sleep(0.01)
    task.cancel()  # the server cancels the request
    await abandon_started.wait()
    task.cancel()  # and again, while the abandon runs

    with pytest.raises(asyncio.CancelledError):
        await task
    assert abandon_finished.is_set()


def test_a_stream_that_is_not_a_generator_is_refused() -> None:
    class _Iterator:
        def __aiter__(self) -> _Iterator:
            return self

        async def __anext__(self) -> str:
            raise StopAsyncIteration

    async def abandon() -> None:
        return None

    with pytest.raises(TypeError, match="async generator"):
        SettlingStream(_Iterator(), abandon=abandon)
