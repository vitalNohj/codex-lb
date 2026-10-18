"""Quota headroom for one CLIProxyAPI credential.

The capacity router scores these states with the Codex account selector.
A credential with no measured window stays unknown and ranks behind
measured headroom. Headroom is keyed by the auth index CLIProxyAPI uses.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

from app.core.balancer.logic import AccountState
from app.db.models import AccountStatus
from app.modules.claude_sidecar.quota import (
    GrokCreditsQuota,
    GrokCreditWindow,
    SidecarAuthQuota,
    SidecarOAuthUsageBucket,
    SidecarRateLimitHold,
    credential_provider,
)
from app.modules.claude_sidecar.rate_limit_hold import XAI_FREE_USAGE_HOLD, XAI_LIMIT_FREE_USAGE

_QUOTA_SOURCES = frozenset({"codex", "claude", "xai"})
_XAI_WINDOW_KINDS = frozenset({"weekly", "monthly", "credits"})


def account_state_for_auth(
    auth: SidecarAuthQuota,
    *,
    holds: Sequence[SidecarRateLimitHold],
    now: datetime,
) -> AccountState | None:
    """Map one credential onto the quota-feed account interface.

    Real Codex window math stays on Codex ``AccountState`` rows. A
    CLIProxyAPI credential tagged ``codex`` uses OAuth buckets when the
    snapshot has them and otherwise stays unknown.
    """

    provider = credential_provider(auth.provider)
    identity = auth.auth_index.strip() if isinstance(auth.auth_index, str) and auth.auth_index.strip() else auth.name
    if not identity:
        return None
    moment = _as_utc(now)
    hold = _active_hold(auth, holds, moment)
    source = provider if provider in _QUOTA_SOURCES else "unknown"
    status, used_percent, reset_at, secondary_used, secondary_reset = _quota_fields(
        auth,
        source=source,
        hold=hold,
        now=moment,
    )
    return AccountState(
        account_id=f"cliproxy:{provider}:{identity}",
        status=status,
        used_percent=used_percent,
        reset_at=reset_at,
        secondary_used_percent=secondary_used,
        secondary_reset_at=int(secondary_reset) if secondary_reset is not None else None,
        plan_type=provider,
    )


def _quota_fields(
    auth: SidecarAuthQuota,
    *,
    source: str,
    hold: SidecarRateLimitHold | None,
    now: datetime,
) -> tuple[AccountStatus, float | None, float | None, float | None, float | None]:
    status = _status_for_auth(auth, hold)
    if source == "xai":
        used, reset_at = _xai_usage(auth.grok_credits, hold, status, now)
        return status, used, reset_at, None, None
    if source in {"claude", "codex"} and auth.oauth_usage is not None:
        primary_used, primary_reset = _used_from_bucket(auth.oauth_usage.five_hour)
        secondary_used, secondary_reset = _used_from_bucket(auth.oauth_usage.seven_day)
        if status == AccountStatus.RATE_LIMITED and hold is not None:
            return status, 100.0, _epoch(hold.until), secondary_used, secondary_reset
        return status, primary_used, primary_reset, secondary_used, secondary_reset
    if status == AccountStatus.RATE_LIMITED and hold is not None:
        return status, 100.0, _epoch(hold.until), None, None
    return status, None, None, None, None


def _status_for_auth(auth: SidecarAuthQuota, hold: SidecarRateLimitHold | None) -> AccountStatus:
    status_text = (auth.status or "").strip().lower()
    message = (auth.status_message or "").lower()
    if status_text in {"unauthorized", "reauth", "reauth_required"} or "reauth" in message:
        return AccountStatus.REAUTH_REQUIRED
    if auth.disabled or auth.unavailable:
        return AccountStatus.PAUSED
    if auth.quota_exceeded:
        return AccountStatus.QUOTA_EXCEEDED
    if _xai_free_exhausted(auth, hold) or hold is not None:
        return AccountStatus.RATE_LIMITED
    return AccountStatus.ACTIVE


def _xai_free_exhausted(auth: SidecarAuthQuota, hold: SidecarRateLimitHold | None) -> bool:
    credits = auth.grok_credits
    if credits is not None and credits.observed_limit == XAI_LIMIT_FREE_USAGE:
        return True
    return hold is not None and hold.kind == XAI_LIMIT_FREE_USAGE


def _xai_usage(
    credits: GrokCreditsQuota | None,
    hold: SidecarRateLimitHold | None,
    status: AccountStatus,
    now: datetime,
) -> tuple[float | None, float | None]:
    if status == AccountStatus.RATE_LIMITED:
        if hold is not None:
            return 100.0, _epoch(hold.until)
        return 100.0, (now + XAI_FREE_USAGE_HOLD).timestamp()
    window = _xai_window(credits)
    if window is None:
        return None, None
    return _clamp_percent(window.percent_used), _epoch(window.resets_at)


def _xai_window(credits: GrokCreditsQuota | None) -> GrokCreditWindow | None:
    if credits is None or not credits.windows:
        return None
    for window in credits.windows:
        if window.id == "credits" or window.kind in _XAI_WINDOW_KINDS:
            return window
    return credits.windows[0]


def _used_from_bucket(bucket: SidecarOAuthUsageBucket | None) -> tuple[float | None, float | None]:
    if bucket is None or bucket.remaining_percent is None:
        return None, None
    return _clamp_percent(100.0 - bucket.remaining_percent), _epoch(bucket.resets_at)


def _active_hold(
    auth: SidecarAuthQuota,
    holds: Sequence[SidecarRateLimitHold],
    now: datetime,
) -> SidecarRateLimitHold | None:
    provider = credential_provider(auth.provider)
    for hold in holds:
        if hold.released or hold.name != auth.name:
            continue
        if credential_provider(hold.provider) != provider:
            continue
        if _as_utc(hold.until) > now:
            return hold
    return None


def _clamp_percent(value: float) -> float:
    if value < 0:
        return 0.0
    if value > 100:
        return 100.0
    return value


def _epoch(moment: datetime | None) -> float | None:
    if moment is None:
        return None
    return _as_utc(moment).timestamp()


def _as_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)
