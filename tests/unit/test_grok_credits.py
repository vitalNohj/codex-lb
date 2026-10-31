from __future__ import annotations

import asyncio
import base64
import json
import struct
from collections.abc import Mapping
from datetime import datetime, timezone

import pytest

from app.core.clients.claude_sidecar import ClaudeSidecarError, ClaudeSidecarUnavailableError
from app.core.types import JsonValue
from app.modules.claude_sidecar import grok_credits as grok_credits_module
from app.modules.claude_sidecar.grok_credits import (
    GrokCreditsError,
    GrokCreditsRateLimit,
    GrokCreditsUnavailable,
    _PRODUCT_NAMES,
    classify_xai_429,
    decode_grpc_web_body,
    fetch_grok_credits,
    normalize_grok_consumer_payload,
    note_xai_usage_queue,
    project_xai_usage,
    take_xai_usage_observations,
)
from app.modules.claude_sidecar.quota import (
    GrokCreditsQuota,
    GrokCreditWindow,
    GrokTokenRollup,
    SidecarAuthQuota,
    SidecarQuotaSnapshot,
    claude_quota_snapshot,
    snapshot_from_json,
    snapshot_to_json,
)
from app.modules.claude_sidecar.rate_limit_hold import XAI_LIMIT_BACKOFF, XAI_LIMIT_FREE_USAGE

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 10, 16, 8, 0, tzinfo=timezone.utc)
_START = datetime(2026, 10, 12, 0, 0, tzinfo=timezone.utc)
_RESET = datetime(2026, 10, 19, 0, 0, tzinfo=timezone.utc)


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _key(field: int, wire: int) -> bytes:
    return _varint((field << 3) | wire)


def _message(field: int, payload: bytes) -> bytes:
    return _key(field, 2) + _varint(len(payload)) + payload


def _float(field: int, value: float) -> bytes:
    return _key(field, 5) + struct.pack("<f", value)


def _field_varint(field: int, value: int) -> bytes:
    return _key(field, 0) + _varint(value)


def _timestamp(seconds: int) -> bytes:
    return _field_varint(1, seconds)


def _period(kind: int, start: datetime, reset: datetime) -> bytes:
    return (
        _field_varint(1, kind)
        + _message(2, _timestamp(int(start.timestamp())))
        + _message(3, _timestamp(int(reset.timestamp())))
    )


def _weekly_config() -> bytes:
    """quota-axi field layout: config.1 percent, .7 products, .8 period, .12 prepaid."""

    product = _field_varint(1, 2) + _float(2, 12.5)
    prepaid = _field_varint(1, 42)
    return _float(1, 37.5) + _message(7, product) + _message(8, _period(2, _START, _RESET)) + _message(12, prepaid)


def _grpc_text(payload: bytes, *, trailer: bytes | None = None) -> str:
    frame = b"\x00" + len(payload).to_bytes(4, "big") + payload
    if trailer is not None:
        frame += b"\x80" + len(trailer).to_bytes(4, "big") + trailer
    return base64.b64encode(frame).decode("ascii")


def _account(provider: str, auth_index: str, *, credits: GrokCreditsQuota | None = None) -> SidecarAuthQuota:
    return SidecarAuthQuota(
        name=f"{provider}.json",
        auth_index=auth_index,
        email=f"{provider}@example.com",
        provider=provider,
        status="active",
        status_message=None,
        disabled=False,
        unavailable=False,
        quota_exceeded=False,
        next_recover_at=None,
        model_states=(),
        success=0,
        failed=0,
        last_refresh=None,
        grok_credits=credits,
    )


def test_parser_reads_quota_axi_weekly_windows_and_prepaid() -> None:
    parsed = normalize_grok_consumer_payload(_message(1, _weekly_config()), now=_NOW)

    assert parsed.prepaid_credits == 42
    assert parsed.refreshed_at == _NOW
    [credits] = parsed.windows
    assert credits == GrokCreditWindow(
        id="credits",
        label="week",
        kind="weekly",
        percent_used=pytest.approx(37.5),
        percent_remaining=pytest.approx(62.5),
        starts_at=_START,
        resets_at=_RESET,
    )
    assert all(window.id != "product:grok_build" for window in parsed.windows)


