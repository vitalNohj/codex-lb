"""SSE framing and byte-boundary handling in the NVIDIA and OpenAI-compat decoders.

Both decoders previously recognised only ``\\n\\n`` as an event delimiter and
decoded each network chunk independently with ``errors="ignore"``. Reported on
https://github.com/vitalNohj/codex-lb/pull/59 and reproduced here before fixing.

Both integrations point at *arbitrary* OpenAI-compatible servers (vLLM,
LM Studio, llama.cpp, NIM, ...), so neither the line-ending dialect nor the
chunk boundaries are ours to assume. The same properties are already covered for
the OpenCode Go decoder in ``tests/unit/test_opencode_go_sidecar_dispatch.py``;
this file holds the two decoders that still lacked them.

OpenAI-compat (with OpenRouter and OrcaRouter) now decodes with the shared
``app.core.utils.sse.SseJsonDataDecoder``, specified in ``tests/unit/test_sse.py``;
it stays here so both decoders keep meeting the same bar.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from app.core.utils.sse import SseJsonDataDecoder
from app.modules.proxy.nvidia_sidecar_dispatch import _SseUsageDecoder as NvidiaSseUsageDecoder

_DECODERS: tuple[tuple[str, Callable[[], object]], ...] = (
    ("nvidia", NvidiaSseUsageDecoder),
    ("shared", SseJsonDataDecoder),
)


@pytest.fixture(params=_DECODERS, ids=[name for name, _ in _DECODERS])
def events(request: pytest.FixtureRequest) -> Callable[..., list]:
    """Feed byte chunks through one decoder and return every event it emitted."""

    _, factory = request.param

    def _events(*chunks: bytes) -> list:
        decoder = factory()
        out: list = []
        for chunk in chunks:
            out.extend(decoder.feed(chunk))
        out.extend(decoder.flush())
        return out

    return _events


@pytest.mark.parametrize("eol", [b"\n", b"\r\n", b"\r"], ids=["lf", "crlf", "cr"])
def test_every_spec_permitted_line_ending_delimits_events(events, eol: bytes) -> None:
    """CRLF and bare CR are as valid as LF, and an arbitrary server's dialect is not ours to pick.

    Before the fix a CRLF stream produced no usable events: everything buffered
    to EOF and then parsed as one malformed event, so the usage object and
    ``[DONE]`` were both lost. That is not cosmetic - the iterator treats a
    missing ``[DONE]`` as an incomplete stream, so a perfectly successful
    request was logged as an error and its reservation released instead of
    finalized.
    """

    stream = (
        b'data: {"choices":[{"delta":{"content":"hi"}}],'
        b'"usage":{"prompt_tokens":10,"completion_tokens":5}}' + eol + eol + b"data: [DONE]" + eol + eol
    )

    emitted = events(stream)

    assert emitted[0]["choices"][0]["delta"]["content"] == "hi"
    assert emitted[0]["usage"]["prompt_tokens"] == 10
    assert emitted[-1] == "[DONE]"


def test_events_are_emitted_during_the_stream_not_only_at_eof(events) -> None:
    """A CRLF-framed event must surface when it arrives, not be buffered to EOF."""

    emitted = events(b'data: {"choices":[{"delta":{"content":"hi"}}]}\r\n\r\n')

    assert emitted and emitted[0]["choices"][0]["delta"]["content"] == "hi"


@pytest.mark.parametrize("split_marker", [b"\xc3", b"\xe6"], ids=["two-byte", "three-byte"])
def test_a_character_split_across_chunks_is_reassembled(events, split_marker: bytes) -> None:
    """aiohttp splits on byte offsets, not character boundaries.

    Decoding each chunk independently with ``errors="ignore"`` silently deleted
    the partial sequence. The raw bytes still reach the client untouched, so the
    visible damage is to what this observer parses - and a multi-byte character
    landing inside the event that carries ``usage`` corrupts that JSON, which
    loses the usage the reservation settles against.
    """

    payload = 'data: {"choices":[{"delta":{"content":"café 日本"}}],"usage":{"prompt_tokens":4}}\n\n'.encode("utf-8")
    cut = payload.index(split_marker) + 1

    emitted = events(payload[:cut], payload[cut:])

    assert emitted[0]["choices"][0]["delta"]["content"] == "café 日本"
    assert emitted[0]["usage"]["prompt_tokens"] == 4


def test_a_delimiter_split_across_chunks_still_closes_the_event(events) -> None:
    """The two-character CRLF delimiter can itself straddle a chunk boundary."""

    payload = b'data: {"choices":[{"delta":{"content":"hi"}}]}\r\n\r\ndata: [DONE]\r\n\r\n'
    cut = payload.index(b"\r\n\r\n") + 2

    emitted = events(payload[:cut], payload[cut:])

    assert emitted[0]["choices"][0]["delta"]["content"] == "hi"
    assert emitted[-1] == "[DONE]"


def test_byte_at_a_time_delivery_yields_the_same_events(events) -> None:
    """The worst-case framing: every boundary is a split boundary."""

    payload = 'data: {"choices":[{"delta":{"content":"café"}}]}\r\n\r\ndata: [DONE]\r\n\r\n'.encode("utf-8")

    emitted = events(*(payload[i : i + 1] for i in range(len(payload))))

    assert emitted[0]["choices"][0]["delta"]["content"] == "café"
    assert emitted[-1] == "[DONE]"


def test_a_final_event_without_a_trailing_delimiter_is_not_lost(events) -> None:
    """An upstream that ends without a final blank line still reported usage."""

    emitted = events(b'data: {"usage":{"prompt_tokens":7,"completion_tokens":3}}')

    assert emitted[0]["usage"]["prompt_tokens"] == 7


def test_invalid_bytes_are_replaced_rather_than_silently_dropped(events) -> None:
    """Genuinely invalid bytes stay visible instead of shortening the text."""

    emitted = events(b'data: {"choices":[{"delta":{"content":"a\xffb"}}]}\n\n')

    assert emitted[0]["choices"][0]["delta"]["content"] == "a\ufffdb"


def test_a_crlf_framed_error_before_done_is_still_seen(events) -> None:
    """The error-classification fix depends on the error event being parsed at all.

    With ``\\n\\n``-only framing a CRLF stream never surfaced the ``error``
    event, so an errored stream was still classified as a success - exactly the
    defect commit ``fbddc891`` set out to fix, silently reintroduced by the
    framing bug for any CRLF upstream.
    """

    emitted = events(b'data: {"error":{"code":"upstream_oom","message":"out of memory"}}\r\n\r\ndata: [DONE]\r\n\r\n')

    assert emitted[0]["error"]["code"] == "upstream_oom"
    assert emitted[-1] == "[DONE]"
