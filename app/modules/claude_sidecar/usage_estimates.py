from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from app.modules.claude_sidecar.quota import SidecarQuotaSnapshot
from app.modules.settings.service import ClaudeSidecarAuthPlanData

PRIMARY_WINDOW = timedelta(hours=5)
SECONDARY_WINDOW = timedelta(days=7)
PRIMARY_WINDOW_MINUTES = 300
SECONDARY_WINDOW_MINUTES = 10_080


@dataclass(frozen=True, slots=True)
class ClaudeSidecarPlanPreset:
    plan_type: str
    primary_token_budget: int
    secondary_token_budget: int


PLAN_PRESETS: dict[str, ClaudeSidecarPlanPreset] = {
    "pro": ClaudeSidecarPlanPreset("pro", primary_token_budget=40_000, secondary_token_budget=280_000),
    "max5": ClaudeSidecarPlanPreset("max5", primary_token_budget=88_000, secondary_token_budget=616_000),
    "max20": ClaudeSidecarPlanPreset("max20", primary_token_budget=352_000, secondary_token_budget=2_464_000),
}


class UsageEventLike(Protocol):
    timestamp: datetime
    auth_index: str | None
    source: str | None
    total_tokens: int
    failed: bool


@dataclass(frozen=True, slots=True)
class ClaudeAuthUsageEstimate:
    auth_index: str | None
    email: str | None
    source: str | None
    plan_type: str | None
    usage_source: str
    primary_remaining_percent: float | None
    secondary_remaining_percent: float | None
    primary_used_tokens: int
    secondary_used_tokens: int
    primary_token_budget: int | None
    secondary_token_budget: int | None
    reset_at_primary: datetime | None
    reset_at_secondary: datetime | None
    confidence: str


@dataclass(frozen=True, slots=True)
class ClaudeAggregateUsageEstimate:
    primary_remaining_percent: float | None
    secondary_remaining_percent: float | None
    primary_used_tokens: int
    secondary_used_tokens: int
    primary_token_budget: int | None
    secondary_token_budget: int | None
    reset_at_primary: datetime | None
    reset_at_secondary: datetime | None
    confidence: str


@dataclass(frozen=True, slots=True)
class ClaudeUsageEstimates:
    accounts: list[ClaudeAuthUsageEstimate]
    aggregate: ClaudeAggregateUsageEstimate


def build_claude_usage_estimates(
    *,
    events: Sequence[UsageEventLike],
    plans: Sequence[ClaudeSidecarAuthPlanData],
    snapshot: SidecarQuotaSnapshot | None,
    now: datetime | None = None,
) -> ClaudeUsageEstimates:
    reference_time = _utc(now or datetime.now(timezone.utc))
    events_by_key: dict[str, list[UsageEventLike]] = {}
    for event in events:
        key = _event_key(event)
        if key is not None:
            events_by_key.setdefault(key, []).append(event)

    plans_by_key = {_plan_key(plan): plan for plan in plans if _plan_key(plan) is not None}
    auths_by_key: dict[str, tuple[str | None, str | None]] = {}
    exceeded_keys: set[str] = set()
    recover_at_by_key: dict[str, datetime] = {}
    if snapshot is not None:
        for auth in snapshot.accounts:
            key = _identity_key(auth.auth_index, auth.email or auth.name)
            if key is None:
                continue
            auths_by_key[key] = (auth.auth_index, auth.email)
            if auth.quota_exceeded:
                exceeded_keys.add(key)
                if auth.next_recover_at is not None:
                    recover_at_by_key[key] = _utc(auth.next_recover_at)

    keys = sorted(set(events_by_key) | set(plans_by_key) | set(auths_by_key))
    estimates: list[ClaudeAuthUsageEstimate] = []
    for key in keys:
        plan = plans_by_key.get(key)
        auth_index, email = auths_by_key.get(key, _split_key(key))
        source = _source_for_key(key, events_by_key.get(key, []), plan)
        primary_budget, secondary_budget, plan_type = _budgets_for_plan(plan)
        auth_events = sorted(events_by_key.get(key, []), key=lambda event: _utc(event.timestamp))
        primary_start = _active_window_start(auth_events, PRIMARY_WINDOW, reference_time)
        secondary_start = _active_window_start(auth_events, SECONDARY_WINDOW, reference_time)
        primary_reset = primary_start + PRIMARY_WINDOW if primary_start else None
        secondary_reset = secondary_start + SECONDARY_WINDOW if secondary_start else None
        primary_used = _used_tokens(auth_events, primary_start, primary_reset)
        secondary_used = _used_tokens(auth_events, secondary_start, secondary_reset)
        primary_remaining = _remaining_percent(primary_used, primary_budget)
        secondary_remaining = _remaining_percent(secondary_used, secondary_budget)
        if key in exceeded_keys:
            primary_remaining = 0.0
            if key in recover_at_by_key:
                primary_reset = recover_at_by_key[key]
        confidence = "estimated" if primary_budget or secondary_budget else "unknown"
        estimates.append(
            ClaudeAuthUsageEstimate(
                auth_index=auth_index,
                email=email,
                source=source,
                plan_type=plan_type,
                usage_source="usage_queue",
                primary_remaining_percent=primary_remaining,
                secondary_remaining_percent=secondary_remaining,
                primary_used_tokens=primary_used,
                secondary_used_tokens=secondary_used,
                primary_token_budget=primary_budget,
                secondary_token_budget=secondary_budget,
                reset_at_primary=primary_reset,
                reset_at_secondary=secondary_reset,
                confidence=confidence,
            )
        )
    return ClaudeUsageEstimates(accounts=estimates, aggregate=_aggregate(estimates))


