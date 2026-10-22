from __future__ import annotations

import asyncio
import gc
import json
import logging
from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core import shutdown as shutdown_state
from app.core.openai.parsing import _LIFECYCLE_EVENT_TYPES, classify_event_type, parse_sse_event
from app.core.types import JsonValue
from app.core.utils.sse import (
    CODEX_KEEPALIVE_FRAME,
    SHUTDOWN_SERVICE_UNAVAILABLE_FRAME,
    SSE_DONE,
    SSE_KEEPALIVE_FRAME,
    ParsedSseBlock,
    SseDataDecoder,
    SseEventDecoder,
    SseJsonDataDecoder,
    extract_sse_data,
    format_local_sse_event,
    format_sse_data,
    format_sse_event,
    format_sse_event_from_text,
    inject_sse_keepalives,
    parse_sse_data_json,
    parse_sse_data_json_text,
    sse_block_with_payload,
    sse_event_type_from_block,
)
from tests.unit.hypothesis_strategies import json_objects, json_values

pytestmark = pytest.mark.unit


def test_format_sse_event_serializes_payload():
    payload = {"type": "response.completed", "response": {"id": "resp_1"}}
    result = format_sse_event(payload)
    assert result == 'event: response.completed\ndata: {"type":"response.completed","response":{"id":"resp_1"}}\n\n'


@given(payload=json_objects)
@settings(max_examples=40, deadline=None)
def test_format_sse_event_round_trips_arbitrary_json_objects(payload):
    assert parse_sse_data_json(format_sse_event(payload)) == payload


@given(payload=json_objects)
@settings(max_examples=40, deadline=None)
def test_format_sse_data_round_trips_arbitrary_json_objects(payload):
    assert parse_sse_data_json(format_sse_data(payload)) == payload


@given(
    boundary=st.sampled_from(["\r", "\n", "\r\n"]),
    key=st.text(max_size=40),
    value=st.integers(),
)
@settings(max_examples=30, deadline=None)
def test_sse_line_boundaries_are_equivalent_in_multiline_data(boundary, key, value):
    encoded_key = json.dumps(key, ensure_ascii=True)
    block = f"data: {{{encoded_key}:" + boundary + f"data: {value}}}" + boundary * 2

    assert parse_sse_data_json(block) == {key: value}


@given(text=st.text(max_size=80))
@settings(max_examples=30, deadline=None)
def test_sse_unicode_line_separators_remain_data(text):
    payload = {"value": f"before{text}\u2028middle\u2029after"}
    block = "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"

    assert parse_sse_data_json(block) == payload


@given(
    boundary=st.sampled_from(["\r", "\n", "\r\n"]),
    first=st.text(alphabet=st.characters(blacklist_categories=("C", "Z")), min_size=1, max_size=40),
    second=st.text(alphabet=st.characters(blacklist_categories=("C", "Z")), min_size=1, max_size=40),
)
@settings(max_examples=30, deadline=None)
def test_sse_multiline_data_ignores_comments_and_joins_with_newline(boundary, first, second):
    block = f": comment{boundary}data: {first}{boundary}event: ignored{boundary}data: {second}{boundary}{boundary}"

    assert extract_sse_data(block) == f"{first}\n{second}"


@given(value=st.one_of(st.none(), st.booleans(), st.integers(), st.lists(json_values, max_size=4)))
@settings(max_examples=30, deadline=None)
def test_parse_sse_data_json_rejects_non_object_json(value):
    assert parse_sse_data_json("data: " + json.dumps(value) + "\n\n") is None


async def _agen(items: list[str]) -> AsyncIterator[str]:
    for item in items:
        yield item


async def _slow_agen(items: list[str], delay: float) -> AsyncIterator[str]:
    for item in items:
        await asyncio.sleep(delay)
        yield item


@pytest.mark.asyncio
async def test_inject_sse_keepalives_passes_through_when_disabled():
    out = [chunk async for chunk in inject_sse_keepalives(_agen(["a\n\n", "b\n\n"]), 0)]
    assert out == ["a\n\n", "b\n\n"]


@pytest.mark.asyncio
async def test_inject_sse_keepalives_no_pings_when_source_is_fast():
    out = [chunk async for chunk in inject_sse_keepalives(_agen(["a\n\n", "b\n\n"]), 5.0)]
    assert out == ["a\n\n", "b\n\n"]


