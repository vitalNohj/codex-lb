from __future__ import annotations

import asyncio
import codecs
import json
import re
from collections.abc import AsyncIterator, Callable, Mapping
from typing import Final, Literal

from app.core.errors import ResponseFailedEvent
from app.core.shutdown import wait_for_shutdown_stream_handoff
from app.core.types import JsonObject, JsonValue
from app.core.utils.json_guards import is_json_dict
from app.core.utils.stream_close import aclose_stream

type JsonPayload = Mapping[str, JsonValue] | ResponseFailedEvent

# The data an OpenAI-style stream sends last, in place of a JSON chunk.
SSE_DONE: Final = "[DONE]"

type SseJsonEvent = JsonObject | Literal["[DONE]"]

# The SSE spec delimits lines only by CR, LF, or CRLF. str.splitlines() also
# breaks on other Unicode boundaries (VT, FF, FS/GS/RS, NEL, U+2028, U+2029),
# and U+2028/U+2029 are valid *unescaped* inside JSON strings, so splitting on
# them would corrupt a data: payload that legitimately contains one.
_SSE_LINE_BOUNDARY = re.compile(r"\r\n|\r|\n")

SSE_KEEPALIVE_FRAME = ": keepalive\n\n"
CODEX_KEEPALIVE_FRAME = 'event: codex.keepalive\ndata: {"type":"codex.keepalive"}\n\n'

# Chat clients retry "503" and "service unavailable". A restart sends this
# while the socket can still write, instead of closing the stream with no error.
SHUTDOWN_SERVICE_UNAVAILABLE_FRAME = (
    'data: {"error":{"message":"503 service unavailable",'
    '"type":"server_error","code":"service_unavailable"}}\n\n'
)

# The exact single-event shape ``format_sse_event`` emits (and the upstream
# Codex backend sends): a leading ``event: <type>`` line, one JSON-object
# ``data:`` line, LF-only framing, and a blank-line terminator. Blocks that
# match can expose their event type without a JSON parse and are safe to
# relay downstream byte-for-byte.
_CANONICAL_SSE_BLOCK = re.compile(r"\Aevent: ([^\r\n]+)\ndata: \{[^\r\n]*\n\n\Z")


def sse_event_type_from_block(event_block: str) -> str | None:
    """Cheaply extract the event type from a canonically framed SSE block.

    Returns the ``event:`` line's value only when the block matches the exact
    shape ``format_sse_event`` produces (see ``_CANONICAL_SSE_BLOCK``).
    Anything else — data-only blocks, multi-line data, CR/CRLF framing,
    comment or ``id:`` lines, non-object data payloads, or an ``event:`` field
    that appears after ``data:`` (legal SSE, but not canonical here) — returns
    ``None`` so callers fall back to a full parse.
    """
    match = _CANONICAL_SSE_BLOCK.match(event_block)
    if match is None:
        return None
    return match.group(1)