def test_parser_drops_grok_build_and_keeps_the_other_products() -> None:
    """Product 2 is Grok Build and is not a dashboard window; every other product stays."""

    products = b"".join(
        _message(7, _field_varint(1, number) + _float(2, float(number))) for number in (1, 2, 4, 9)
    )
    config = _float(1, 1.0) + products + _message(8, _period(2, _START, _RESET))
    parsed = normalize_grok_consumer_payload(_message(1, config), now=_NOW)

    assert [window.id for window in parsed.windows] == [
        "credits",
        "product:api",
        "product:chat",
        "product:grok_bot",
    ]
    assert "product:grok_build" not in {window.id for window in parsed.windows}
    assert _PRODUCT_NAMES[2] == ("grok_build", "Grok Build")


def test_parser_keeps_prepaid_credits_when_grok_build_is_the_only_window() -> None:
    """Hiding product 2 must not fail the payload before prepaid credits are read."""

    product = _field_varint(1, 2) + _float(2, 12.5)
    config = _message(7, product) + _message(12, _field_varint(1, 42))
    parsed = normalize_grok_consumer_payload(_message(1, config), now=_NOW)

    assert parsed.windows == ()
    assert parsed.prepaid_credits == 42
    assert parsed.refreshed_at == _NOW


def test_parser_names_grok_bot_and_falls_back_for_an_unmapped_product() -> None:
    products = b"".join(_message(7, _field_varint(1, number) + _float(2, 10.0)) for number in (7, 8, 9, 10, 11, 12))
    config = _float(1, 1.0) + products + _message(8, _period(2, _START, _RESET))
    parsed = normalize_grok_consumer_payload(_message(1, config), now=_NOW)

    by_id = {window.id: window.label for window in parsed.windows}
    assert by_id["product:grok_app_builder"] == "Grok App Builder"
    assert by_id["product:grok_tasks"] == "Grok Tasks"
    assert by_id["product:grok_bot"] == "Grok Bot"
    assert by_id["product:cursor"] == "Cursor"
    assert by_id["product:bugbot"] == "Bugbot"
    assert by_id["product:unknown_12"] == "Product 12"


def test_parser_uses_zero_when_a_valid_period_has_no_explicit_percent() -> None:
    config = _message(8, _period(1, _START, _RESET)) + _message(7, _field_varint(1, 4))
    parsed = normalize_grok_consumer_payload(_message(1, config), now=_NOW)

    assert [window.id for window in parsed.windows] == ["credits", "product:chat"]
    assert parsed.windows[0].kind == "monthly"
    assert parsed.windows[0].label == "month"
    assert parsed.windows[0].percent_used == 0.0
    assert parsed.windows[1].label == "Chat"
    assert parsed.windows[1].percent_used == 0.0
    assert parsed.prepaid_credits is None


def test_parser_clamps_percent_and_rejects_an_empty_config() -> None:
    config = _float(1, 140.0) + _message(8, _period(2, _START, _RESET))
    parsed = normalize_grok_consumer_payload(_message(1, config), now=_NOW)
    assert parsed.windows[0].percent_used == 100.0
    assert parsed.windows[0].percent_remaining == 0.0

    with pytest.raises(GrokCreditsError, match="missing config"):
        normalize_grok_consumer_payload(b"")
    with pytest.raises(GrokCreditsError, match="no windows"):
        normalize_grok_consumer_payload(_message(1, b""))


def test_parser_rejects_a_prepaid_balance_past_the_safe_integer() -> None:
    prepaid = _field_varint(1, 9007199254740992)
    config = _float(1, 1.0) + _message(12, prepaid)
    with pytest.raises(GrokCreditsError, match="safe integer"):
        normalize_grok_consumer_payload(_message(1, config), now=_NOW)


def test_grpc_web_text_joins_padded_chunks_before_reading_the_trailer() -> None:
    payload = _message(1, _weekly_config())
    data = b"\x00" + len(payload).to_bytes(4, "big") + payload
    trailer = b"grpc-status: 8\r\ngrpc-message: free-usage-exhausted\r\nx: yy\r\n"
    trailer_frame = b"\x80" + len(trailer).to_bytes(4, "big") + trailer
    data_text = base64.b64encode(data).decode("ascii")
    trailer_text = base64.b64encode(trailer_frame).decode("ascii")
    assert data_text.endswith("=") or trailer_text.endswith("=")

    with pytest.raises(GrokCreditsRateLimit) as limited:
        decode_grpc_web_body(data_text + trailer_text)
    assert limited.value.kind == XAI_LIMIT_FREE_USAGE


