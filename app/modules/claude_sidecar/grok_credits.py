"""Per-credential xAI quota via CLIProxyAPI's management api-call passthrough.

The poll posts ``GetGrokCreditsConfig`` with ``$TOKEN$`` so codex-lb never
reads the credential file. CLIProxyAPI returns the upstream body as a JSON
string, and Go's JSON encoder replaces invalid UTF-8, so the request uses
grpc-web-text (base64 frames) instead of raw protobuf.

The quota poller calls this module for xAI credentials only. Claude rows pass
through every function here unchanged.
"""

from __future__ import annotations

import base64
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Protocol

from app.core.clients.claude_sidecar import ClaudeSidecarError, ClaudeSidecarUnavailableError
from app.core.types import JsonValue
from app.core.utils.json_guards import is_json_mapping
from app.modules.claude_sidecar.quota import (
    GrokCreditsQuota,
    GrokCreditWindow,
    GrokTokenRollup,
    SidecarAuthQuota,
    SidecarQuotaSnapshot,
    credential_provider,
    dashboard_auth_status,
)
from app.modules.claude_sidecar.rate_limit_hold import XAI_LIMIT_BACKOFF, XAI_LIMIT_FREE_USAGE
from app.modules.claude_sidecar.usage_queue import parse_usage_queue_record

GROK_CREDITS_URL = "https://grok.com/grok_api_v2.GrokBuildBilling/GetGrokCreditsConfig"
_RESPONSE_LIMIT_BYTES = 64 * 1024
_MAX_SAFE_INTEGER = 9007199254740991
_EMPTY_GRPC_WEB_TEXT_BODY = base64.b64encode(bytes(5)).decode("ascii")

_PRODUCT_NAMES = {
    0: ("unspecified", "Other"),
    1: ("api", "API"),
    2: ("grok_build", "Grok Build"),
    3: ("grok_plugins", "Grok Plugins"),
    4: ("chat", "Chat"),
    5: ("imagine", "Imagine"),
    6: ("voice", "Voice"),
}


class _ApiCaller(Protocol):
    async def api_call(
        self,
        *,
        auth_index: str,
        method: str,
        url: str,
        header: Mapping[str, str],
        data: str | None = None,
        decode_json: bool = True,
    ) -> JsonValue: ...


class GrokCreditsError(Exception):
    pass


class GrokCreditsUnavailable(GrokCreditsError):
    pass


class GrokCreditsRateLimit(GrokCreditsError):
    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


class _Field:
    __slots__ = ("field", "wire", "value")

    def __init__(self, field: int, wire: int, value: int | bytes) -> None:
        self.field = field
        self.wire = wire
        self.value = value


def classify_xai_429(body: str) -> str:
    """Match CLIProxyAPI's ``xaiStatusErr`` free-usage marker, else backoff."""

    code = ""
    error = ""
    try:
        import json

        parsed = json.loads(body)
    except (ValueError, TypeError):
        parsed = None
    if is_json_mapping(parsed):
        raw_code = parsed.get("code")
        raw_error = parsed.get("error")
        if isinstance(raw_code, str):
            code = raw_code.lower()
        if isinstance(raw_error, str):
            error = raw_error.lower()
        elif is_json_mapping(raw_error):
            nested = raw_error.get("code")
            message = raw_error.get("message")
            if isinstance(nested, str):
                code = f"{code} {nested.lower()}"
            if isinstance(message, str):
                error = message.lower()
    blob = f"{code} {error} {body.lower()}"
    if "free-usage-exhausted" in blob or "included free usage" in blob:
        return XAI_LIMIT_FREE_USAGE
    return XAI_LIMIT_BACKOFF


def grok_credential_usable(account: SidecarAuthQuota) -> bool:
    """Whether GetGrokCreditsConfig may be called for this auth file.

    An empty auth index has nothing to substitute. A login that needs reauth,
    or an auth CLIProxyAPI has marked unavailable outside a quota cooldown,
    must not be sent upstream. A quota cooldown also sets ``unavailable`` and
    still needs this read. A hold only sets ``disabled``, so a paused file
    stays pollable.
    """

    if not account.auth_index or not account.auth_index.strip():
        return False
    if dashboard_auth_status(account) == "reauth_required":
        return False
    return not (account.unavailable and not account.quota_exceeded and not account.disabled)


