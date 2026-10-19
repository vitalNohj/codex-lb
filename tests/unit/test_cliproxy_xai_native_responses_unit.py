"""Unit tests for the native xAI Responses route and its helpers."""

from __future__ import annotations

import json
import logging
from typing import Any, cast

import pytest

from app.core.clients.claude_sidecar import (
    ClaudeSidecarClient,
    ClaudeSidecarConfig,
    ClaudeSidecarError,
    ClaudeSidecarUnavailableError,
    SidecarPrefix,
)
from app.core.config.settings import get_settings
from app.core.openai.requests import ResponsesRequest
from app.modules.claude_sidecar import session_affinity_guard
from app.modules.proxy import cliproxy_account_routing as routing
from app.modules.proxy.claude_sidecar_dispatch import extract_usage, extract_xai_billed_cost
from app.modules.proxy.cliproxy_account_routing import (
    CliproxyStickyHints,
    cliproxy_conversation_id,
    cliproxy_responses_sticky_hints,
)
from app.modules.proxy.cliproxy_responses_dispatch import (
    _SseEventFramer,
    build_cliproxy_xai_responses_body,
    is_cliproxy_xai_model,
    native_conversation_id,
    use_cliproxy_xai_native_responses,
)

pytestmark = pytest.mark.unit

ENCRYPTED = "Q2lwaGVydGV4dDEyMzQ1Njc4OTBhYmNkZWZnaGlqa2xtbm9wcXJzdHV2d3h5ejAxMjM0NTY3ODk"


# --- model classification ------------------------------------------------------------


@pytest.mark.parametrize("model", ["grok-4.3", "grok-4-fast", "Grok-Code-Fast-1", " grok-4 "])
def test_plain_grok_ids_are_xai(model: str) -> None:
    assert is_cliproxy_xai_model(model)


@pytest.mark.parametrize(
    "model",
    ["devin/grok-4-6", "acct/grok-4.3", "claude-sonnet-4-5", "gpt-5.4", "", "xai-grok", "groq-llama"],
)
def test_other_ids_are_not_xai(model: str) -> None:
    assert not is_cliproxy_xai_model(model)