def test_grpc_web_text_returns_the_data_frame_and_maps_status_8() -> None:
    payload = _message(1, _weekly_config())
    assert decode_grpc_web_body(_grpc_text(payload, trailer=b"grpc-status: 0\r\n")) == payload

    with pytest.raises(GrokCreditsRateLimit) as limited:
        decode_grpc_web_body(_grpc_text(payload, trailer=b"grpc-status: 8\r\ngrpc-message: free-usage-exhausted\r\n"))
    assert limited.value.kind == XAI_LIMIT_FREE_USAGE

    compressed = b"\x01" + len(payload).to_bytes(4, "big") + payload
    with pytest.raises(GrokCreditsError, match="compressed"):
        decode_grpc_web_body(base64.b64encode(compressed).decode("ascii"))


@pytest.mark.parametrize(
    ("body", "kind"),
    [
        ('{"code":"free-usage-exhausted"}', XAI_LIMIT_FREE_USAGE),
        ('{"error":{"message":"included free usage is gone"}}', XAI_LIMIT_FREE_USAGE),
        ('{"error":"slow down"}', XAI_LIMIT_BACKOFF),
        ("not-json", XAI_LIMIT_BACKOFF),
    ],
)
def test_classify_xai_429(body: str, kind: str) -> None:
    assert classify_xai_429(body) == kind