async def fetch_grok_credits(
    client: _ApiCaller,
    auth_index: str,
    *,
    credential_usable: bool,
    now: datetime | None = None,
) -> GrokCreditsQuota:
    """Fetch one credential's consumer quota through the management passthrough."""

    if not auth_index.strip() or not credential_usable:
        raise GrokCreditsUnavailable("Grok credits credential is not usable")
    try:
        raw = await client.api_call(
            auth_index=auth_index,
            method="POST",
            url=GROK_CREDITS_URL,
            header={
                "Authorization": "Bearer $TOKEN$",
                "Accept": "application/grpc-web-text",
                "Content-Type": "application/grpc-web-text",
                "Origin": "https://grok.com",
                "Referer": "https://grok.com/?_s=usage",
                "x-grpc-web": "1",
                "x-user-agent": "connect-es/2.1.1",
            },
            data=_EMPTY_GRPC_WEB_TEXT_BODY,
            decode_json=False,
        )
    except ClaudeSidecarUnavailableError as exc:
        raise GrokCreditsUnavailable("Grok credits transport failed") from exc
    except ClaudeSidecarError as exc:
        if exc.status_code == 429:
            raise GrokCreditsRateLimit(classify_xai_429(_error_text(exc.body))) from exc
        raise GrokCreditsError("Grok credits request failed") from exc
    if not isinstance(raw, str):
        raise GrokCreditsError("Grok credits response was not text")
    payload = decode_grpc_web_body(raw)
    return normalize_grok_consumer_payload(payload, now=now)


def normalize_grok_consumer_payload(payload: bytes, *, now: datetime | None = None) -> GrokCreditsQuota:
    """Port of quota-axi ``normalizeGrokConsumerPayload``."""

    response = _scan_message(payload)
    config = _first_message(response, 1)
    if config is None:
        raise GrokCreditsError("Grok credits payload missing config")
    current_period = _first_message(config, 8)
    period_type = _period_type(current_period) if current_period is not None else "unspecified"
    period_start = _timestamp_at(current_period, 2) if current_period is not None else None
    resets_at = _timestamp_at(current_period, 3) if current_period is not None else None
    valid_current_period = period_type in {"weekly", "monthly"} and period_start is not None and resets_at is not None
    window_kind = period_type if period_type in {"weekly", "monthly"} else "credits"
    window_label = {"weekly": "week", "monthly": "month"}.get(period_type, "credits")
    windows: list[GrokCreditWindow] = []
    shared_explicit = _float_at(config, 1)
    if shared_explicit is not None or valid_current_period:
        percent_used = _clamp_percent(0.0 if shared_explicit is None else shared_explicit)
        windows.append(
            GrokCreditWindow(
                id="credits",
                label=window_label,
                kind=window_kind,
                percent_used=percent_used,
                percent_remaining=100.0 - percent_used,
                starts_at=period_start,
                resets_at=resets_at,
            )
        )
    for product_payload in _messages_at(config, 7):
        product = _scan_message(product_payload)
        explicit = _float_at(product, 2)
        if explicit is None and not valid_current_period:
            continue
        product_number = _safe_number(_varint_at(product, 1) if _varint_at(product, 1) is not None else 0)
        if product_number is None:
            continue
        product_id, product_label = _PRODUCT_NAMES.get(
            product_number,
            (f"unknown_{product_number}", f"Product {product_number}"),
        )
        percent_used = _clamp_percent(0.0 if explicit is None else explicit)
        windows.append(
            GrokCreditWindow(
                id=f"product:{product_id}",
                label=product_label,
                kind=window_kind,
                percent_used=percent_used,
                percent_remaining=100.0 - percent_used,
                starts_at=period_start,
                resets_at=resets_at,
            )
        )
    if not windows:
        raise GrokCreditsError("Grok credits payload had no windows")
    prepaid = _first_message(config, 12)
    prepaid_balance: int | None = None
    if prepaid is not None:
        raw_balance = _varint_at(prepaid, 1)
        parsed_balance = _safe_number(0 if raw_balance is None else raw_balance)
        if parsed_balance is None:
            raise GrokCreditsError("Grok prepaid balance was not a safe integer")
        prepaid_balance = parsed_balance
    refreshed_at = now or datetime.now(timezone.utc)
    if refreshed_at.tzinfo is None:
        refreshed_at = refreshed_at.replace(tzinfo=timezone.utc)
    return GrokCreditsQuota(
        windows=tuple(windows),
        prepaid_credits=prepaid_balance,
        refreshed_at=refreshed_at.astimezone(timezone.utc),
    )


