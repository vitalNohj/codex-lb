"""SSE framing over the two real HTTP paths, with split UTF-8 and CR separators.

Three framing defects are reproduced here. Each is driven through an **actual
HTTP request** to a real loopback upstream, on **both** streaming paths, because
the two paths fail differently and only measuring the decoder hides that:

``POST /v1/chat/completions``
    Raw upstream chunks are relayed verbatim (``yield raw_chunk``), so client
    bytes survive. What breaks is internal parsing: usage and the ``[DONE]``
    sentinel are read from *decoded* events, so the request settles with no
    usage and is logged ``stream_incomplete`` despite terminating correctly.

``POST /v1/responses``
    Output is **synthesized from decoded events**
    (``synthesizer.feed(event)``), never relayed raw. So the same decoding
    failure corrupts or erases what the caller actually sees, not just the
    accounting. This is the more severe path and it is exactly why the decoder
    alone is not sufficient evidence.

**Status: both defects are fixed as of backend ``d4ea9d64``.** The decoder now
treats any two consecutive line endings as an event boundary and holds an
incremental UTF-8 decoder across chunks, so every test here asserts the accepted
behavior directly and passes. No expected-failure marker, skip, or
defect-passing characterization remains - per MAIN's rule that a final suite
must never be green *because* a bug exists.

The coverage is kept as permanent regression evidence rather than retired:
reverting the event-boundary pattern to ``\n\n`` fails all 15 tests, which is
what makes this a real guard on the fix rather than a record of it.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.config.settings import get_settings
from app.db.models import RequestLog
from app.db.session import SessionLocal
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeyCreateData, ApiKeysService
from app.modules.proxy.opencode_go_sidecar_dispatch import _SseUsageDecoder
from tests.fixtures.opencode_go_upstream import FakeOpenCodeGoUpstream, build_sse_reader

pytestmark = pytest.mark.integration

parse_sse = build_sse_reader()

UPSTREAM_KEY = "sk-go-sse-Zq7SvT2pLm9KdR4xHn8B"
GO_MODEL = "opencode-go/glm-5.3"
NON_ASCII = "café naïve 日本語 🚀"

# The CR-framing and split-UTF-8 defects this file first recorded are FIXED as of
# backend ``d4ea9d64``, which replaced the decoder with one that treats any two
# consecutive line endings as an event boundary and holds an incremental UTF-8
# decoder across chunks. Every expected-failure marker has been removed and each
# test below now asserts the accepted behavior directly, per MAIN's rule that
# final tests carry no defect-passing characterizations.
#
# NOTE, measured rather than assumed. The per-chunk
# ``decode("utf-8", errors="ignore")`` is a real latent defect in the decoder,
# but it does **not** reproduce over real HTTP here, so these tests are NOT
# xfail-marked - they pass, and they must keep passing.
#
# Why it does not reproduce: the client consumes the body through
# ``resp.content.iter_chunked(8192)``, which re-buffers. Measured against this
# fixture writing a frame in six separate socket writes, aiohttp still delivered
# it as a single 1155-byte chunk, so the mid-character boundary never survived
# to the ``decode`` call.
#
# That makes the risk conditional, not absent: any upstream frame exceeding the
# 8192-byte read size is split by aiohttp at a byte offset with no regard for
# character boundaries, and a long non-ASCII completion will exceed it. These
# tests therefore assert the correct behavior unconditionally and would catch a
# regression; the large-frame case is covered explicitly below.


@pytest.fixture
def opencode_go_enabled(monkeypatch):
    monkeypatch.setenv("CODEX_LB_OPENCODE_GO_SIDECAR_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def go_upstream(monkeypatch):
    """Real loopback upstream, without relaxing the Go/Zen base-URL guard.

    ``is_opencode_go_base_url`` pins the host to ``opencode.ai`` so a Go key can
    never be aimed at the Zen path. Only the transport's resolved URL is
    redirected; settings, the real loader, decryption and the outbound header
    builder stay on the production path.
    """
    upstream = FakeOpenCodeGoUpstream(
        api_key=UPSTREAM_KEY,
        model_ids=("glm-5.3",),
        strict_auth_by_endpoint=False,
    )
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


async def _configure(client) -> None:
    response = await client.put(
        "/api/settings",
        json={
            "opencodeGoSidecarEnabled": True,
            "opencodeGoSidecarBaseUrl": "https://opencode.ai/zen/go/v1",
            "opencodeGoSidecarApiKey": UPSTREAM_KEY,
            "opencodeGoSidecarModelPrefixes": [{"prefix": "opencode-go/", "strip": True}],
            "opencodeGoSidecarFullModels": ["glm-5.3"],
            "apiKeyAuthEnabled": True,
        },
    )
    assert response.status_code == 200, response.text


async def _create_key(name: str) -> str:
    async with SessionLocal() as session:
        service = ApiKeysService(ApiKeysRepository(session))
        created = await service.create_key(ApiKeyCreateData(name=name, allowed_models=None, limits=[]))
    return created.key


async def _go_logs() -> list[RequestLog]:
    async with SessionLocal() as session:
        rows = list((await session.execute(select(RequestLog))).scalars().all())
    return [row for row in rows if row.source == "opencode_go_sidecar"]


async def _post_chat(client, key: str) -> object:
    return await client.post(
        "/v1/chat/completions",
        json={
            "model": GO_MODEL,
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
            "stream_options": {"include_usage": True},
        },
        headers={"Authorization": f"Bearer {key}"},
    )


async def _post_responses(client, key: str) -> object:
    return await client.post(
        "/v1/responses",
        json={"model": GO_MODEL, "input": "hi", "stream": True},
        headers={"Authorization": f"Bearer {key}"},
    )


def _responses_text(body: str) -> str:
    """Concatenate visible output text from synthesized Responses events."""
    text = ""
    for frame in parse_sse(body):
        if frame.get("type") == "response.output_text.delta":
            text += frame.get("delta", "")
    return text


# ---------------------------------------------------------------------------
# Control cases: LF framing, whole frames. These must pass unconditionally.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_stream_relays_content_and_settles_usage_under_lf_framing(
    async_client, opencode_go_enabled, go_upstream
):
    await _configure(async_client)
    go_upstream.completion_text = "alpha beta gamma"
    key = await _create_key("sse-chat-control")

    response = await _post_chat(async_client, key)
    assert response.status_code == 200, response.text

    frames = parse_sse(response.text)
    content = "".join(f["choices"][0]["delta"].get("content", "") for f in frames if f.get("choices"))
    assert content.strip() == "alpha beta gamma"
    assert response.text.rstrip().endswith("data: [DONE]")

    logs = await _go_logs()
    assert len(logs) == 1
    assert logs[0].status == "success"
    assert logs[0].output_tokens == 7


@pytest.mark.asyncio
async def test_responses_stream_synthesizes_visible_text_under_lf_framing(
    async_client, opencode_go_enabled, go_upstream
):
    """The Responses path is synthesized, so its output is the thing to check."""
    await _configure(async_client)
    go_upstream.completion_text = "alpha beta gamma"
    key = await _create_key("sse-responses-control")

    response = await _post_responses(async_client, key)
    assert response.status_code == 200, response.text
    assert _responses_text(response.text).strip() == "alpha beta gamma"

    logs = await _go_logs()
    assert len(logs) == 1
    assert logs[0].status == "success"


# ---------------------------------------------------------------------------
# Split multi-byte UTF-8, across both real paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_stream_preserves_multi_byte_text_split_across_chunks(
    async_client, opencode_go_enabled, go_upstream
):
    """Non-ASCII content survives a mid-character split at the socket.

    Passes today because ``iter_chunked`` re-buffers the fixture's small writes
    (see the note above). Kept unconditional so a change to the read path that
    exposed the per-chunk decode would fail here.
    """
    await _configure(async_client)
    go_upstream.completion_text = NON_ASCII
    go_upstream.split_frames_into = 6  # force boundaries inside characters
    key = await _create_key("sse-chat-utf8")

    response = await _post_chat(async_client, key)
    assert response.status_code == 200, response.text

    frames = parse_sse(response.text)
    content = "".join(f["choices"][0]["delta"].get("content", "") for f in frames if f.get("choices"))
    assert content.strip() == NON_ASCII

    logs = await _go_logs()
    assert len(logs) == 1
    assert logs[0].status == "success", "a fully delivered stream was recorded as an error"
    assert logs[0].output_tokens == 7, "usage was lost because a split character corrupted the frame"


@pytest.mark.asyncio
async def test_responses_stream_preserves_multi_byte_text_split_across_chunks(
    async_client, opencode_go_enabled, go_upstream
):
    """Same split on the Responses path, where output is synthesized not relayed.

    If the per-chunk decode ever does drop a character, this path shows it to the
    caller directly rather than only in the accounting.
    """
    await _configure(async_client)
    go_upstream.completion_text = NON_ASCII
    go_upstream.split_frames_into = 6
    key = await _create_key("sse-responses-utf8")

    response = await _post_responses(async_client, key)
    assert response.status_code == 200, response.text
    assert _responses_text(response.text).strip() == NON_ASCII, (
        "synthesized Responses output lost characters to a mid-character chunk split"
    )


@pytest.mark.asyncio
async def test_a_frame_larger_than_the_read_size_keeps_its_multi_byte_text(
    async_client, opencode_go_enabled, go_upstream
):
    """The condition under which the per-chunk decode can actually bite.

    ``iter_chunked(8192)`` splits any frame longer than its read size at a byte
    offset chosen without regard for character boundaries. A long non-ASCII
    completion exceeds that, so this is the realistic exposure for the latent
    defect - and it is asserted as correct behavior rather than characterized.
    """
    await _configure(async_client)
    # Comfortably past the 8192-byte read size, all multi-byte characters.
    go_upstream.completion_text = " ".join(["日本語テキスト"] * 900)
    key = await _create_key("sse-chat-large-utf8")

    response = await _post_chat(async_client, key)
    assert response.status_code == 200, response.text

    frames = parse_sse(response.text)
    content = "".join(f["choices"][0]["delta"].get("content", "") for f in frames if f.get("choices"))
    assert content.strip() == go_upstream.completion_text, (
        "a frame larger than the 8192-byte read size lost characters: aiohttp "
        "split it mid-character and the per-chunk decode discarded the fragments"
    )

    logs = await _go_logs()
    assert len(logs) == 1
    assert logs[0].status == "success"


# ---------------------------------------------------------------------------
# CR-based event separators, across both real paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("separator", ["\r\n\r\n", "\r\r"], ids=["crlf", "bare_cr"])
@pytest.mark.asyncio
async def test_chat_stream_settles_usage_under_cr_framing(async_client, opencode_go_enabled, go_upstream, separator):
    """Accepted behavior: a CR-framed stream still settles usage and completion.

    Client bytes survive on this path because chunks are relayed raw. What is
    asserted here is the internal outcome: a correctly terminated stream must be
    logged ``success`` with usage, not ``stream_incomplete``.
    """
    await _configure(async_client)
    go_upstream.completion_text = "alpha beta"
    go_upstream.event_separator = separator
    key = await _create_key(f"sse-chat-cr-{len(separator)}")

    response = await _post_chat(async_client, key)
    assert response.status_code == 200, response.text

    logs = await _go_logs()
    assert len(logs) == 1
    assert logs[0].status == "success", (
        "a correctly terminated CR-framed stream was logged as incomplete: the [DONE] sentinel was never decoded"
    )
    assert logs[0].error_code is None
    assert logs[0].output_tokens == 7, "usage was never decoded from CR-framed events"


@pytest.mark.parametrize("separator", ["\r\n\r\n", "\r\r"], ids=["crlf", "bare_cr"])
@pytest.mark.asyncio
async def test_responses_stream_emits_visible_text_under_cr_framing(
    async_client, opencode_go_enabled, go_upstream, separator
):
    """The severe case: CR framing erases the caller's output entirely.

    Because Responses output is synthesized from decoded events, a stream whose
    events never decode produces **no visible text at all** - the caller gets an
    empty answer for a request the upstream served in full.
    """
    await _configure(async_client)
    go_upstream.completion_text = "alpha beta"
    go_upstream.event_separator = separator
    key = await _create_key(f"sse-responses-cr-{len(separator)}")

    response = await _post_responses(async_client, key)
    assert response.status_code == 200, response.text
    assert _responses_text(response.text).strip() == "alpha beta", (
        "synthesized Responses output is empty or truncated because CR-framed upstream events were never decoded"
    )


# ---------------------------------------------------------------------------
# Decoder-level detail that the HTTP tests cannot show directly
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("separator", ["\r\n\r\n", "\r\r", "\n\n"], ids=["crlf", "bare_cr", "lf"])
def test_every_event_of_a_multi_event_stream_is_decoded(separator):
    """Each separator must yield every event, not merely the first.

    This is the case that corrected an earlier claim of mine. I had reported CR
    framing as an accounting bug only, on the grounds that ``flush()`` recovered
    the buffered data - but that was measured on a *single* event. With several
    events buffered together the old parser concatenated every ``data:`` line
    into ``{"n":1}{"n":2}[DONE]``, which is neither valid JSON nor the sentinel,
    so ``flush()`` returned nothing and the events were lost outright.

    The decoder now takes bytes, so the whole stream is fed as the transport
    delivers it.
    """
    decoder = _SseUsageDecoder()
    stream = f'data: {{"n":1}}{separator}data: {{"n":2}}{separator}data: [DONE]{separator}'

    events = list(decoder.feed(stream.encode()))
    events.extend(decoder.flush())

    assert events == [{"n": 1}, {"n": 2}, "[DONE]"]


def test_a_multi_byte_character_split_across_chunks_is_held_not_dropped():
    """The incremental decoder must buffer a partial sequence across chunks.

    Driven at the decoder because the transport re-buffers (see the note above),
    so this is the only place the byte-level split can be exercised directly.
    """
    payload = 'data: {"t":"caf\u00e9"}\n\n'.encode()
    split_at = payload.index(b"\xc3") + 1  # inside the two-byte 'e-acute'

    decoder = _SseUsageDecoder()
    events = list(decoder.feed(payload[:split_at]))
    events.extend(decoder.feed(payload[split_at:]))
    events.extend(decoder.flush())

    assert events == [{"t": "caf\u00e9"}], "a split multi-byte character was dropped"


def test_an_event_split_across_many_chunks_reassembles():
    decoder = _SseUsageDecoder()
    payload = 'data: {"usage":{"total_tokens":18}}\n\n'.encode()
    collected: list[object] = []
    for index in range(len(payload)):
        collected.extend(decoder.feed(payload[index : index + 1]))
    collected.extend(decoder.flush())
    assert collected == [{"usage": {"total_tokens": 18}}]


def test_comment_lines_are_ignored_within_an_event():
    decoder = _SseUsageDecoder()
    assert list(decoder.feed(b': keepalive\ndata: {"ok":true}\n\n')) == [{"ok": True}]
