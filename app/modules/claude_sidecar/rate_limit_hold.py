"""Decide when a CLIProxyAPI Claude auth stays out of rotation.

The quota poll already knows each usage window's remaining percent and reset
time. This module turns that into a disable-until-reset plan. It does not
talk to CLIProxyAPI.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

from app.modules.claude_sidecar.quota import (
    SidecarAuthQuota,
    SidecarOAuthUsageBucket,
    SidecarRateLimitHold,
    credential_provider,
)

# CLIProxyAPI's free-tier hint: "Usage resets over a rolling 24-hour window".
XAI_LIMIT_FREE_USAGE = "free-usage-exhausted"
XAI_LIMIT_BACKOFF = "backoff"
XAI_FREE_USAGE_HOLD = timedelta(hours=24)
# Conductor quota backoff: 1s, 2s, 4s, ... capped at 30 minutes.
XAI_BACKOFF_BASE = timedelta(seconds=1)
XAI_BACKOFF_MAX = timedelta(minutes=30)


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

    Only Claude accounts and Claude holds are planned. xAI holds stay with
    :func:`plan_xai_rate_limit_holds`.
    """
    accounts = [account for account in accounts if credential_provider(account.provider) == "claude"]
    existing_holds = [hold for hold in existing_holds if credential_provider(hold.provider) == "claude"]
    holds: list[SidecarRateLimitHold] = []
    disables: list[str] = []
    enables: list[str] = []
    seen: set[str] = set()
    for account in accounts:
        if not account.name or account.name in seen:
            continue
        seen.add(account.name)
        until = rate_limit_hold_until(account, now)
        owned = _unreleased(existing_holds, account.name)
        if until is not None:
            if _released_for(existing_holds, account.name, until):
                holds.append(SidecarRateLimitHold(name=account.name, until=until, released=True))
                continue
            if account.disabled and owned is None:
                continue
            holds.append(SidecarRateLimitHold(name=account.name, until=until, released=False))
            if not account.disabled:
                disables.append(account.name)
            continue
        if owned is not None and account.oauth_usage is None and _as_utc(owned.until) > _as_utc(now):
            holds.append(owned)
            continue
        if owned is not None and account.disabled:
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
    provider: str = "claude",
) -> tuple[tuple[SidecarAuthQuota, ...], tuple[SidecarRateLimitHold, ...]]:
    """Commit only the disabled-field updates that succeeded.

    A failed update keeps the previous hold for that auth, or no hold when
    there was none, so the next poll retries the same transition. Holds for
    every other provider are copied through unchanged.
    """
    scoped_provider = credential_provider(provider)
    other_holds = tuple(hold for hold in existing_holds if credential_provider(hold.provider) != scoped_provider)
    scoped_accounts = tuple(account for account in accounts if credential_provider(account.provider) == scoped_provider)
    scoped_existing = tuple(hold for hold in existing_holds if credential_provider(hold.provider) == scoped_provider)
    updated_scoped, scoped_holds = _apply_scoped_hold_results(
        scoped_accounts,
        scoped_existing,
        plan,
        failed_disables=failed_disables,
        failed_enables=failed_enables,
    )
    updated_by_name = {account.name: account for account in updated_scoped if account.name}
    merged: list[SidecarAuthQuota] = []
    for account in accounts:
        if credential_provider(account.provider) == scoped_provider and account.name in updated_by_name:
            merged.append(updated_by_name[account.name])
        else:
            merged.append(account)
    return tuple(merged), scoped_holds + other_holds


def _apply_scoped_hold_results(
    accounts: Sequence[SidecarAuthQuota],
    existing_holds: Sequence[SidecarRateLimitHold],
    plan: RateLimitHoldPlan,
    *,
    failed_disables: set[str],
    failed_enables: set[str],
) -> tuple[tuple[SidecarAuthQuota, ...], tuple[SidecarRateLimitHold, ...]]:
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
    for hold in existing_holds:
        if hold.name and hold.name not in seen:
            holds.append(hold)
    return tuple(updated_accounts), tuple(holds)


def holds_after_operator_change(
    holds: Sequence[SidecarRateLimitHold],
    name: str,
    paused: bool,
    account: SidecarAuthQuota | None,
    now: datetime,
) -> tuple[SidecarRateLimitHold, ...]:
    """Pause drops any owned hold. Resume releases the current deadline.

    A pause with a surviving unreleased hold would be enabled again once the
    window cleared. A resume with no usage reading releases the stored reset
    so the next poll does not disable that auth again.
    """
    if not name:
        return tuple(holds)
    kept = tuple(hold for hold in holds if hold.name != name)
    if paused:
        return kept
    owned = _unreleased(holds, name, provider=None)
    if account is None or credential_provider(account.provider) != "claude" or account.oauth_usage is None:
        if owned is None:
            return kept
        return kept + (_released_copy(owned),)
    until = rate_limit_hold_until(account, now)
    if until is None:
        return kept
    return kept + (
        SidecarRateLimitHold(
            name=name,
            until=until,
            released=True,
            provider=credential_provider(account.provider),
        ),
    )