class _Api:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    async def api_call(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.mark.asyncio
async def test_fetch_rejects_an_unusable_credential_before_the_passthrough() -> None:
    client = _Api(_grpc_text(_message(1, _weekly_config())))

    with pytest.raises(GrokCreditsUnavailable, match="not usable"):
        await fetch_grok_credits(client, "x1", credential_usable=False, now=_NOW)
    with pytest.raises(GrokCreditsUnavailable, match="not usable"):
        await fetch_grok_credits(client, "  ", credential_usable=True, now=_NOW)

    assert client.calls == []


@pytest.mark.asyncio
async def test_fetch_posts_token_marker_and_parses_grpc_web_text() -> None:
    client = _Api(_grpc_text(_message(1, _weekly_config())))

    parsed = await fetch_grok_credits(client, "x1", credential_usable=True, now=_NOW)

    call = client.calls[0]
    assert call["auth_index"] == "x1"
    assert call["method"] == "POST"
    assert call["url"] == "https://grok.com/grok_api_v2.GrokBuildBilling/GetGrokCreditsConfig"
    header = call["header"]
    assert isinstance(header, dict)
    assert header["Authorization"] == "Bearer $TOKEN$"
    assert "$TOKEN$" in header["Authorization"]
    assert "secret" not in json.dumps(header)
    assert call["decode_json"] is False
    assert parsed.windows[0].percent_remaining == pytest.approx(62.5)


@pytest.mark.asyncio
async def test_fetch_maps_passthrough_429_and_transport_errors() -> None:
    limited = _Api(ClaudeSidecarError(429, "limited", body='{"code":"free-usage-exhausted","token":"secret"}'))
    with pytest.raises(GrokCreditsRateLimit) as exc:
        await fetch_grok_credits(limited, "x1", credential_usable=True, now=_NOW)
    assert exc.value.kind == XAI_LIMIT_FREE_USAGE
    assert "secret" not in str(exc.value)

    down = _Api(ClaudeSidecarUnavailableError("connection refused"))
    with pytest.raises(GrokCreditsUnavailable):
        await fetch_grok_credits(down, "x1", credential_usable=True, now=_NOW)


class _StalledApi:
    async def api_call(
        self,
        *,
        auth_index: str,
        method: str,
        url: str,
        header: Mapping[str, str],
        data: str | None = None,
        decode_json: bool = True,
    ) -> JsonValue:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


@pytest.mark.asyncio
async def test_fetch_gives_up_on_a_stalled_passthrough_after_its_own_timeout(monkeypatch) -> None:
    monkeypatch.setattr(grok_credits_module, "GROK_CREDITS_TIMEOUT_SECONDS", 0.05)

    with pytest.raises(GrokCreditsUnavailable, match="timed out"):
        await fetch_grok_credits(_StalledApi(), "x1", credential_usable=True, now=_NOW)


def test_usage_queue_rollup_keeps_free_usage_and_drops_the_raw_body() -> None:
    take_xai_usage_observations()
    secret = "raw-429-body-must-not-be-stored"
    note_xai_usage_queue(
        [
            {
                "provider": "claude",
                "auth_index": "c1",
                "timestamp": "2026-10-16T08:00:00Z",
                "tokens": {"input_tokens": 99, "total_tokens": 99},
                "fail": {"status_code": 429, "body": secret},
            },
            {
                "provider": "xai",
                "auth_index": "x1",
                "timestamp": "2026-10-16T09:00:00Z",
                "tokens": {
                    "input_tokens": 10,
                    "output_tokens": 4,
                    "reasoning_tokens": 1,
                    "cached_tokens": 2,
                    "total_tokens": 17,
                },
                "fail": {
                    "status_code": 429,
                    "body": json.dumps({"code": "free-usage-exhausted", "detail": secret}),
                },
            },
            {
                "provider": "xai",
                "auth_index": "x1",
                "timestamp": "2026-10-11T09:00:00Z",
                "tokens": {"input_tokens": 1000, "total_tokens": 1000},
            },
        ]
    )
    observations = take_xai_usage_observations()
    assert len(observations) == 2
    assert observations[0].fail_body == XAI_LIMIT_FREE_USAGE
    assert secret not in (observations[0].fail_body or "")

    credits = GrokCreditsQuota(
        windows=(
            GrokCreditWindow(
                id="credits",
                label="week",
                kind="weekly",
                percent_used=10.0,
                percent_remaining=90.0,
                starts_at=_START,
                resets_at=_RESET,
            ),
        ),
        observed_limit=XAI_LIMIT_FREE_USAGE,
        token_rollup=GrokTokenRollup(input_tokens=1, total_tokens=1, request_count=1, window_start=_START),
    )
    backoff = type(observations[0])(
        provider="xai",
        auth_index="x1",
        input_tokens=3,
        output_tokens=0,
        reasoning_tokens=0,
        cached_tokens=0,
        total_tokens=3,
        timestamp=_NOW,
        fail_status_code=429,
        fail_body=XAI_LIMIT_BACKOFF,
    )
    snapshot = SidecarQuotaSnapshot(
        checked_at=_NOW,
        status="healthy",
        message=None,
        accounts=(_account("claude", "c1"), _account("xai", "x1", credits=credits)),
    )
    projected = project_xai_usage(snapshot, (*observations, backoff))
    assert projected.accounts[0] == snapshot.accounts[0]
    rolled = projected.accounts[1].grok_credits
    assert rolled is not None
    assert rolled.observed_limit == XAI_LIMIT_FREE_USAGE
    assert rolled.token_rollup is not None
    assert rolled.token_rollup.input_tokens == 14
    assert rolled.token_rollup.request_count == 3
    assert rolled.token_rollup.total_tokens == 21


def test_taken_usage_is_not_replayed_by_a_later_poll() -> None:
    """A 429 from the usage queue reaches one poll only, so it holds once."""

    take_xai_usage_observations()
    note_xai_usage_queue(
        [
            {
                "provider": "xai",
                "auth_index": "x1",
                "timestamp": "2026-10-16T09:00:00Z",
                "tokens": {"total_tokens": 1},
                "fail": {"status_code": 429, "body": "free-usage-exhausted"},
            }
        ]
    )
    [observation] = take_xai_usage_observations()
    assert observation.fail_body == XAI_LIMIT_FREE_USAGE
    assert take_xai_usage_observations() == ()


def test_claude_snapshot_drops_xai_rows_and_omits_observed_limit() -> None:
    credits = GrokCreditsQuota(
        windows=(
            GrokCreditWindow(
                id="credits",
                label="week",
                kind="weekly",
                percent_used=1.0,
                percent_remaining=99.0,
                resets_at=_RESET,
            ),
        ),
        observed_limit=XAI_LIMIT_FREE_USAGE,
        prepaid_credits=7,
    )
    snapshot = SidecarQuotaSnapshot(
        checked_at=_NOW,
        status="healthy",
        message=None,
        accounts=(_account("claude", "c1"), _account("xai", "x1", credits=credits)),
    )
    claude_only = claude_quota_snapshot(snapshot)
    assert [account.provider for account in claude_only.accounts] == ["claude"]
    raw = snapshot_to_json(snapshot)
    assert "observed_limit" not in raw
    assert "secret" not in raw
    loaded = snapshot_from_json(raw)
    assert loaded is not None
    stored = loaded.accounts[1].grok_credits
    assert stored is not None
    assert stored.observed_limit is None
    assert stored.prepaid_credits == 7
    assert stored.windows[0].percent_remaining == 99.0
