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
from collections.abc import AsyncGenerator, AsyncIterable, AsyncIterator, Awaitable, Callable, Mapping
from typing import cast

from starlette.background import BackgroundTask
from starlette.responses import ContentStream, StreamingResponse
from starlette.types import Receive, Scope, Send

from app.core.utils.cancellation import complete_despite_cancellation

__all__ = ["ClosingStreamingResponse", "SettlingStream", "aclose_stream"]


class SettlingStream[T](AsyncIterator[T]):
    """The async generator that settles a streamed request, safe to close unstarted.

    ``stream``'s ``finally`` settles the request: it closes the upstream,
    settles the reservation, and writes the request log. But Python skips the
    ``finally`` of an async generator closed before it started, which is what
    happens when the client leaves before the response body first pulls from
    it. Starting it just to close it would be no better, since it may open an
    upstream request for a client that is already gone.

    So closing this wrapper checks, at that moment, whether ``stream`` ever
    started. If not, ``abandon`` runs in place of that ``finally``: it closes
    anything opened before the response, releases the reservation, and logs
    the request as cancelled. The check is made when the close happens, not
    later. Once closed, a generator that never started looks the same as one
    that finished, and a wrapper such as ``inject_sse_keepalives`` may close
    its source before ever pulling from it.

    This is a class rather than a generator so its ``aclose`` always runs.
    """

    __slots__ = ("_abandon", "_closed", "_stream")

    def __init__(self, stream: AsyncIterator[T], *, abandon: Callable[[], Awaitable[None]]) -> None:
        # Only a generator can be seen not to have started. The settling
        # iterators are annotated as plain iterators, so this is checked here.
        if not inspect.isasyncgen(stream):
            raise TypeError(f"stream must be an async generator, not {type(stream).__name__}")
        self._stream = stream
        self._abandon = abandon
        self._closed = False

    def __aiter__(self) -> SettlingStream[T]:
        return self

    async def __anext__(self) -> T:
        return await self._stream.__anext__()

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        never_started = inspect.getasyncgenstate(cast(AsyncGenerator[T, None], self._stream)) == inspect.AGEN_CREATED
        try:
            # On a generator that never started, this only marks it closed, so
            # a later garbage collection cannot start it either.
            await aclose_stream(self._stream)
        finally:
            if never_started:
                await complete_despite_cancellation(self._abandon())


async def aclose_stream(stream: AsyncIterable[object]) -> None:
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
    """A ``StreamingResponse`` that finishes its body's cleanup before returning.

    Starlette never closes the body iterator. When the client leaves, it
    cancels the task sending the body. If that task was waiting on the socket
    rather than inside the iterator, the iterator stays suspended at its
    ``yield``, and its ``finally`` (upstream close, reservation settlement,
    request log) waits for garbage collection. Closing it here runs that
    cleanup inside the request, while the server still counts it as in flight,
    so graceful shutdown waits for it too. On a stream that already finished,
    the close does nothing.

    A body that never started is different: Python skips the ``finally`` of
    an async generator closed before it starts. ``settling`` is the stream in
    the body that settles the request. It is closed here too, so a body that
    never reached it still settles, through ``SettlingStream``'s abandon.

    ``settling`` is required so every streamed response states which stream
    settles it. Pass ``None`` only for a body that owns nothing.
    """

    def __init__(
        self,
        content: ContentStream,
        status_code: int = 200,
        headers: Mapping[str, str] | None = None,
        media_type: str | None = None,
        background: BackgroundTask | None = None,
        *,
        settling: SettlingStream[object] | None,
    ) -> None:
        super().__init__(content, status_code, headers, media_type, background)
        self._settling = settling

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            await self._finish_body()

    async def _finish_body(self) -> None:
        try:
            await aclose_stream(self.body_iterator)
        finally:
            # Usually a no-op: closing the body closed it. Not when a wrapper in
            # between does not pass its close on.
            if self._settling is not None:
                await self._settling.aclose()
