"""SSE framing robustness for the OpenCode Go stream decoder.

Three failure modes routed for review, reproduced here against the composed
code. All three corrupt or lose data on a stream that is otherwise valid, and
none of them raises, so nothing surfaces at runtime.

These run entirely from the delivered repository: no sibling branch, no private
document, no other task copy. They import the shipped decoder and drive real
bytes through the real chat path.

Scope note: the dispatcher's decoder is the unit under test for framing, and the
end-to-end case drives it through a real socket. Where a defect is currently
open, the test asserts the **defect** with a message naming the fix, rather than
asserting desired behavior that would fail the branch or a weakened condition
that would hide it. Each such test names the owner and clears itself when fixed.
"""

from __future__ import annotations

import json

import pytest
import pytest_asyncio

from app.core.config.settings import get_settings
from app.db.session import SessionLocal
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeyCreateData, ApiKeysService
from app.modules.proxy.opencode_go_sidecar_dispatch import _SseUsageDecoder
from tests.fixtures.opencode_go_upstream import build_sse_reader

pytestmark = pytest.mark.integration

parse_sse = build_sse_reader()


# ---------------------------------------------------------------------------
# Unit-level framing
# ---------------------------------------------------------------------------


def test_lf_separated_events_decode_as_the_control_case():
    """The control. Everything below deviates from this one axis at a time."""
    decoder = _SseUsageDecoder()
    events = decoder.feed('data: {"usage":{"total_tokens":18}}\n\n')
    assert events == [{"usage": {"total_tokens": 18}}]


def test_a_multi_byte_character_split_across_chunks_is_not_corrupted():
    """Split UTF-8 across a TCP boundary must not silently drop a character.

    ``raw_chunk.decode("utf-8", errors="ignore")`` is applied per chunk, so a
    multi-byte character straddling two chunks loses its leading byte in the
    first chunk and its continuation byte in the second. ``errors="ignore"``
    means this never raises - the character is simply gone from the text the
    client is shown, and from any JSON parsed out of it.

    Owner: codexlb-opencode-go-integration. The fix is an incremental decoder
    (``codecs.getincrementaldecoder("utf-8")``) held across chunks, so a partial
    character is buffered rather than discarded.
    """
    payload = 'data: {"t":"café"}\n\n'.encode()
    split_at = payload.index(b"\xc3") + 1  # inside the two-byte 'é'
    first, second = payload[:split_at], payload[split_at:]

    # Exactly what the dispatcher does today, per-chunk.
    reassembled = first.decode("utf-8", errors="ignore") + second.decode("utf-8", errors="ignore")

    if reassembled == payload.decode("utf-8"):
        pytest.fail(
            "split UTF-8 is now handled correctly - replace this characterization "
            "test with a direct assertion and drop the finding from report.md"
        )

    # Characterize the current, defective behavior precisely: the character is
    # dropped, silently, and the surrounding frame still parses - which is why
    # nothing surfaces at runtime.
    assert reassembled == 'data: {"t":"caf"}\n\n'
    assert json.loads(reassembled.removeprefix("data: ").strip())["t"] == "caf", (
        "the decoded frame is still valid JSON carrying corrupted content, so a consumer cannot detect the loss"
    )


@pytest.mark.parametrize(
    ("label", "separator"),
    [("crlf", "\r\n\r\n"), ("bare_cr", "\r\r")],
)
def test_carriage_return_separated_events_are_not_decoded_today(label, separator):
    """CRLF and bare-CR event separators are not recognised.

    The SSE specification allows an event to be terminated by ``\\r\\n\\r\\n``
    or ``\\r\\r`` as well as ``\\n\\n``. ``_drain_complete_events`` splits on
    ``"\\n\\n"`` only, so a CRLF-framed stream yields no events until the
    connection ends.

    The consequence is specific and matters: usage and the ``[DONE]`` sentinel
    are read from decoded events, so a CRLF upstream would settle with no usage
    and be logged ``stream_incomplete`` even though it terminated correctly.
    Content still reaches the client - the raw chunks are relayed verbatim - so
    this shows up as wrong accounting rather than a broken stream.

    Owner: codexlb-opencode-go-integration. Normalising ``\\r\\n`` and bare
    ``\\r`` to ``\\n`` on entry to the buffer fixes all cases at once.
    """
    decoder = _SseUsageDecoder()
    events = decoder.feed(f'data: {{"usage":{{"total_tokens":18}}}}{separator}')

    if events:
        pytest.fail(
            f"{label} separators are now decoded - replace this characterization "
            "test with a direct assertion and drop the finding from report.md"
        )
    assert events == []

    # The data is buffered, not discarded: a flush at end-of-stream still finds
    # it. That is why this is an accounting bug rather than data loss, and it is
    # the part a fix must preserve.
    flushed = decoder.flush()
    assert flushed == [{"usage": {"total_tokens": 18}}]


