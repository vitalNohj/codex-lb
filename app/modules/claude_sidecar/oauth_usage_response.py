from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.modules.claude_sidecar.usage_estimates import ClaudeAggregateUsageEstimate


def utilization_from_remaining(remaining_percent: float | None) -> float | None:
    if remaining_percent is None:
        return None
    return round(max(0.0, min(100.0, 100.0 - float(remaining_percent))), 1)


def build_anthropic_oauth_usage_payload(
    aggregate: ClaudeAggregateUsageEstimate | None,
) -> dict[str, Any]:
    """Map a pooled Claude estimate to Anthropic ``/api/oauth/usage`` JSON."""
    if aggregate is None:
        return _empty_payload()
    return {
        "five_hour": _bucket(aggregate.primary_remaining_percent, aggregate.reset_at_primary),
        "seven_day": _bucket(aggregate.secondary_remaining_percent, aggregate.reset_at_secondary),
        "seven_day_opus": None,
        "seven_day_sonnet": None,
        "extra_usage": None,
    }


def _empty_payload() -> dict[str, Any]:
    return {
        "five_hour": None,
        "seven_day": None,
        "seven_day_opus": None,
        "seven_day_sonnet": None,
        "extra_usage": None,
    }


def _bucket(remaining_percent: float | None, resets_at: datetime | None) -> dict[str, Any] | None:
    utilization = utilization_from_remaining(remaining_percent)
    if utilization is None:
        return None
    return {
        "utilization": utilization,
        "resets_at": _format_resets_at(resets_at),
    }


def _format_resets_at(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat().replace("+00:00", "Z")
