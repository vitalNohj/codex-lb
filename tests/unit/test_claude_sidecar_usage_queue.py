from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.modules.claude_sidecar.usage_queue import parse_usage_queue_record, parse_usage_queue_records

pytestmark = pytest.mark.unit


def test_parse_usage_queue_record_sanitizes_and_parses_tokens() -> None:
    record = parse_usage_queue_record(
        {
            "timestamp": "2026-05-05T12:00:00Z",
            "latency_ms": 1234,
            "source": "claude@example.com",
            "auth_index": "auth-1",
            "tokens": {
                "input_tokens": 10,
                "output_tokens": 20,
                "reasoning_tokens": 3,
                "cached_tokens": 4,
                "total_tokens": 37,
            },
            "failed": False,
            "provider": "claude",
            "model": "claude-sonnet",
            "alias": "claude",
            "endpoint": "POST /v1/chat/completions",
            "auth_type": "oauth",
            "api_key": "must-not-be-present",
            "request_id": "req_1",
        }
    )

    assert record is not None
    assert record.request_id == "req_1"
    assert record.timestamp == datetime(2026, 5, 5, 12, 0, tzinfo=timezone.utc)
    assert record.auth_index == "auth-1"
    assert record.source == "claude@example.com"
    assert record.total_tokens == 37
    assert record.cached_tokens == 4
    assert not hasattr(record, "api_key")


def test_parse_usage_queue_record_calculates_missing_total() -> None:
    record = parse_usage_queue_record(
        {
            "timestamp": "2026-05-05T12:00:00Z",
            "tokens": {
                "input_tokens": 10,
                "output_tokens": 20,
                "reasoning_tokens": 3,
                "cached_tokens": 4,
            },
        }
    )

    assert record is not None
    assert record.total_tokens == 37
    assert record.request_id.startswith("generated:")


def test_generated_request_id_ignores_api_key() -> None:
    base = {
        "timestamp": "2026-05-05T12:00:00Z",
        "tokens": {"total_tokens": 10},
        "model": "claude-sonnet",
    }

    first = parse_usage_queue_record({**base, "api_key": "one"})
    second = parse_usage_queue_record({**base, "api_key": "two"})

    assert first is not None
    assert second is not None
    assert first.request_id == second.request_id


def test_parse_usage_queue_records_skips_malformed_entries() -> None:
    records = parse_usage_queue_records(
        [
            {"timestamp": "not-a-date", "tokens": {"total_tokens": 1}},
            {"timestamp": "2026-05-05T12:00:00Z", "tokens": {"total_tokens": 2}},
        ]
    )

    assert len(records) == 1
    assert records[0].total_tokens == 2
