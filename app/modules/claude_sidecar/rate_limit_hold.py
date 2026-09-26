"""Decide when a CLIProxyAPI Claude auth stays out of rotation.

The quota poll already knows each usage window's remaining percent and reset
time. This module turns that into a disable-until-reset plan. It does not
talk to CLIProxyAPI.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from app.modules.claude_sidecar.quota import (
    SidecarAuthQuota,
    SidecarOAuthUsageBucket,
    SidecarRateLimitHold,
)


@dataclass(frozen=True, slots=True)
class RateLimitHoldPlan:
    """Holds to store if every disabled-field update succeeds."""

    holds: tuple[SidecarRateLimitHold, ...]
    disable_names: tuple[str, ...]
    enable_names: tuple[str, ...]


def rate_limit_hold_until(account: SidecarAuthQuota, now: datetime) -> datetime | None:
    """Return the latest future reset among windows that have no remaining percent."""
    if not account.name or account.oauth_usage is None:
        return None
    now_utc = _as_utc(now)
    deadlines: list[datetime] = []
    for bucket in (account.oauth_usage.five_hour, account.oauth_usage.seven_day):
        deadline = _bucket_deadline(bucket, now_utc)
        if deadline is not None:
            deadlines.append(deadline)
    if not deadlines:
        return None
    return max(deadlines)


def plan_rate_limit_holds(
    accounts: Sequence[SidecarAuthQuota],
    existing_holds: Sequence[SidecarRateLimitHold],
    now: datetime,
) -> RateLimitHoldPlan:
    """Plan disable and enable calls for this poll.

    An auth that is already disabled, with no unreleased hold, is an operator
    pause: it is not adopted and it is not enabled later. A released hold for
    the same reset time suppresses a new disable.
    """
    holds: list[SidecarRateLimitHold] = []
    disables: list[str] = []
    enables: list[str] = []
    seen: set[str] = set()
    for account in accounts:
        if not account.name or account.name in seen:
            continue
        seen.add(account.name)
        until = rate_limit_hold_until(account, now)
        if until is not None:
            if _released_for(existing_holds, account.name, until):
                holds.append(SidecarRateLimitHold(name=account.name, until=until, released=True))
                continue
            if account.disabled and _unreleased(existing_holds, account.name) is None:
                continue
            holds.append(SidecarRateLimitHold(name=account.name, until=until, released=False))
            if not account.disabled:
                disables.append(account.name)
            continue
        if _unreleased(existing_holds, account.name) is not None and account.disabled:
            enables.append(account.name)
    return RateLimitHoldPlan(
        holds=tuple(holds),
        disable_names=tuple(disables),
        enable_names=tuple(enables),
    )


def apply_hold_results(
    accounts: Sequence[SidecarAuthQuota],
    existing_holds: Sequence[SidecarRateLimitHold],
    plan: RateLimitHoldPlan,
    *,
    failed_disables: set[str],
    failed_enables: set[str],
) -> tuple[tuple[SidecarAuthQuota, ...], tuple[SidecarRateLimitHold, ...]]:
    """Commit only the disabled-field updates that succeeded.

    A failed update keeps the previous hold for that auth, or no hold when
    there was none, so the next poll retries the same transition.
    """
    applied_disables = set(plan.disable_names) - failed_disables
    applied_enables = set(plan.enable_names) - failed_enables
    updated_accounts: list[SidecarAuthQuota] = []
    for account in accounts:
        if account.name in applied_disables:
            updated_accounts.append(replace(account, disabled=True))
        elif account.name in applied_enables:
            updated_accounts.append(replace(account, disabled=False))
        else:
            updated_accounts.append(account)

    failed = failed_disables | failed_enables
    existing_by_name = {hold.name: hold for hold in existing_holds}
    planned_by_name = {hold.name: hold for hold in plan.holds}
    holds: list[SidecarRateLimitHold] = []
    seen: set[str] = set()
    for account in accounts:
        if not account.name or account.name in seen:
            continue
        seen.add(account.name)
        if account.name in failed:
            previous = existing_by_name.get(account.name)
            if previous is not None:
                holds.append(previous)
            continue
        planned = planned_by_name.get(account.name)
        if planned is not None:
            holds.append(planned)
    return tuple(updated_accounts), tuple(holds)


def holds_after_operator_change(
    holds: Sequence[SidecarRateLimitHold],
    name: str,
    paused: bool,
    account: SidecarAuthQuota | None,
    now: datetime,
) -> tuple[SidecarRateLimitHold, ...]:
    """Pause leaves holds untouched. Resume releases the current deadline."""
    if paused or not name:
        return tuple(holds)
    kept = tuple(hold for hold in holds if hold.name != name)
    if account is None:
        return kept
    until = rate_limit_hold_until(account, now)
    if until is None:
        return kept
    return kept + (SidecarRateLimitHold(name=name, until=until, released=True),)


def _bucket_deadline(bucket: SidecarOAuthUsageBucket | None, now_utc: datetime) -> datetime | None:
    if bucket is None or bucket.remaining_percent is None or bucket.resets_at is None:
        return None
    if bucket.remaining_percent > 0:
        return None
    resets_at = _as_utc(bucket.resets_at)
    if resets_at <= now_utc:
        return None
    return resets_at


def _released_for(holds: Sequence[SidecarRateLimitHold], name: str, until: datetime) -> bool:
    until_utc = _as_utc(until)
    return any(hold.name == name and hold.released and _as_utc(hold.until) == until_utc for hold in holds)


def _unreleased(holds: Sequence[SidecarRateLimitHold], name: str) -> SidecarRateLimitHold | None:
    for hold in holds:
        if hold.name == name and not hold.released:
            return hold
    return None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
