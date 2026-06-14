from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.db.models import RequestLog
from app.modules.request_logs.mappers import to_request_log_entry

pytestmark = pytest.mark.unit


def _log(**overrides) -> RequestLog:
    values = {
        "request_id": "req-1",
        "model": "vendor/model-x:free",
        "status": "success",
        "error_code": None,
        "requested_at": datetime(2026, 6, 14, tzinfo=timezone.utc),
        "input_tokens": 10_000,
        "output_tokens": 2_000,
        "cached_input_tokens": 0,
        "reasoning_tokens": None,
        "cost_usd": 0.0,
        "reference_cost_usd": 0.016,
        "source": "openrouter_sidecar",
        "request_kind": "normal",
    }
    values.update(overrides)
    return RequestLog(**values)


def test_savings_is_reference_minus_actual() -> None:
    entry = to_request_log_entry(_log())
    assert entry.reference_cost_usd == pytest.approx(0.016)
    # cost_usd here is computed from the cost breakdown (free model -> 0).
    assert entry.savings_usd == pytest.approx(0.016)


def test_savings_unset_when_reference_cost_missing() -> None:
    entry = to_request_log_entry(_log(reference_cost_usd=None))
    assert entry.reference_cost_usd is None
    assert entry.savings_usd is None


def test_savings_floored_at_zero() -> None:
    # Reference lower than actual cost -> no negative savings.
    entry = to_request_log_entry(_log(cost_usd=0.05, reference_cost_usd=0.01))
    assert entry.savings_usd == pytest.approx(0.0)
