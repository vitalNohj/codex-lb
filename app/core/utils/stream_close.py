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

import asyncio
from collections.abc import AsyncIterator

import anyio

__all__ = ["aclose_stream"]


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
    task = asyncio.ensure_future(aclose())
    cancellation_deferred = False
    with anyio.CancelScope(shield=True):
        while True:
            try:
                await asyncio.shield(task)
                break
            except asyncio.CancelledError:
                if task.cancelled():
                    raise
                cancellation_deferred = True
    if cancellation_deferred:
        # Deferred, never swallowed. Absorbing the cancellation so the close can
        # finish is the point; returning normally afterwards is not - callers
        # below would treat a cancelled request as a completed one.
        raise asyncio.CancelledError