def decode_grpc_web_body(body: str) -> bytes:
    """Decode a grpc-web-text body to the single protobuf data frame."""

    decoded = _decode_grpc_web_text(body)
    if len(decoded) > _RESPONSE_LIMIT_BYTES:
        raise GrokCreditsError("Grok credits body was too large")
    if not decoded or not _looks_framed(decoded[0]):
        return decoded
    data_frames: list[bytes] = []
    trailer_seen = False
    index = 0
    while index < len(decoded):
        if index + 5 > len(decoded):
            raise GrokCreditsError("Grok credits frame was truncated")
        flags = decoded[index]
        if flags & 0x01:
            raise GrokCreditsError("Grok credits frame was compressed")
        if flags not in (0, 0x80):
            raise GrokCreditsError("Grok credits frame flags were invalid")
        length = int.from_bytes(decoded[index + 1 : index + 5], "big")
        if length > _RESPONSE_LIMIT_BYTES:
            raise GrokCreditsError("Grok credits frame was too large")
        start = index + 5
        end = start + length
        if end > len(decoded):
            raise GrokCreditsError("Grok credits frame length overran the body")
        frame = decoded[start:end]
        if flags == 0x80:
            if trailer_seen:
                raise GrokCreditsError("Grok credits body had two trailers")
            trailer_seen = True
            trailers = _trailer_fields(frame)
            _throw_for_grpc_status(trailers.get("grpc-status"), trailers.get("grpc-message"))
        else:
            if trailer_seen or data_frames:
                raise GrokCreditsError("Grok credits body had an unexpected data frame")
            data_frames.append(frame)
        index = end
    if len(data_frames) != 1:
        raise GrokCreditsError("Grok credits body did not contain one data frame")
    return data_frames[0]


class _UsageEvent(Protocol):
    provider: str | None
    auth_index: str | None
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    cached_tokens: int
    total_tokens: int
    timestamp: datetime
    fail_status_code: int | None
    fail_body: str | None


def project_xai_usage(
    snapshot: SidecarQuotaSnapshot,
    records: Sequence[_UsageEvent],
) -> SidecarQuotaSnapshot:
    """Fold xAI usage-queue rows into quota windows and a fresh 429 observation.

    Claude accounts are copied unchanged. ``observed_limit`` is left set so the
    hold planner can see this batch; persistence strips it.
    """

    xai_records = [record for record in records if (record.provider or "").strip().lower() == "xai"]
    if not xai_records:
        return snapshot
    by_index: dict[str, list[_UsageEvent]] = {}
    for record in xai_records:
        if record.auth_index:
            by_index.setdefault(record.auth_index, []).append(record)
    accounts: list[SidecarAuthQuota] = []
    for account in snapshot.accounts:
        if credential_provider(account.provider) != "xai" or not account.auth_index:
            accounts.append(account)
            continue
        events = by_index.get(account.auth_index, [])
        if not events:
            accounts.append(account)
            continue
        credits = account.grok_credits or GrokCreditsQuota()
        credits = replace(credits, token_rollup=_merge_rollup(credits, events))
        limit = _prefer_limit(credits.observed_limit, _limit_kind(events))
        if limit is not None:
            credits = replace(credits, observed_limit=limit)
        accounts.append(replace(account, grok_credits=credits))
    return replace(snapshot, accounts=tuple(accounts))


@dataclass(frozen=True, slots=True)
class XaiUsageObservation:
    """One xAI usage-queue row, with the 429 body reduced to a hold kind."""

    provider: str
    auth_index: str
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    cached_tokens: int
    total_tokens: int
    timestamp: datetime
    fail_status_code: int | None
    fail_body: str | None


_pending_usage: list[XaiUsageObservation] = []


def note_xai_usage_queue(raw_records: Sequence[Mapping[str, JsonValue]]) -> None:
    """Remember xAI usage-queue rows until the quota poll folds them in.

    The raw 429 body is classified immediately and dropped, so a credential
    error never sits in the pending list. Claude rows are ignored.
    """

    for raw in raw_records:
        if not is_json_mapping(raw):
            continue
        provider = raw.get("provider")
        if not isinstance(provider, str) or provider.strip().lower() != "xai":
            continue
        parsed = parse_usage_queue_record(raw)
        if parsed is None or not parsed.auth_index:
            continue
        status_code, kind = _queue_limit(raw.get("fail"))
        _pending_usage.append(
            XaiUsageObservation(
                provider="xai",
                auth_index=parsed.auth_index,
                input_tokens=parsed.input_tokens,
                output_tokens=parsed.output_tokens,
                reasoning_tokens=parsed.reasoning_tokens,
                cached_tokens=parsed.cached_tokens,
                total_tokens=parsed.total_tokens,
                timestamp=parsed.timestamp,
                fail_status_code=status_code,
                fail_body=kind,
            )
        )