def test_only_the_cliproxy_provider_takes_the_native_route(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    try:
        assert use_cliproxy_xai_native_responses("claude", "grok-4.3")
        assert not use_cliproxy_xai_native_responses("openrouter", "grok-4.3")
        assert not use_cliproxy_xai_native_responses("openai_compat:xai", "grok-4.3")
        monkeypatch.setenv("CODEX_LB_CLIPROXY_XAI_NATIVE_RESPONSES_ENABLED", "false")
        get_settings.cache_clear()
        assert not use_cliproxy_xai_native_responses("claude", "grok-4.3")
    finally:
        get_settings.cache_clear()


def test_the_switch_defaults_on() -> None:
    get_settings.cache_clear()
    try:
        assert get_settings().cliproxy_xai_native_responses_enabled is True
    finally:
        get_settings.cache_clear()


# --- request body ----------------------------------------------------------------------


def _payload(**overrides: object) -> ResponsesRequest:
    data: dict[str, object] = {
        "model": "grok-4.3",
        "instructions": "Be brief.",
        "input": [
            {"role": "user", "content": [{"type": "input_text", "text": "hi"}]},
            {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": ENCRYPTED},
        ],
    }
    data.update(overrides)
    return ResponsesRequest.model_validate(data)


def test_the_body_keeps_reasoning_items_and_sets_model_and_key() -> None:
    built = build_cliproxy_xai_responses_body(
        _payload(),
        wire_model="acct/grok-4.3",
        conversation_id="conv-1",
        default_reasoning_effort=None,
    )
    assert built.body["model"] == "acct/grok-4.3"
    assert built.body["prompt_cache_key"] == "conv-1"
    items = cast(list[dict[str, Any]], built.body["input"])
    assert items[1] == {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": ENCRYPTED}
    assert "reasoning" not in built.body
    assert built.requested_reasoning_effort is None
    assert built.effective_reasoning_effort is None


def test_the_default_effort_fills_only_a_missing_effort() -> None:
    kept = build_cliproxy_xai_responses_body(
        _payload(reasoning={"effort": "high", "summary": "auto"}),
        wire_model="grok-4.3",
        conversation_id="c",
        default_reasoning_effort="low",
    )
    assert kept.body["reasoning"] == {"effort": "high", "summary": "auto"}
    assert (kept.requested_reasoning_effort, kept.effective_reasoning_effort) == ("high", "high")

    filled = build_cliproxy_xai_responses_body(
        _payload(reasoning={"summary": "auto"}),
        wire_model="grok-4.3",
        conversation_id="c",
        default_reasoning_effort=" low ",
    )
    assert filled.body["reasoning"] == {"summary": "auto", "effort": "low"}
    assert (filled.requested_reasoning_effort, filled.effective_reasoning_effort) == (None, "low")


def test_a_client_cache_key_is_replaced_by_the_conversation_id() -> None:
    built = build_cliproxy_xai_responses_body(
        _payload(prompt_cache_key="client"),
        wire_model="grok-4.3",
        conversation_id="client",
        default_reasoning_effort=None,
    )
    assert built.body["prompt_cache_key"] == "client"


# --- conversation id = sticky pin id ---------------------------------------------------


@pytest.mark.parametrize(
    ("hints", "headers", "expected_key"),
    [
        (CliproxyStickyHints(prompt_cache_key="pck"), {}, "cliproxy:prompt_cache:pck"),
        (CliproxyStickyHints(), {"X-Session-Id": "sess"}, "cliproxy:session:sess"),
        (CliproxyStickyHints(body_session_id="body"), {}, "cliproxy:session:body"),
        (CliproxyStickyHints(derived_key="derived"), {}, "cliproxy:derived:derived"),
    ],
)
def test_the_cache_key_is_the_id_inside_the_pin_key(
    hints: CliproxyStickyHints, headers: dict[str, str], expected_key: str
) -> None:
    identity = routing._resolve_sticky_identity(hints, headers, sticky_enabled=True)
    conversation_id = cliproxy_conversation_id(hints, headers)
    assert identity.key == expected_key
    assert conversation_id is not None
    assert identity.key.endswith(f":{conversation_id}")


def test_a_long_body_session_id_is_hashed_the_same_in_both() -> None:
    hints = CliproxyStickyHints(body_session_id="s" * 1000)
    identity = routing._resolve_sticky_identity(hints, {}, sticky_enabled=True)
    conversation_id = cliproxy_conversation_id(hints, {})
    assert identity.key == f"cliproxy:session:{conversation_id}"


def test_the_cache_key_is_read_even_when_sticky_routing_is_off() -> None:
    assert (
        routing._resolve_sticky_identity(CliproxyStickyHints(prompt_cache_key="pck"), {}, sticky_enabled=False).key
        is None
    )
    assert cliproxy_conversation_id(CliproxyStickyHints(prompt_cache_key="pck"), {}) == "pck"


def test_a_keyless_request_gets_a_fresh_cache_key_each_time() -> None:
    first = native_conversation_id(CliproxyStickyHints(), {})
    second = native_conversation_id(CliproxyStickyHints(), {})
    assert first.startswith("codex-lb-") and second.startswith("codex-lb-")
    assert first != second


def test_responses_hints_feed_the_conversation_id() -> None:
    payload = _payload(prompt_cache_key="thread-1")
    hints = cliproxy_responses_sticky_hints(payload, prompt_cache_key_derived=False)
    assert native_conversation_id(hints, {}) == "thread-1"


# --- usage and cost --------------------------------------------------------------------


def test_responses_usage_maps_cached_and_reasoning_tokens() -> None:
    usage = extract_usage(
        {
            "usage": {
                "input_tokens": 100,
                "input_tokens_details": {"cached_tokens": 80},
                "output_tokens": 20,
                "output_tokens_details": {"reasoning_tokens": 12},
            }
        }
    )
    assert usage is not None
    assert (usage.input_tokens, usage.cached_input_tokens, usage.output_tokens) == (100, 80, 20)
    assert usage.reasoning_tokens == 12


def test_chat_usage_maps_reasoning_tokens() -> None:
    usage = extract_usage(
        {
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "completion_tokens_details": {"reasoning_tokens": 3},
            }
        }
    )
    assert usage is not None
    assert usage.reasoning_tokens == 3


def test_usage_without_reasoning_detail_has_none() -> None:
    usage = extract_usage({"usage": {"input_tokens": 1, "output_tokens": 1}})
    assert usage is not None
    assert usage.reasoning_tokens is None


@pytest.mark.parametrize(
    ("ticks", "expected"),
    [
        (10_000_000_000, 1.0),
        (123_456_789, 0.0123456789),
        (1, 1e-10),
        (5.0, 5e-10),
    ],
)
def test_xai_ticks_are_converted_to_usd(ticks: Any, expected: float) -> None:
    payload: Any = {"usage": {"cost_in_usd_ticks": ticks}}
    assert extract_xai_billed_cost(payload) == pytest.approx(expected)


@pytest.mark.parametrize(
    "ticks",
    [0, -5, None, "123", True, 1.5, float("nan"), float("inf")],
)
def test_unusable_xai_ticks_are_ignored(ticks: Any) -> None:
    payload: Any = {"usage": {"cost_in_usd_ticks": ticks}}
    assert extract_xai_billed_cost(payload) is None


@pytest.mark.parametrize("payload", [None, [], {"usage": None}, {"usage": {}}, {"usage": {"cost": 0.5}}])
def test_a_missing_tick_field_is_no_cost(payload: Any) -> None:
    assert extract_xai_billed_cost(payload) is None


# --- SSE framing -----------------------------------------------------------------------


def test_the_framer_emits_only_whole_events_and_loses_no_byte() -> None:
    whole = b'event: a\ndata: {"x":1}\n\nevent: b\r\ndata: {"y":"\xc3\xa9"}\r\n\r\ndata: tail\n\n'
    framer = _SseEventFramer()
    out = []
    for index in range(len(whole)):
        frame = framer.feed(whole[index : index + 1])
        if frame:
            assert frame.endswith(("\n\n", "\r\n\r\n"))
            out.append(frame)
    out.append(framer.flush())
    assert "".join(out).encode() == whole


def test_the_framer_holds_a_chunk_with_no_boundary() -> None:
    framer = _SseEventFramer()
    assert framer.feed(b"data: {") == ""
    assert framer.feed(b'"a":1}\n') == ""
    assert framer.feed(b"\n") == 'data: {"a":1}\n\n'
    assert framer.flush() == ""


@pytest.mark.parametrize(
    ("tail", "closed"),
    [
        (b'data: {"type":"response.output_text.delta"', 'data: {"type":"response.output_text.delta"\n\n'),
        (b"data: x\n", "data: x\n\n"),
        (b"data: x\r\n", "data: x\r\n\r\n"),
    ],
)
def test_the_framer_closes_an_event_the_upstream_left_open(tail: bytes, closed: str) -> None:
    """Whatever follows a cut stream must parse as its own event."""

    framer = _SseEventFramer()
    assert framer.feed(tail) == ""
    assert framer.flush() == closed


def test_a_failure_frame_after_a_cut_tail_parses_as_its_own_event() -> None:
    from app.core.utils.sse import SseJsonDataDecoder

    framer = _SseEventFramer()
    framer.feed(b'event: response.output_text.delta\ndata: {"type":"response.output_text.delta"')
    stream = framer.flush() + 'event: response.failed\ndata: {"type":"response.failed"}\n\n'

    decoder = SseJsonDataDecoder()
    events = decoder.feed(stream.encode()) + decoder.flush()
    assert {"type": "response.failed"} in events


def test_the_framer_keeps_a_lone_newline_inside_an_event() -> None:
    """A single ``\\n`` is not an event boundary; -1 + 2 must not read as one."""

    framer = _SseEventFramer()
    assert framer.feed(b"x") == ""
    assert framer.feed(b"\n") == ""


# --- client -----------------------------------------------------------------------------


def _config() -> ClaudeSidecarConfig:
    return ClaudeSidecarConfig(
        enabled=True,
        base_url="http://127.0.0.1:8317",
        api_key="sidecar-key",
        prefixes=(SidecarPrefix(prefix="claude", strip=False),),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
    )


class _Content:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def iter_chunked(self, _size: int):
        for chunk in self._chunks:
            yield chunk


class _Response:
    def __init__(self, status: int, text: str, chunks: list[bytes] | None = None) -> None:
        self.status = status
        self._text = text
        self.content = _Content(chunks or [])

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def text(self) -> str:
        return self._text


class _Session:
    def __init__(self, response: _Response | Exception) -> None:
        self.response = response
        self.urls: list[str] = []
        self.headers: list[dict[str, str]] = []
        self.bodies: list[Any] = []

    def post(self, url: str, *, headers: dict[str, str], json: Any, timeout: object):
        del timeout
        self.urls.append(url)
        self.headers.append(headers)
        self.bodies.append(json)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class _Lease:
    def __init__(self, session: _Session) -> None:
        self.session = session

    async def __aenter__(self) -> _Session:
        return self.session

    async def __aexit__(self, *_exc: object) -> None:
        return None


def _install_session(monkeypatch: pytest.MonkeyPatch, session: _Session) -> None:
    monkeypatch.setattr("app.core.clients.claude_sidecar.lease_http_session", lambda: _Lease(session))


async def test_responses_posts_to_the_native_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session(_Response(200, json.dumps({"id": "resp_1", "object": "response"})))
    _install_session(monkeypatch, session)
    body = {"model": "grok-4.3", "input": "hi"}

    result = await ClaudeSidecarClient(_config()).responses(body)

    assert result == {"id": "resp_1", "object": "response"}
    assert session.urls == ["http://127.0.0.1:8317/v1/responses"]
    assert session.bodies == [body]
    assert session.headers[0]["Authorization"] == "Bearer sidecar-key"
    assert not any(name.lower().startswith(("session", "x-session")) for name in session.headers[0])


async def test_responses_relays_an_error_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session(_Response(429, '{"error":{"message":"slow down","type":"rate_limit_error"}}'))
    _install_session(monkeypatch, session)

    with pytest.raises(ClaudeSidecarError) as exc_info:
        await ClaudeSidecarClient(_config()).responses({"model": "grok-4.3"})

    assert exc_info.value.status_code == 429
    assert exc_info.value.message == "slow down"


async def test_responses_transport_failure_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_session(monkeypatch, _Session(OSError("boom")))

    with pytest.raises(ClaudeSidecarUnavailableError) as exc_info:
        await ClaudeSidecarClient(_config()).responses({"model": "grok-4.3"})

    assert "CLIProxyAPI responses" in str(exc_info.value)


async def test_stream_responses_posts_to_the_native_entry_and_yields_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    chunks = [b"event: response.created\ndata: {}\n\n", b"data: [x]\n\n"]
    session = _Session(_Response(200, "", chunks))
    _install_session(monkeypatch, session)

    async with ClaudeSidecarClient(_config()).stream_responses({"model": "grok-4.3", "stream": True}) as stream:
        received = [chunk async for chunk in stream]

    assert session.urls == ["http://127.0.0.1:8317/v1/responses"]
    assert b"".join(received) == b"".join(chunks)


async def test_chat_still_posts_to_chat_completions(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session(_Response(200, "{}"))
    _install_session(monkeypatch, session)

    await ClaudeSidecarClient(_config()).chat_completion({"model": "claude", "messages": []})

    assert session.urls == ["http://127.0.0.1:8317/v1/chat/completions"]


# --- session affinity guard ---------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_guard() -> None:
    session_affinity_guard.reset_session_affinity_guard()


class _Gauge:
    def __init__(self) -> None:
        self.values: list[float] = []

    def set(self, value: float) -> None:
        self.values.append(value)


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.WARNING and "session-affinity is off" in record.getMessage()
    ]


def test_affinity_off_warns_and_repeats_only_after_the_interval(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    gauge = _Gauge()
    monkeypatch.setattr(session_affinity_guard, "cliproxy_session_affinity_enabled", gauge)
    caplog.set_level(logging.INFO, logger=session_affinity_guard.__name__)

    session_affinity_guard.observe_session_affinity(False, now=0.0)
    session_affinity_guard.observe_session_affinity(False, now=60.0)
    assert len(_warnings(caplog)) == 1
    session_affinity_guard.observe_session_affinity(
        False, now=session_affinity_guard.SESSION_AFFINITY_WARNING_REPEAT_SECONDS + 1
    )
    assert len(_warnings(caplog)) == 2
    assert gauge.values == [0, 0, 0]


def test_affinity_on_is_quiet_and_turning_off_again_warns_at_once(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    gauge = _Gauge()
    monkeypatch.setattr(session_affinity_guard, "cliproxy_session_affinity_enabled", gauge)
    caplog.set_level(logging.INFO, logger=session_affinity_guard.__name__)

    session_affinity_guard.observe_session_affinity(True, now=0.0)
    assert _warnings(caplog) == []
    session_affinity_guard.observe_session_affinity(False, now=1.0)
    session_affinity_guard.observe_session_affinity(True, now=2.0)
    session_affinity_guard.observe_session_affinity(False, now=3.0)
    assert len(_warnings(caplog)) == 2
    assert gauge.values == [1, 0, 1, 0]


class _AffinityClient:
    def __init__(self, result: bool | Exception) -> None:
        self.result = result

    async def get_session_affinity(self) -> bool:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


async def test_the_check_reports_the_state(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger=session_affinity_guard.__name__)
    assert await session_affinity_guard.check_cliproxy_session_affinity(cast(Any, _AffinityClient(False))) is False
    assert len(_warnings(caplog)) == 1
    assert await session_affinity_guard.check_cliproxy_session_affinity(cast(Any, _AffinityClient(True))) is True


@pytest.mark.parametrize("error", [ClaudeSidecarUnavailableError("down"), ClaudeSidecarError(500, "x"), ValueError()])
async def test_a_failed_read_never_raises(error: Exception) -> None:
    assert await session_affinity_guard.check_cliproxy_session_affinity(cast(Any, _AffinityClient(error))) is None


# --- stream settlement on client disconnect ---------------------------------------------


class _OneStreamClient:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks

    def stream_responses(self, payload):
        del payload
        chunks = self.chunks

        class _Stream:
            async def __aenter__(self):
                async def iterate():
                    for chunk in chunks:
                        yield chunk

                return iterate()

            async def __aexit__(self, *exc):
                return False

        return _Stream()


def _sse(event: dict) -> bytes:
    return f"event: {event['type']}\ndata: {json.dumps(event)}\n\n".encode()


async def _close_after(frames_wanted: int, chunks: list[bytes], monkeypatch) -> tuple[list[str], list[str]]:
    from app.modules.proxy import claude_sidecar_dispatch, cliproxy_responses_dispatch

    monkeypatch.setattr(claude_sidecar_dispatch, "CLAUDE_SIDECAR_COOLDOWN_WAIT_SECONDS", 0.0)
    outcomes: list[str] = []

    async def fake_settle(reservation, *, log, response, failure):
        del reservation, log, failure
        outcomes.append("settled" if response is not None else "settled-without-usage")

    async def fake_release(*args, **kwargs):
        del args, kwargs
        outcomes.append("released")

    monkeypatch.setattr(cliproxy_responses_dispatch, "_settle_and_log", fake_settle)
    monkeypatch.setattr(cliproxy_responses_dispatch, "_release_and_log_sidecar_request", fake_release)
    log = cliproxy_responses_dispatch._LogFields(
        api_key=None, model="grok-4.3", started_at=0.0, reasoning_effort=None, requested_reasoning_effort=None
    )
    stream = cliproxy_responses_dispatch._native_stream(
        {"model": "grok-4.3"},
        client=cast(Any, _OneStreamClient(chunks)),
        reservation=None,
        log=log,
    )
    frames: list[str] = []
    async for frame in stream:
        frames.append(frame)
        if len(frames) == frames_wanted:
            break
    await stream.aclose()
    return frames, outcomes


@pytest.mark.asyncio
async def test_a_client_leaving_after_the_terminal_event_is_still_charged(monkeypatch) -> None:
    """xAI billed the turn once response.completed arrived; a disconnect must not release it."""

    completed = {
        "type": "response.completed",
        "response": {"id": "r", "status": "completed", "usage": {"input_tokens": 3, "output_tokens": 2}},
    }
    frames, outcomes = await _close_after(1, [_sse(completed)], monkeypatch)

    assert "response.completed" in frames[0]
    assert outcomes == ["settled"]


@pytest.mark.asyncio
async def test_a_client_leaving_mid_turn_releases_the_reservation(monkeypatch) -> None:
    delta = {"type": "response.output_text.delta", "delta": "hi"}
    completed = {"type": "response.completed", "response": {"id": "r", "usage": {"input_tokens": 3}}}
    frames, outcomes = await _close_after(1, [_sse(delta), _sse(completed)], monkeypatch)

    assert "output_text.delta" in frames[0]
    assert outcomes == ["released"]
