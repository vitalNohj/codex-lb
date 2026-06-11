from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone

from app.core.types import JsonValue
from app.core.utils.json_guards import is_json_mapping


@dataclass(frozen=True, slots=True)
class ClaudeSidecarUsageRecord:
    request_id: str
    timestamp: datetime
    auth_index: str | None
    source: str | None
    provider: str | None
    model: str | None
    alias: str | None
    endpoint: str | None
    auth_type: str | None
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    cached_tokens: int
    total_tokens: int
    failed: bool
    latency_ms: int | None


def parse_usage_queue_records(raw_records: Iterable[Mapping[str, JsonValue]]) -> list[ClaudeSidecarUsageRecord]:
    records: list[ClaudeSidecarUsageRecord] = []
    for raw in raw_records:
        parsed = parse_usage_queue_record(raw)
        if parsed is not None:
            records.append(parsed)
    return records


def parse_usage_queue_record(raw: Mapping[str, JsonValue]) -> ClaudeSidecarUsageRecord | None:
    timestamp = _parse_datetime(raw.get("timestamp"))
    if timestamp is None:
        return None
    tokens = raw.get("tokens")
    if not is_json_mapping(tokens):
        tokens = {}
    input_tokens = _int(tokens.get("input_tokens")) or 0
    output_tokens = _int(tokens.get("output_tokens")) or 0
    reasoning_tokens = _int(tokens.get("reasoning_tokens")) or 0
    cached_tokens = _int(tokens.get("cached_tokens")) or 0
    total_tokens = _int(tokens.get("total_tokens"))
    if total_tokens is None:
        total_tokens = input_tokens + output_tokens + reasoning_tokens + cached_tokens
    request_id = _str(raw.get("request_id")) or _generated_request_id(raw)
    return ClaudeSidecarUsageRecord(
        request_id=request_id,
        timestamp=timestamp,
        auth_index=_str(raw.get("auth_index")),
        source=_str(raw.get("source")),
        provider=_str(raw.get("provider")),
        model=_str(raw.get("model")),
        alias=_str(raw.get("alias")),
        endpoint=_str(raw.get("endpoint")),
        auth_type=_str(raw.get("auth_type")),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        reasoning_tokens=reasoning_tokens,
        cached_tokens=cached_tokens,
        total_tokens=max(0, total_tokens),
        failed=bool(raw.get("failed")),
        latency_ms=_int(raw.get("latency_ms")),
    )


def _generated_request_id(raw: Mapping[str, JsonValue]) -> str:
    sanitized = {key: value for key, value in raw.items() if key != "api_key"}
    encoded = json.dumps(sanitized, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return f"generated:{digest}"


def _parse_datetime(value: JsonValue) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _str(value: JsonValue) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _int(value: JsonValue) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None
