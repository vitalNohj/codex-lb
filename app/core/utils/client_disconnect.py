"""Stop waiting on an upstream when the client that asked for it has left.

Once the request body is read, nothing in a request handler watches the client
connection. A handler that waits on an upstream before it returns a response
keeps waiting after the client disconnects, holding the upstream connection
and the caller's reserved quota until the upstream answers or times out, all
for a response nobody will read.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from starlette.types import Receive

from app.core.utils.cancellation import await_deferring_cancellation

__all__ = ["ClientDisconnected", "await_unless_client_disconnects"]

_T = TypeVar("_T")


class ClientDisconnected(Exception):
    """The client disconnected before the awaited work finished. The work was cancelled."""


async def _wait_for_disconnect(receive: Receive) -> None:
    # The body was read already, so the server has nothing left to deliver but
    # the disconnect. A stray body message is skipped rather than trusted.
    while (await receive())["type"] != "http.disconnect":
        pass


async def await_unless_client_disconnects(
    receive: Receive,
    awaitable: Awaitable[_T],
    *,
    discard: Callable[[_T], Awaitable[object]],
) -> _T:
    """Await ``awaitable``, cancelling it if the client disconnects first.

    Returns the result, or raises :class:`ClientDisconnected` once the work is
    cancelled and fully unwound. ``discard`` releases a result the work
    produced anyway, in the moment between the disconnect and the
    cancellation. It should close an opened upstream, not settle anything.
    Settlement is left to the caller.

    Call this only after the request body has been read: the disconnect is
    watched through ``receive``, and so is the body.

    If the calling task is cancelled, the work is cancelled and unwound before
    the cancellation propagates, so it cannot outlive the request.
    """

    work = asyncio.ensure_future(awaitable)
    watcher = asyncio.ensure_future(_wait_for_disconnect(receive))
    try:
        await asyncio.wait((work, watcher), return_when=asyncio.FIRST_COMPLETED)
    except asyncio.CancelledError:
        await _cancel_and_unwind(work, discard)
        raise
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)
    if work.done():
        return work.result()
    _, cancellation_deferred = await await_deferring_cancellation(_cancel_and_unwind(work, discard))
    if cancellation_deferred:
        raise asyncio.CancelledError
    raise ClientDisconnected


async def _cancel_and_unwind(work: asyncio.Future[_T], discard: Callable[[_T], Awaitable[object]]) -> None:
    """Cancel ``work`` and wait for it to unwind, discarding a result that won the race."""

    async def _unwind() -> None:
        work.cancel()
        await asyncio.gather(work, return_exceptions=True)
        if not work.cancelled() and work.exception() is None:
            await discard(work.result())

    await await_deferring_cancellation(_unwind())