def _budgets_for_plan(plan: ClaudeSidecarAuthPlanData | None) -> tuple[int | None, int | None, str | None]:
    if plan is None:
        return None, None, None
    preset = PLAN_PRESETS.get(plan.plan_type)
    primary_budget = plan.primary_token_budget or (preset.primary_token_budget if preset else None)
    secondary_budget = plan.secondary_token_budget or (preset.secondary_token_budget if preset else None)
    return primary_budget, secondary_budget, plan.plan_type


def _active_window_start(
    events: Sequence[UsageEventLike],
    window: timedelta,
    now: datetime,
) -> datetime | None:
    start: datetime | None = None
    for event in events:
        if event.failed:
            continue
        timestamp = _utc(event.timestamp)
        if timestamp > now:
            continue
        if start is None or timestamp >= start + window:
            start = timestamp
    if start is None or now >= start + window:
        return None
    return start


def _used_tokens(
    events: Sequence[UsageEventLike],
    window_start: datetime | None,
    window_end: datetime | None,
) -> int:
    if window_start is None or window_end is None:
        return 0
    return sum(
        max(0, int(event.total_tokens))
        for event in events
        if window_start <= _utc(event.timestamp) < window_end
    )


def _remaining_percent(used_tokens: int, budget_tokens: int | None) -> float | None:
    if budget_tokens is None:
        return None
    return max(0.0, 100.0 - (used_tokens / budget_tokens * 100.0))


def _aggregate(estimates: Sequence[ClaudeAuthUsageEstimate]) -> ClaudeAggregateUsageEstimate:
    primary_budget = sum(estimate.primary_token_budget or 0 for estimate in estimates)
    secondary_budget = sum(estimate.secondary_token_budget or 0 for estimate in estimates)
    primary_used = sum(estimate.primary_used_tokens for estimate in estimates if estimate.primary_token_budget)
    secondary_used = sum(estimate.secondary_used_tokens for estimate in estimates if estimate.secondary_token_budget)
    return ClaudeAggregateUsageEstimate(
        primary_remaining_percent=_remaining_percent(primary_used, primary_budget) if primary_budget else None,
        secondary_remaining_percent=(
            _remaining_percent(secondary_used, secondary_budget) if secondary_budget else None
        ),
        primary_used_tokens=primary_used,
        secondary_used_tokens=secondary_used,
        primary_token_budget=primary_budget or None,
        secondary_token_budget=secondary_budget or None,
        reset_at_primary=_earliest(estimate.reset_at_primary for estimate in estimates),
        reset_at_secondary=_earliest(estimate.reset_at_secondary for estimate in estimates),
        confidence="estimated" if primary_budget or secondary_budget else "unknown",
    )


def _event_key(event: UsageEventLike) -> str | None:
    return _identity_key(event.auth_index, event.source)


def _plan_key(plan: ClaudeSidecarAuthPlanData) -> str | None:
    return _identity_key(plan.auth_index, plan.email or plan.source)


def _identity_key(auth_index: str | None, fallback: str | None) -> str | None:
    if auth_index:
        return f"auth:{auth_index}"
    if fallback:
        return f"source:{fallback.lower()}"
    return None


def _split_key(key: str) -> tuple[str | None, str | None]:
    if key.startswith("auth:"):
        return key.removeprefix("auth:"), None
    if key.startswith("source:"):
        return None, key.removeprefix("source:")
    return None, None


def _source_for_key(
    key: str,
    events: Sequence[UsageEventLike],
    plan: ClaudeSidecarAuthPlanData | None,
) -> str | None:
    if plan and plan.source:
        return plan.source
    if plan and plan.email:
        return plan.email
    for event in events:
        if event.source:
            return event.source
    if key.startswith("source:"):
        return key.removeprefix("source:")
    return None


def _earliest(values) -> datetime | None:
    candidates = [_utc(value) for value in values if value is not None]
    return min(candidates) if candidates else None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