def xai_hold_deadline(kind: str, now: datetime, backoff_level: int) -> tuple[datetime, int]:
    """Return ``(until, next_backoff_level)`` for one xAI 429 observation."""

    now_utc = _as_utc(now)
    if kind == XAI_LIMIT_FREE_USAGE:
        return now_utc + XAI_FREE_USAGE_HOLD, 0
    level = backoff_level if backoff_level > 0 else 0
    if level > 30:
        level = 30
    cooldown = XAI_BACKOFF_BASE * (1 << level)
    if cooldown >= XAI_BACKOFF_MAX:
        return now_utc + XAI_BACKOFF_MAX, level
    return now_utc + cooldown, level + 1


def plan_xai_rate_limit_holds(
    accounts: Sequence[SidecarAuthQuota],
    existing_holds: Sequence[SidecarRateLimitHold],
    now: datetime,
) -> RateLimitHoldPlan:
    """Plan disable and enable calls for xAI credentials only.

    ``free-usage-exhausted`` holds the credential for 24 hours. Any other 429
    uses conductor's exponential backoff. A released hold still inside its
    deadline is not disabled again. Claude accounts are ignored.
    """

    holds: list[SidecarRateLimitHold] = []
    disables: list[str] = []
    enables: list[str] = []
    seen: set[str] = set()
    now_utc = _as_utc(now)
    xai_holds = tuple(hold for hold in existing_holds if credential_provider(hold.provider) == "xai")
    for account in accounts:
        if credential_provider(account.provider) != "xai" or not account.name or account.name in seen:
            continue
        seen.add(account.name)
        owned = _unreleased(xai_holds, account.name, provider="xai")
        released = _released_xai_hold(xai_holds, account.name, now_utc)
        observed = account.grok_credits.observed_limit if account.grok_credits is not None else None
        if released is not None:
            holds.append(released)
            continue
        if observed in (XAI_LIMIT_FREE_USAGE, XAI_LIMIT_BACKOFF):
            previous_level = owned.backoff_level if owned is not None and owned.kind == XAI_LIMIT_BACKOFF else 0
            if observed != XAI_LIMIT_BACKOFF:
                previous_level = 0
            until, level = xai_hold_deadline(observed, now_utc, previous_level)
            if account.disabled and owned is None:
                continue
            holds.append(
                SidecarRateLimitHold(
                    name=account.name,
                    until=until,
                    released=False,
                    provider="xai",
                    kind=observed,
                    backoff_level=level,
                )
            )
            if not account.disabled:
                disables.append(account.name)
            continue
        if owned is not None and _as_utc(owned.until) > now_utc:
            holds.append(owned)
            continue
        if owned is not None and account.disabled:
            enables.append(account.name)
    return RateLimitHoldPlan(holds=tuple(holds), disable_names=tuple(disables), enable_names=tuple(enables))


def _released_copy(hold: SidecarRateLimitHold) -> SidecarRateLimitHold:
    return SidecarRateLimitHold(
        name=hold.name,
        until=hold.until,
        released=True,
        provider=credential_provider(hold.provider),
        kind=hold.kind,
        backoff_level=hold.backoff_level,
    )


def _released_xai_hold(
    holds: Sequence[SidecarRateLimitHold],
    name: str,
    now_utc: datetime,
) -> SidecarRateLimitHold | None:
    covering = [
        hold
        for hold in holds
        if hold.name == name
        and hold.released
        and credential_provider(hold.provider) == "xai"
        and _as_utc(hold.until) > now_utc
    ]
    if not covering:
        return None
    return max(covering, key=lambda hold: _as_utc(hold.until))


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
    return any(
        hold.name == name
        and hold.released
        and credential_provider(hold.provider) == "claude"
        and _as_utc(hold.until) == until_utc
        for hold in holds
    )


def _unreleased(
    holds: Sequence[SidecarRateLimitHold],
    name: str,
    *,
    provider: str | None = "claude",
) -> SidecarRateLimitHold | None:
    for hold in holds:
        if hold.name != name or hold.released:
            continue
        if provider is not None and credential_provider(hold.provider) != provider:
            continue
        return hold
    return None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