def take_xai_usage_observations() -> tuple[XaiUsageObservation, ...]:
    """Remove and return pending xAI usage rows."""

    pending = tuple(_pending_usage)
    _pending_usage.clear()
    return pending


def restore_xai_usage_observations(observations: Sequence[XaiUsageObservation]) -> None:
    """Put a poll that failed to persist back at the front of the pending list."""

    if not observations:
        return
    _pending_usage[:0] = list(observations)


def _queue_limit(fail: JsonValue) -> tuple[int | None, str | None]:
    if not is_json_mapping(fail):
        return None, None
    status_code = fail.get("status_code")
    if isinstance(status_code, bool) or not isinstance(status_code, int) or status_code != 429:
        return None, None
    body = fail.get("body")
    return 429, classify_xai_429(body if isinstance(body, str) else "")


def strip_observed_limits(accounts: Sequence[SidecarAuthQuota]) -> tuple[SidecarAuthQuota, ...]:
    """Drop the in-poll 429 flag so the stored snapshot cannot replay it."""

    stripped: list[SidecarAuthQuota] = []
    for account in accounts:
        credits = account.grok_credits
        if credits is not None and credits.observed_limit is not None:
            stripped.append(replace(account, grok_credits=replace(credits, observed_limit=None)))
        else:
            stripped.append(account)
    return tuple(stripped)


def _merge_rollup(credits: GrokCreditsQuota, events: Sequence[_UsageEvent]) -> GrokTokenRollup:
    window_start = _credits_window_start(credits)
    existing = credits.token_rollup
    if existing is not None and existing.window_start == window_start:
        base = existing
    else:
        base = GrokTokenRollup(window_start=window_start)
    counted = [event for event in events if _in_window(event.timestamp, window_start)]
    return GrokTokenRollup(
        input_tokens=base.input_tokens + sum(event.input_tokens for event in counted),
        output_tokens=base.output_tokens + sum(event.output_tokens for event in counted),
        reasoning_tokens=base.reasoning_tokens + sum(event.reasoning_tokens for event in counted),
        cached_tokens=base.cached_tokens + sum(event.cached_tokens for event in counted),
        total_tokens=base.total_tokens + sum(event.total_tokens for event in counted),
        request_count=base.request_count + len(counted),
        window_start=window_start,
    )


def _credits_window_start(credits: GrokCreditsQuota) -> datetime | None:
    for window in credits.windows:
        if window.id == "credits" and window.starts_at is not None:
            return window.starts_at
    return None


def _in_window(timestamp: datetime, window_start: datetime | None) -> bool:
    if window_start is None:
        return True
    stamp = timestamp if timestamp.tzinfo is not None else timestamp.replace(tzinfo=timezone.utc)
    start = window_start if window_start.tzinfo is not None else window_start.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc) >= start.astimezone(timezone.utc)


def _limit_kind(events: Sequence[_UsageEvent]) -> str | None:
    kind: str | None = None
    for event in events:
        if event.fail_status_code != 429:
            continue
        classified = classify_xai_429(event.fail_body or "")
        if classified == XAI_LIMIT_FREE_USAGE:
            return classified
        kind = classified
    return kind


def _prefer_limit(current: str | None, incoming: str | None) -> str | None:
    """Keep a 24 h free-usage hold when a later 429 is only backoff."""

    if current == XAI_LIMIT_FREE_USAGE or incoming == XAI_LIMIT_FREE_USAGE:
        return XAI_LIMIT_FREE_USAGE
    return incoming or current


def _error_text(body: JsonValue | None) -> str:
    if isinstance(body, str):
        return body
    if body is None:
        return ""
    import json

    try:
        return json.dumps(body)
    except TypeError:
        return ""


def _decode_grpc_web_text(body: str) -> bytes:
    """Decode grpc-web-text, including successive padded base64 chunks.

    A streamed body base64-encodes each chunk on its own, so padding can sit
    in the middle. Decoding the concatenation as one string stops at the first
    padded chunk and drops the trailer.
    """

    text = "".join(body.split())
    if not text:
        raise GrokCreditsError("Grok credits body was empty")
    decoded = bytearray()
    for start in range(0, len(text), 4):
        chunk = text[start : start + 4]
        if len(chunk) < 4:
            chunk += "=" * (4 - len(chunk))
        try:
            decoded.extend(base64.b64decode(chunk, validate=True))
        except (ValueError, TypeError) as exc:
            raise GrokCreditsError("Grok credits body was not base64") from exc
    return bytes(decoded)