async def inject_sse_keepalives(
    source: AsyncIterator[str],
    interval_seconds: float,
    *,
    keepalive_frame: str = SSE_KEEPALIVE_FRAME,
    on_keepalive: Callable[[], None] | None = None,
    shutdown_handoff_frame: str | None = None,
) -> AsyncIterator[str]:
    """Wrap an SSE event iterator and emit comment heartbeats on idle gaps.

    Comment frames (lines starting with ``:``) are mandated by the SSE spec to
    be ignored by parsers, so they are safe to inject between event blocks.
    They keep the TCP path warm so half-open sockets surface as write errors
    instead of hanging forever, and let aggressive intermediaries see traffic.

    A non-positive ``interval_seconds`` disables injection entirely.

    ``shutdown_handoff_frame``, when set, is yielded once and the source is
    closed when process shutdown's drain is about to expire. That write
    happens while this task can still send. Callers that omit it keep the
    previous close-on-cancel behavior.

    Closing this generator closes ``source`` too, so the cleanup in the
    source's ``finally`` runs now rather than at garbage collection.
    """
    if interval_seconds <= 0 and shutdown_handoff_frame is None:
        try:
            async for chunk in source:
                yield chunk
        finally:
            await aclose_stream(source)
        return

    async def _next_chunk(it: AsyncIterator[str]) -> str:
        return await it.__anext__()

    iterator = source.__aiter__()
    pending: asyncio.Task[str] | None = None
    handoff: asyncio.Task[None] | None = None
    if shutdown_handoff_frame is not None:
        handoff = asyncio.create_task(wait_for_shutdown_stream_handoff())
    try:
        while True:
            if pending is None:
                pending = asyncio.create_task(_next_chunk(iterator))
            if handoff is None:
                try:
                    chunk = await asyncio.wait_for(
                        asyncio.shield(pending),
                        timeout=interval_seconds,
                    )
                except asyncio.TimeoutError:
                    if on_keepalive is not None:
                        on_keepalive()
                    yield keepalive_frame
                    continue
                except StopAsyncIteration:
                    pending = None
                    break
                pending = None
                yield chunk
                continue

            waiters: set[asyncio.Future[object]] = {pending, handoff}
            timeout = None if interval_seconds <= 0 else interval_seconds
            done, _ = await asyncio.wait(
                waiters,
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if handoff in done:
                yield shutdown_handoff_frame
                return
            if pending in done:
                try:
                    chunk = pending.result()
                except StopAsyncIteration:
                    pending = None
                    break
                pending = None
                yield chunk
                continue
            if on_keepalive is not None:
                on_keepalive()
            yield keepalive_frame
    finally:
        try:
            if handoff is not None and not handoff.done():
                handoff.cancel()
                try:
                    await handoff
                except BaseException:
                    pass
            if pending is not None and not pending.done():
                pending.cancel()
                try:
                    await pending
                except BaseException:
                    pass
        finally:
            await aclose_stream(source)


class SseDataDecoder:
    """Split an SSE byte stream, fed in arbitrary chunks, into each event's ``data``.

    Follows the event-stream parsing rules of the HTML standard, because real
    upstreams differ exactly where those rules are precise:

    * Chunks end at arbitrary byte offsets, so one incremental UTF-8 decoder
      spans the stream and a character split across chunks decodes whole.
      Invalid bytes become U+FFFD rather than vanishing; a leading BOM is
      dropped.
    * Lines end at CRLF, LF, or CR and nowhere else, including at a CRLF split
      across chunks. (``str.splitlines`` also splits at U+2028, U+2029, and
      U+0085, which JSON strings may hold unescaped.)
    * An event ends at a blank line and its ``data`` lines join with LF.
      Comments and other fields are skipped, and an event without ``data``
      yields nothing.

    One deliberate leniency: ``flush`` also yields a last event the stream did
    not close with a blank line, since some upstreams end right after
    ``data: [DONE]``.
    """

    def __init__(self) -> None:
        # ``utf-8-sig`` drops a leading BOM, even one split across chunks.
        self._text = codecs.getincrementaldecoder("utf-8-sig")(errors="replace")
        self._partial_line: list[str] = []
        # The text so far ended in CR, so a leading LF completes that CRLF.
        self._after_cr = False
        self._data_lines: list[str] = []

    def feed(self, chunk: bytes) -> list[str]:
        return self._take_text(self._text.decode(chunk))

    def flush(self) -> list[str]:
        """End the stream: yield what is left, including an unclosed last event."""

        payloads = self._take_text(self._text.decode(b"", final=True))
        partial_line = "".join(self._partial_line)
        self._partial_line = []
        self._after_cr = False
        if partial_line:
            self._take_field(partial_line)
        payload = self._dispatch()
        if payload is not None:
            payloads.append(payload)
        return payloads

    def _take_text(self, text: str) -> list[str]:
        if self._after_cr and text:
            self._after_cr = False
            if text[0] == "\n":
                text = text[1:]
        if not text:
            return []
        pieces = _SSE_LINE_BOUNDARY.split(text)
        self._partial_line.append(pieces[0])
        if len(pieces) == 1:
            return []
        self._after_cr = text[-1] == "\r"
        lines = ["".join(self._partial_line), *pieces[1:-1]]
        self._partial_line = [pieces[-1]]
        payloads: list[str] = []
        for line in lines:
            if line:
                self._take_field(line)
            elif (payload := self._dispatch()) is not None:
                payloads.append(payload)
        return payloads

    def _take_field(self, line: str) -> None:
        if line.startswith(":"):
            return
        field, _, value = line.partition(":")
        if field == "data":
            self._data_lines.append(value[1:] if value.startswith(" ") else value)

    def _dispatch(self) -> str | None:
        if not self._data_lines:
            return None
        payload = "\n".join(self._data_lines)
        self._data_lines = []
        return payload


class SseJsonDataDecoder:
    """``SseDataDecoder`` for OpenAI-style streams.

    Each event is its data parsed as a JSON object, or ``SSE_DONE``; data that
    is neither is skipped.
    """

    def __init__(self) -> None:
        self._data = SseDataDecoder()

    def feed(self, chunk: bytes) -> list[SseJsonEvent]:
        return _json_events(self._data.feed(chunk))

    def flush(self) -> list[SseJsonEvent]:
        return _json_events(self._data.flush())


def _json_events(payloads: list[str]) -> list[SseJsonEvent]:
    events: list[SseJsonEvent] = []
    for payload in payloads:
        if payload.strip() == SSE_DONE:
            events.append(SSE_DONE)
            continue
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if is_json_dict(parsed):
            events.append(parsed)
    return events


def format_sse_event(payload: JsonPayload) -> str:
    data = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    event_type = payload.get("type")
    if isinstance(event_type, str) and event_type:
        return f"event: {event_type}\ndata: {data}\n\n"
    return f"data: {data}\n\n"


def format_sse_data(payload: Mapping[str, JsonValue]) -> str:
    data = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    return f"data: {data}\n\n"


def parse_sse_data_json(event_block: str) -> dict[str, JsonValue] | None:
    data = extract_sse_data(event_block)
    if data is None:
        return None
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        return None
    if is_json_dict(payload):
        return payload
    return None


def extract_sse_data(event_block: str) -> str | None:
    data_lines = _extract_sse_data_lines(event_block)
    if data_lines is None:
        return None
    data = "\n".join(data_lines)
    if not data.strip():
        return None
    if data.strip() == "[DONE]":
        return None
    return data


def _extract_sse_data_lines(event_block: str) -> list[str] | None:
    data_lines: list[str] = []
    for raw_line in _SSE_LINE_BOUNDARY.split(event_block):
        if not raw_line:
            continue
        if raw_line.startswith(":"):
            continue

        field, value = _parse_sse_field(raw_line)
        if field == "data":
            data_lines.append(value)

    if not data_lines:
        return None
    return data_lines


def _parse_sse_field(line: str) -> tuple[str, str]:
    if ":" not in line:
        return line, ""
    field, value = line.split(":", 1)
    if value.startswith(" "):
        value = value[1:]
    return field, value
