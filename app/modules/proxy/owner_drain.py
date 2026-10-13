"""Classification of transient drain for required continuity owners.

A required continuity owner (previous-response owner, hard turn-state
owner, file-pin owner, ...) can be unavailable for transient reasons —
bounded error backoff after repeated transient upstream errors, or the
DRAINING/PROBING health tier — or permanently. The bounded hold for
continuity-bound follow-ups waits only on the transient case.
"""

from __future__ import annotations

import time

from app.core.balancer import (
    ERROR_BACKOFF_THRESHOLD,
    HEALTH_TIER_DRAINING,
    HEALTH_TIER_PROBING,
    AccountState,
)
from app.core.balancer.logic import DRAIN_ERROR_WINDOW_SECONDS, PROBE_QUIET_SECONDS
from app.db.models import AccountStatus
from app.modules.proxy.load_balancer import LoadBalancer, _build_states

# Transient error backoff mirrors the inner selector's math so the owner-drain
# classification agrees with what actually blocked selection.
_OWNER_TRANSIENT_BACKOFF_CAP_SECONDS = 300.0
_OWNER_TRANSIENT_BACKOFF_BASE_SECONDS = 30.0

# Owner states that are never a transient drain: the bounded hold must not
# wait on these (spec: only drained/probing owners may be waited on).
_PERMANENTLY_UNSELECTABLE_OWNER_STATUSES = frozenset(
    {
        AccountStatus.RATE_LIMITED,
        AccountStatus.QUOTA_EXCEEDED,
        AccountStatus.PAUSED,
        AccountStatus.REAUTH_REQUIRED,
        AccountStatus.DEACTIVATED,
    }
)


def _required_owner_transient_drain_seconds(state: AccountState, *, now: float) -> float | None:
    """Estimate how long a required owner stays transiently unavailable.

    Returns the remaining seconds of the transient window, or ``None`` when
    the owner is not transiently drained. A required owner fails selection
    today through the inner selector's bounded error backoff after repeated
    transient upstream errors (the 1012 ``stream_incomplete`` /
    ``server_error`` bursts that also drive the DRAINING/PROBING health
    tiers); health-tier drain without backoff is kept as a defensive
    transient signal so future selection filters cannot silently reintroduce
    the instant fail-closed 502.
    """
    if state.status in _PERMANENTLY_UNSELECTABLE_OWNER_STATUSES:
        return None
    if state.error_count >= ERROR_BACKOFF_THRESHOLD and state.last_error_at is not None:
        backoff = min(
            _OWNER_TRANSIENT_BACKOFF_CAP_SECONDS,
            _OWNER_TRANSIENT_BACKOFF_BASE_SECONDS * (2.0 ** (state.error_count - ERROR_BACKOFF_THRESHOLD)),
        )
        remaining = backoff - (now - state.last_error_at)
        if remaining > 0:
            return remaining
    if state.health_tier in (HEALTH_TIER_DRAINING, HEALTH_TIER_PROBING):
        if state.last_error_at is None:
            return DRAIN_ERROR_WINDOW_SECONDS
        remaining = DRAIN_ERROR_WINDOW_SECONDS - (now - state.last_error_at)
        return remaining if remaining > 0 else PROBE_QUIET_SECONDS
    return None


async def required_owner_transient_drain_seconds(
    load_balancer: LoadBalancer,
    *,
    account_id: str,
    model: str | None,
    service_tier: str | None = None,
    additional_limit_name: str | None = None,
) -> float | None:
    """Classify why a required continuity owner failed selection.

    Returns the remaining transient-unavailability window in seconds when
    the owner is unavailable only because it is transiently drained or
    probing (bounded error backoff after repeated transient upstream
    errors, or the DRAINING/PROBING health tier). Returns ``None`` for
    every permanent reason — inputs errors, owner removed from the
    runtime pool, rate-limited / quota-exhausted / paused /
    re-auth-required / deactivated status, cooldown, or owner outside
    the eligible policy — so callers keep the fail-closed behavior for
    those.
    """
    selection_inputs = await load_balancer._load_selection_inputs(
        account_ids=[account_id],
        model=model,
        service_tier=service_tier,
        additional_limit_name=additional_limit_name,
    )
    if selection_inputs.error_code is not None:
        return None
    owner = next((account for account in selection_inputs.accounts if account.id == account_id), None)
    if owner is None:
        return None
    if owner.status in _PERMANENTLY_UNSELECTABLE_OWNER_STATUSES:
        return None
    runtime = load_balancer._runtime.get(account_id)
    if runtime is None:
        return None
    if runtime.cooldown_until is not None and runtime.cooldown_until > time.time():
        return None
    states, _ = _build_states(
        accounts=[owner],
        latest_primary=selection_inputs.latest_primary,
        latest_secondary=selection_inputs.latest_secondary,
        latest_monthly=selection_inputs.latest_monthly,
        runtime=load_balancer._runtime,
        ignore_standard_quota_account_ids=selection_inputs.ignore_standard_quota_account_ids,
    )
    state = next((entry for entry in states if entry.account_id == account_id), None)
    if state is None:
        return None
    return _required_owner_transient_drain_seconds(state, now=time.time())