@pytest.mark.asyncio
async def test_inject_sse_keepalives_emits_pings_on_idle_gap():
    callbacks: list[str] = []
    out = [
        chunk
        async for chunk in inject_sse_keepalives(
            _slow_agen(["a\n\n"], delay=0.25),
            0.05,
            on_keepalive=lambda: callbacks.append("sent"),
        )
    ]
    assert out[-1] == "a\n\n"
    assert SSE_KEEPALIVE_FRAME in out
    assert out.count(SSE_KEEPALIVE_FRAME) >= 2
    assert len(callbacks) == out.count(SSE_KEEPALIVE_FRAME)


@pytest.mark.asyncio
async def test_inject_sse_keepalives_cancels_idle_source_when_downstream_closes():
    source_cancelled = asyncio.Event()

    async def source() -> AsyncIterator[str]:
        try:
            await asyncio.Event().wait()
        finally:
            source_cancelled.set()
        yield ""  # pragma: no cover - keeps this a pending async generator

    stream = inject_sse_keepalives(source(), 0.01)
    assert await anext(stream) == SSE_KEEPALIVE_FRAME

    await cast(Any, stream).aclose()

    assert source_cancelled.is_set()


@pytest.mark.asyncio
async def test_inject_sse_keepalives_does_not_leave_stream_end_unretrieved(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A source that ends while the consumer is away must not become an ERROR.

    The injector pulls each chunk in its own task. After a keepalive timeout it
    yields the frame and suspends, leaving that task running with no waiter
    attached; if the source ends there, nothing retrieves the resulting
    ``StopAsyncIteration`` and asyncio logs ``Task exception was never
    retrieved`` with a traceback when the task is collected -- on a request
    that had otherwise completed normally. Production saw one per such stream.
    """

    source_exhausted = asyncio.Event()

    async def source() -> AsyncIterator[str]:
        yield "a\n\n"
        await asyncio.sleep(0.05)
        source_exhausted.set()

    caplog.set_level(logging.ERROR, logger="asyncio")
    stream = inject_sse_keepalives(source(), 0.01)
    assert await anext(stream) == "a\n\n"
    # The keepalive fires while the pull task is still running.
    assert await anext(stream) == SSE_KEEPALIVE_FRAME

    # The consumer goes away here -- a client that disconnected, or simply a
    # socket write that has not drained -- so the source ends with the injector
    # suspended and no waiter registered on the pull task.
    await source_exhausted.wait()
    await asyncio.sleep(0)
    await cast(Any, stream).aclose()

    # Collection is when asyncio's destructor would log it.
    for _ in range(3):
        await asyncio.sleep(0)
    gc.collect()

    unretrieved = [record for record in caplog.records if "never retrieved" in record.getMessage()]
    assert not unretrieved, [record.getMessage() for record in unretrieved]


@pytest.mark.asyncio
async def test_inject_sse_keepalives_can_emit_codex_event_frame():
    out = [
        chunk
        async for chunk in inject_sse_keepalives(
            _slow_agen(["a\n\n"], delay=0.25),
            0.05,
            keepalive_frame=CODEX_KEEPALIVE_FRAME,
        )
    ]
    assert out[-1] == "a\n\n"
    assert CODEX_KEEPALIVE_FRAME in out
    assert out.count(CODEX_KEEPALIVE_FRAME) >= 2


@pytest.mark.asyncio
async def test_inject_sse_keepalives_shutdown_handoff_ends_with_retryable_error():
    shutdown_state.reset()
    shutdown_state.commit_shutdown(0.1)
    source_closed = asyncio.Event()

    async def source() -> AsyncIterator[str]:
        try:
            await asyncio.Event().wait()
            yield "never\n\n"
        finally:
            source_closed.set()

    try:
        out = [
            chunk
            async for chunk in inject_sse_keepalives(
                source(),
                30,
                shutdown_handoff_frame=SHUTDOWN_SERVICE_UNAVAILABLE_FRAME,
            )
        ]
    finally:
        shutdown_state.reset()

    assert out == [SHUTDOWN_SERVICE_UNAVAILABLE_FRAME]
    assert "503 service unavailable" in SHUTDOWN_SERVICE_UNAVAILABLE_FRAME
    assert source_closed.is_set()


@pytest.mark.asyncio
async def test_inject_sse_keepalives_skips_shutdown_handoff_before_commit():
    shutdown_state.reset()
    try:
        out = [
            chunk
            async for chunk in inject_sse_keepalives(
                _agen(["a\n\n", "b\n\n"]),
                5.0,
                shutdown_handoff_frame=SHUTDOWN_SERVICE_UNAVAILABLE_FRAME,
            )
        ]
    finally:
        shutdown_state.reset()

    assert out == ["a\n\n", "b\n\n"]


@pytest.mark.asyncio
async def test_inject_sse_keepalives_keepalive_frame_is_sse_comment():
    assert SSE_KEEPALIVE_FRAME.startswith(":")
    assert SSE_KEEPALIVE_FRAME.endswith("\n\n")


def test_extract_sse_data_preserves_unicode_line_separators():
    # U+2028 / U+2029 are valid *unescaped* inside JSON strings. The SSE spec
    # delimits lines only by CR/LF/CRLF, so they must not split a data: payload.
    payload = {"type": "response.output_text.delta", "delta": "line1\u2028line2\u2029end"}
    block = "event: response.output_text.delta\ndata: " + json.dumps(payload, ensure_ascii=False) + "\n\n"

    data = extract_sse_data(block)

    assert data is not None
    assert json.loads(data) == payload


def test_parse_sse_data_json_preserves_unicode_line_separators():
    payload = {"type": "response.completed", "response": {"id": "resp_1", "status": "completed", "note": "a\u2028b"}}
    block = "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"

    assert parse_sse_data_json(block) == payload


def test_parse_sse_event_parses_payload_with_unicode_line_separators():
    # The proxy receive path relies on parse_sse_event for terminal-event
    # detection, dedupe, and usage; an unescaped U+2028 used to drop the event.
    payload = {"type": "response.output_text.delta", "delta": "x\u2028y\u2029z"}
    block = "event: response.output_text.delta\ndata: " + json.dumps(payload, ensure_ascii=False) + "\n\n"

    event = parse_sse_event(block)

    assert event is not None
    assert event.type == "response.output_text.delta"


def test_extract_sse_data_joins_crlf_multiline_data():
    # CR, LF, and CRLF all remain valid line boundaries after the fix.
    block = "data: line1\r\ndata: line2\rdata: line3\n\n"

    assert extract_sse_data(block) == "line1\nline2\nline3"


def test_classify_event_type_prefers_string_type_field():
    assert classify_event_type({"type": "response.output_text.delta", "delta": "x"}) == "response.output_text.delta"


def test_classify_event_type_maps_typeless_error_payload_to_error():
    assert classify_event_type({"error": {"message": "boom"}, "status": 400}) == "error"


def test_classify_event_type_rejects_non_dict_and_typeless_payloads():
    assert classify_event_type(None) is None
    assert classify_event_type([1, 2, 3]) is None
    assert classify_event_type({"type": 42}) is None
    assert classify_event_type({"delta": "x"}) is None


def test_lifecycle_event_types_cover_terminal_and_created_frames():
    assert _LIFECYCLE_EVENT_TYPES == frozenset(
        {
            "response.created",
            "response.queued",
            "response.in_progress",
            "response.completed",
            "response.incomplete",
            "response.failed",
            "error",
        }
    )


def test_sse_event_type_from_block_extracts_type_from_canonical_block():
    block = 'event: response.output_text.delta\ndata: {"type":"response.output_text.delta","delta":"hi"}\n\n'

    assert sse_event_type_from_block(block) == "response.output_text.delta"


def test_sse_event_type_from_block_accepts_raw_utf8_payloads():
    block = 'event: response.output_text.delta\ndata: {"type":"response.output_text.delta","delta":"안녕"}\n\n'

    assert sse_event_type_from_block(block) == "response.output_text.delta"


def test_sse_event_type_from_block_rejects_data_only_blocks():
    assert sse_event_type_from_block('data: {"type":"response.output_text.delta","delta":"hi"}\n\n') is None


def test_sse_event_type_from_block_rejects_trailing_event_field_ordering():
    # `event:` after `data:` is legal SSE but not the canonical framing this
    # proxy relays verbatim; callers must fall back to a full parse.
    block = 'data: {"type":"response.output_text.delta","delta":"hi"}\nevent: response.output_text.delta\n\n'

    assert sse_event_type_from_block(block) is None


def test_sse_event_type_from_block_rejects_non_lf_framing_and_multiline_data():
    crlf = 'event: response.output_text.delta\r\ndata: {"type":"response.output_text.delta"}\r\n\r\n'
    multiline = 'event: response.output_text.delta\ndata: {"type":\ndata: "response.output_text.delta"}\n\n'

    assert sse_event_type_from_block(crlf) is None
    assert sse_event_type_from_block(multiline) is None


def test_sse_event_type_from_block_rejects_non_object_data_payloads():
    assert sse_event_type_from_block("event: done\ndata: [DONE]\n\n") is None
    assert sse_event_type_from_block("event: ping\ndata: \n\n") is None


def _decode_in_chunks(stream: bytes, cuts: list[int]) -> list[str]:
    decoder = SseDataDecoder()
    payloads: list[str] = []
    start = 0
    for cut in sorted(set(cuts)):
        payloads.extend(decoder.feed(stream[start:cut]))
        start = cut
    payloads.extend(decoder.feed(stream[start:]))
    payloads.extend(decoder.flush())
    return payloads


def test_sse_data_decoder_splits_events_at_every_line_ending_style():
    stream = b"data: lf\n\ndata: crlf\r\n\r\ndata: cr\r\rdata: mixed\r\n\n"

    assert _decode_in_chunks(stream, []) == ["lf", "crlf", "cr", "mixed"]


def test_sse_data_decoder_ends_a_line_not_an_event_at_one_crlf():
    stream = b'data: {"a":\r\ndata: 1}\r\n\r\n'

    assert _decode_in_chunks(stream, []) == ['{"a":\n1}']


def test_sse_data_decoder_treats_crlf_split_across_chunks_as_one_line_ending():
    # Read as CR then a separate LF, a CRLF between two data lines would end
    # the event early and split it in two.
    stream = b"data: x\r\ndata: y\r\n\r\ndata: z\r\n\r\n"

    for cut in range(len(stream) + 1):
        assert _decode_in_chunks(stream, [cut]) == ["x\ny", "z"], cut


def test_sse_data_decoder_joins_a_character_split_across_chunks():
    stream = "data: café 日本語 🚀\n\n".encode()

    for cut in range(len(stream) + 1):
        assert _decode_in_chunks(stream, [cut]) == ["café 日本語 🚀"], cut


def test_sse_data_decoder_keeps_unicode_line_separators_inside_data():
    payload = "one\u2028two\u2029three\x85four\x0bfive\x0csix"

    assert _decode_in_chunks(f"data: {payload}\n\n".encode(), []) == [payload]


def test_sse_data_decoder_skips_comments_other_fields_and_data_less_events():
    stream = b": ping\n\nevent: x\nid: 7\nretry: 5\n\ndata\n\ndata:no-space\n\n"

    assert _decode_in_chunks(stream, []) == ["", "no-space"]


def test_sse_data_decoder_replaces_invalid_bytes_and_drops_a_leading_bom():
    stream = b"\xef\xbb\xbfdata: a\xffb\n\n"

    for cut in range(len(stream) + 1):
        assert _decode_in_chunks(stream, [cut]) == ["a\ufffdb"], cut


def test_sse_data_decoder_flush_yields_an_unclosed_last_event_once():
    decoder = SseDataDecoder()

    assert decoder.feed(b"data: [DONE]") == []
    assert decoder.flush() == ["[DONE]"]
    assert decoder.flush() == []


def test_sse_data_decoder_flush_completes_a_character_cut_off_at_the_end():
    decoder = SseDataDecoder()

    assert decoder.feed(b"data: caf\xc3") == []
    assert decoder.flush() == ["caf\ufffd"]


def test_sse_data_decoder_drops_an_event_past_max_event_chars_and_keeps_the_next():
    decoder = SseDataDecoder(max_event_chars=8)

    assert decoder.feed(b"data: 0123") == []
    # The oversize event is dropped whether it grows in one line or several.
    assert decoder.feed(b"456789 more") == []
    assert decoder.feed(b"\ndata: tail\n") == []
    assert decoder.feed(b"\ndata: short\n\n") == ["short"]
    assert decoder.feed(b"data: a\ndata: b\n\n") == ["a\nb"]
    assert decoder.flush() == []


def test_sse_data_decoder_holds_no_more_than_max_event_chars_without_a_boundary():
    decoder = SseDataDecoder(max_event_chars=1000)

    for _ in range(200):
        assert decoder.feed(b"x" * 4096) == []
        assert decoder.held_chars <= 1000
    assert decoder.feed(b"\n\ndata: ok\n\n") == ["ok"]


def test_sse_data_decoder_flush_drops_an_oversize_unclosed_event():
    decoder = SseDataDecoder(max_event_chars=4)

    assert decoder.feed(b"data: too long") == []
    assert decoder.flush() == []


def test_sse_data_decoder_counts_empty_data_lines_toward_max_event_chars():
    decoder = SseDataDecoder(max_event_chars=100)

    for _ in range(10_000):
        assert decoder.feed(b"data:\n") == []
        assert decoder.held_chars <= 100
    assert decoder.feed(b"\ndata: ok\n\n") == ["ok"]


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(b'{"n":' + b"1" * 5000 + b"}", id="integer-past-the-digit-limit"),
        pytest.param(b"[" * 100_000, id="nesting-past-the-recursion-limit"),
    ],
)
def test_sse_json_data_decoder_skips_data_json_loads_cannot_build(data: bytes):
    decoder = SseJsonDataDecoder()

    assert decoder.feed(b"data: " + data + b'\n\ndata: {"ok":1}\n\n') == [{"ok": 1}]


def test_sse_event_decoder_yields_each_raw_event_whatever_its_framing():
    stream = b": ping\r\nevent: x\r\ndata: caf\xc3\xa9\r\n\r\ndata: [DONE]"

    for cut in range(len(stream) + 1):
        decoder = SseEventDecoder()
        events = [*decoder.feed(stream[:cut]), *decoder.feed(stream[cut:]), *decoder.flush()]
        assert events == [": ping\nevent: x\ndata: caf\u00e9", "data: [DONE]"], cut


_sse_data_lines = st.text(max_size=12).filter(lambda text: "\r" not in text and "\n" not in text)


@settings(max_examples=300, deadline=None)
@given(
    events=st.lists(st.lists(_sse_data_lines, min_size=1, max_size=3), max_size=5),
    line_ending=st.sampled_from(["\n", "\r\n", "\r"]),
    cuts=st.lists(st.integers(min_value=0, max_value=400), max_size=8),
)
def test_sse_data_decoder_output_does_not_depend_on_chunking(events, line_ending, cuts):
    stream = "".join("".join(f"data: {line}{line_ending}" for line in lines) + line_ending for lines in events).encode()

    decoded = _decode_in_chunks(stream, [cut for cut in cuts if cut <= len(stream)])

    assert decoded == ["\n".join(lines) for lines in events]


def test_sse_json_data_decoder_yields_objects_and_done_and_skips_the_rest():
    decoder = SseJsonDataDecoder()
    stream = b'data: {"usage":{"prompt_tokens":1}}\r\n\r\ndata: [1]\n\ndata: not json\n\ndata:  [DONE] \n\n'

    assert decoder.feed(stream) == [{"usage": {"prompt_tokens": 1}}, SSE_DONE]
    assert decoder.flush() == []


_UNUSUAL_DATA_TEXTS = [
    "",
    "   ",
    "[DONE]",
    " [DONE] ",
    "{not-json}",
    "[1,2]",
    "null",
    '"string"',
    '{"a":1}\n',
    '{"a":1}\r\n',
    ' {"a":1}',
    '{"a":1} ',
    '{\n  "type": "response.completed",\n  "response": {"id": "resp_1"}\n}',
    '{"type":"response.output_text.delta","delta":"\u2028\u2029 \ud55c\uae00 \ud14d\uc2a4\ud2b8"}',
    '{"error":{"code":"server_error","message":"boom"}}',
]


@pytest.mark.parametrize("text", _UNUSUAL_DATA_TEXTS)
def test_parse_sse_data_json_text_matches_framed_parse(text: str) -> None:
    assert parse_sse_data_json_text(text) == parse_sse_data_json(f"data: {text}\n\n")


@given(payload=json_objects, ensure_ascii=st.booleans(), indent=st.sampled_from([None, 2]))
@settings(max_examples=60, deadline=None)
def test_parse_sse_data_json_text_matches_framed_parse_for_json_objects(payload, ensure_ascii, indent) -> None:
    text = json.dumps(payload, ensure_ascii=ensure_ascii, indent=indent)
    assert parse_sse_data_json_text(text) == parse_sse_data_json(f"data: {text}\n\n")


def test_parse_sse_data_json_text_preserves_unicode_line_separators() -> None:
    text = '{"type":"response.output_text.delta","delta":"a\u2028b\u2029c"}'
    payload = parse_sse_data_json_text(text)
    assert payload == {"type": "response.output_text.delta", "delta": "a\u2028b\u2029c"}


def test_format_sse_event_from_text_frames_upstream_text_verbatim() -> None:
    text = '{"type":"response.output_text.delta","item_id":"msg_1","delta":"\ud55c\uae00 \u2028 caf\u00e9"}'
    payload = parse_sse_data_json_text(text)
    assert payload is not None

    block = format_sse_event_from_text(payload, text)

    assert block == f"event: response.output_text.delta\ndata: {text}\n\n"
    assert sse_event_type_from_block(block) == "response.output_text.delta"
    assert parse_sse_data_json(block) == parse_sse_data_json(format_sse_event(payload))
    # Upstream UTF-8 stays as-is instead of being re-escaped.
    assert "\ud55c\uae00" in block
    assert "\\u" not in block


def test_format_sse_event_from_text_is_byte_identical_for_ascii_compact_text() -> None:
    payload = {"type": "response.completed", "sequence_number": 7, "response": {"id": "resp_1", "output": []}}
    text = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    assert format_sse_event_from_text(payload, text) == format_sse_event(payload)


def test_format_sse_event_from_text_keeps_typeless_error_frames_data_only() -> None:
    text = '{"error":{"code":"server_error","message":"boom"}}'
    payload = parse_sse_data_json_text(text)
    assert payload is not None
    assert classify_event_type(payload) == "error"

    block = format_sse_event_from_text(payload, text)

    assert block == f"data: {text}\n\n"
    assert block == format_sse_event(payload)


@pytest.mark.parametrize(
    "text",
    [
        '{\n  "type": "response.completed",\n  "response": {"id": "resp_1"}\n}',
        '{"type":"response.completed","response":{"id":"resp_1"}}\n',
        ' {"type":"response.completed","response":{"id":"resp_1"}}',
    ],
)
def test_format_sse_event_from_text_falls_back_to_serialization_for_non_canonical_text(text: str) -> None:
    payload = json.loads(text)
    assert format_sse_event_from_text(payload, text) == format_sse_event(payload)


@given(payload=json_objects, ensure_ascii=st.booleans())
@settings(max_examples=40, deadline=None)
def test_format_sse_event_from_text_round_trips_arbitrary_json_objects(payload, ensure_ascii) -> None:
    text = json.dumps(payload, ensure_ascii=ensure_ascii, separators=(",", ":"))
    block = format_sse_event_from_text(payload, text)
    assert parse_sse_data_json(block) == payload
    assert sse_event_type_from_block(block) == sse_event_type_from_block(format_sse_event(payload))


@pytest.mark.parametrize("origin", ["upstream", "local_event", "local_response_id"])
def test_parsed_sse_block_behaves_like_str_and_short_circuits_parse(origin: str) -> None:
    payload: dict[str, JsonValue] = {"type": "response.output_text.delta", "delta": "hi"}
    plain = format_sse_event(payload)
    is_local = origin == "local_event"
    local_response_id = origin != "upstream"
    if is_local:
        block = format_local_sse_event(payload)
    elif local_response_id:
        block = ParsedSseBlock(plain, payload, response_id_is_local=True)
    else:
        block = sse_block_with_payload(plain, payload)

    assert isinstance(block, ParsedSseBlock)
    assert isinstance(block, str)
    assert block == plain
    assert block.startswith("event: response.output_text.delta\n")
    assert block.encode("utf-8") == plain.encode("utf-8")
    assert parse_sse_data_json(block) is payload
    # Derived strings are plain ``str`` and take the full parse path.
    assert type(block.strip()) is str
    assert parse_sse_data_json(block.strip()) == payload
    assert parse_sse_data_json(block + "") == payload
    # Re-attaching the same payload is an identity operation.
    assert sse_block_with_payload(block, payload) is block
    assert block.is_local is is_local
    assert block.response_id_is_local is local_response_id
    copied_payload = dict(payload)
    reattached = sse_block_with_payload(block, copied_payload)
    assert reattached == plain
    assert parse_sse_data_json(reattached) is copied_payload
    assert reattached.is_local is is_local
    assert reattached.response_id_is_local is local_response_id


def test_parsed_sse_block_with_none_payload_matches_unparseable_parse() -> None:
    for plain in (": keepalive\n\n", "data: [DONE]\n\n", "data: {not-json}\n\n"):
        assert parse_sse_data_json(plain) is None
        assert parse_sse_data_json(sse_block_with_payload(plain, None)) is None


@given(payload=json_objects)
@settings(max_examples=40, deadline=None)
def test_sse_block_with_payload_agrees_with_full_parse(payload) -> None:
    plain = format_sse_event(payload)
    block = sse_block_with_payload(plain, parse_sse_data_json(plain))
    assert parse_sse_data_json(block) == parse_sse_data_json(plain)
    assert extract_sse_data(block) == extract_sse_data(plain)