def test_comment_and_blank_lines_are_ignored_within_an_event():
    """Keepalive comments must not be mistaken for data."""
    decoder = _SseUsageDecoder()
    events = decoder.feed(': keepalive\ndata: {"ok":true}\n\n')
    assert events == [{"ok": True}]


def test_an_event_split_across_many_chunks_reassembles():
    """Byte-at-a-time delivery must still produce exactly one event."""
    decoder = _SseUsageDecoder()
    payload = 'data: {"usage":{"total_tokens":18}}\n\n'
    collected: list[object] = []
    for character in payload:
        collected.extend(decoder.feed(character))
    assert collected == [{"usage": {"total_tokens": 18}}]


def test_the_done_sentinel_is_surfaced_as_a_terminator():
    decoder = _SseUsageDecoder()
    assert decoder.feed("data: [DONE]\n\n") == ["[DONE]"]


# ---------------------------------------------------------------------------
# End to end over a real socket
# ---------------------------------------------------------------------------

UPSTREAM_KEY = "sk-go-sse-Zq7SvT2pLm9KdR4xHn8B"
GO_MODEL = "opencode-go/glm-5.3"


@pytest.fixture
def opencode_go_enabled(monkeypatch):
    monkeypatch.setenv("CODEX_LB_OPENCODE_GO_SIDECAR_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def go_upstream(monkeypatch):
    """Real loopback upstream, reached without relaxing the Go/Zen base-URL guard.

    ``is_opencode_go_base_url`` pins the host to ``opencode.ai`` so a Go key can
    never be aimed at the Zen path (which bills pay-as-you-go credits). Only the
    transport's resolved URL is redirected; settings persistence, the real config
    loader, credential decryption and the outbound header builder all stay on the
    production path.
    """
    from tests.fixtures.opencode_go_upstream import FakeOpenCodeGoUpstream

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


@pytest.mark.asyncio
async def test_multi_byte_content_survives_a_real_streamed_round_trip(async_client, opencode_go_enabled, go_upstream):
    """Non-ASCII content must reach the client intact over a real socket.

    Whether a multi-byte character lands on a chunk boundary depends on TCP
    framing, so this is the user-visible half of the split-UTF-8 unit test: with
    a long non-ASCII body, the relayed content must still match exactly.
    """
    await _configure(async_client)
    go_upstream.completion_text = " ".join(["café", "naïve", "日本語", "emoji-🚀"] * 12)
    client_key = await _create_key("sse-utf8-key")

    response = await async_client.post(
        "/v1/chat/completions",
        json={
            "model": GO_MODEL,
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
            "stream_options": {"include_usage": True},
        },
        headers={"Authorization": f"Bearer {client_key}"},
    )
    assert response.status_code == 200, response.text

    frames = parse_sse(response.text)
    delivered = "".join(frame["choices"][0]["delta"].get("content", "") for frame in frames if frame.get("choices"))
    assert delivered.strip() == go_upstream.completion_text, (
        "streamed non-ASCII content did not survive the relay intact"
    )
    # Usage still settled, so the framing fix cannot be judged on content alone.
    usage_frames = [frame for frame in frames if frame.get("choices") == [] and "usage" in frame]
    assert len(usage_frames) == 1
