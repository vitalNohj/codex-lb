"""Close a wrapped async stream so its cleanup runs inside the current request.

``async for`` does not close the iterator it consumes. When a wrapper stops
iterating early - the Cursor context-limit rewrite replaces a refused upstream
response with a synthetic success and returns - the wrapped generator is merely
abandoned, and its ``finally`` runs only when the event loop later finalizes it.

That matters because the sidecar stream iterators settle the API-key usage
reservation in exactly such a ``finally``. Deferring it leaves the reservation
``reserved`` and the caller's quota consumed after the response has already
completed, for a request the upstream refused.
"""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator

from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from app.core.utils.cancellation import complete_despite_cancellation

__all__ = ["ClosingStreamingResponse", "aclose_stream"]


async def aclose_stream(stream: AsyncIterator[object]) -> None:
    """Close ``stream`` if it supports it, deferring cancellation until done.

    Iterators without ``aclose`` (plain class-based iterators) are skipped.

    The close is shielded because a client disconnect cancels the response task,
    and settlement running on that cancellation-sensitive stack would otherwise
    be interrupted partway - reintroducing, on the path most likely to hit it,
    the very leak this close exists to prevent. This mirrors the deferred
    cancellation used for owned upstream cleanup elsewhere in the proxy: a
    cancellation that arrives mid-close is absorbed so the close completes, then
    re-raised, so the request still terminates as cancelled. A cancellation of
    the close itself propagates immediately.

    ``aclose()`` is idempotent, so calling it on an exhausted or already-closed
    generator is a no-op and the normal completion path is unaffected.
    """

    aclose = getattr(stream, "aclose", None)
    if aclose is None:
        return
    if inspect.isasyncgen(stream) and inspect.getasyncgenstate(stream) == inspect.AGEN_CLOSED:
        # Nothing to run, so nothing to await. Not awaiting matters: a generator
        # whose own body raised ``GeneratorExit`` leaves its caller unable to
        # await anything more in the same unwind.
        return
    # Deferred, never swallowed. Absorbing the cancellation so the close can
    # finish is the point; returning normally afterwards is not - callers below
    # would treat a cancelled request as a completed one.
    await complete_despite_cancellation(aclose())


class ClosingStreamingResponse(StreamingResponse):
    """A ``StreamingResponse`` that closes its body iterator before returning.

    Starlette never closes the body iterator. When the client leaves, it
    cancels the task sending the body. If that task was waiting on the socket
    rather than inside the iterator, the iterator stays suspended at its
    ``yield``, and its ``finally`` (upstream close, reservation settlement,
    request log) waits for garbage collection. The same happens when the client
    left before the response started: the first send is dropped and the
    iterator never runs past it.

    Closing here runs that cleanup inside the request, while the server still
    counts it as in flight, so graceful shutdown waits for it too. On a stream
    that already finished, the close does nothing.
    """

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            await aclose_stream(self.body_iterator)