def _looks_framed(first: int) -> bool:
    return first in (0, 1) or (first & 0x80) != 0


def _trailer_fields(frame: bytes) -> dict[str, str]:
    trailers: dict[str, str] = {}
    text = frame.decode("utf-8", errors="replace")
    for line in text.splitlines():
        separator = line.find(":")
        if separator <= 0:
            continue
        trailers[line[:separator].strip().lower()] = line[separator + 1 :].strip()
    return trailers


def _throw_for_grpc_status(status: str | None, message: str | None) -> None:
    if status is None:
        return
    if not status.isdigit():
        raise GrokCreditsError("Grok credits grpc-status was invalid")
    code = int(status)
    if code == 0:
        return
    if code == 8:
        raise GrokCreditsRateLimit(classify_xai_429(message or ""))
    raise GrokCreditsError("Grok credits grpc status was not OK")


def _scan_message(payload: bytes) -> list[_Field]:
    fields: list[_Field] = []
    index = 0
    length = len(payload)
    while index < length:
        key, index = _read_varint(payload, index)
        field_number = key >> 3
        if field_number <= 0 or field_number > 0x1FFFFFFF:
            raise GrokCreditsError("Grok credits field number was invalid")
        wire = key & 7
        if wire == 0:
            value, index = _read_varint(payload, index)
            fields.append(_Field(field_number, wire, value))
            continue
        if wire in (1, 5):
            size = 8 if wire == 1 else 4
            end = index + size
            if end > length:
                raise GrokCreditsError("Grok credits fixed field was truncated")
            fields.append(_Field(field_number, wire, payload[index:end]))
            index = end
            continue
        if wire == 2:
            size, index = _read_varint(payload, index)
            if size > _RESPONSE_LIMIT_BYTES:
                raise GrokCreditsError("Grok credits length field was too large")
            end = index + size
            if end > length:
                raise GrokCreditsError("Grok credits length field overran the message")
            fields.append(_Field(field_number, wire, payload[index:end]))
            index = end
            continue
        raise GrokCreditsError("Grok credits wire type was invalid")
    return fields


def _read_varint(payload: bytes, start: int) -> tuple[int, int]:
    value = 0
    index = start
    for count in range(10):
        if index >= len(payload):
            break
        byte = payload[index]
        index += 1
        if count == 9 and byte > 1:
            raise GrokCreditsError("Grok credits varint was too wide")
        value |= (byte & 0x7F) << (count * 7)
        if byte & 0x80 == 0:
            return value, index
    raise GrokCreditsError("Grok credits varint was truncated")


def _messages_at(fields: list[_Field], field: int) -> list[bytes]:
    messages: list[bytes] = []
    for entry in fields:
        if entry.field == field and entry.wire == 2 and isinstance(entry.value, bytes):
            messages.append(entry.value)
    return messages


def _first_message(fields: list[_Field], field: int) -> list[_Field] | None:
    messages = _messages_at(fields, field)
    if not messages:
        return None
    return _scan_message(messages[0])


def _varint_at(fields: list[_Field], field: int) -> int | None:
    for entry in fields:
        if entry.field == field and entry.wire == 0 and isinstance(entry.value, int):
            return entry.value
    return None


def _float_at(fields: list[_Field], field: int) -> float | None:
    for entry in fields:
        if entry.field == field and entry.wire == 5 and isinstance(entry.value, bytes):
            if len(entry.value) != 4:
                raise GrokCreditsError("Grok credits float was the wrong size")
            value = struct.unpack("<f", entry.value)[0]
            if value != value or value in (float("inf"), float("-inf")):
                raise GrokCreditsError("Grok credits float was not finite")
            return float(value)
    return None


def _timestamp_at(fields: list[_Field] | None, field: int) -> datetime | None:
    if fields is None:
        return None
    timestamp = _first_message(fields, field)
    if timestamp is None:
        return None
    seconds = _safe_number(_varint_at(timestamp, 1))
    if seconds is None:
        return None
    milliseconds = seconds * 1000
    if milliseconds > _MAX_SAFE_INTEGER:
        return None
    return datetime.fromtimestamp(seconds, tz=timezone.utc)


def _period_type(period: list[_Field]) -> str:
    value = _varint_at(period, 1)
    if value == 2:
        return "weekly"
    if value == 1:
        return "monthly"
    return "unspecified"


def _safe_number(value: int | None) -> int | None:
    if value is None or value > _MAX_SAFE_INTEGER:
        return None
    return value


def _clamp_percent(value: float) -> float:
    return min(100.0, max(0.0, value))
