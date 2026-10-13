"""Bounded hold for continuity-bound requests on a transiently drained owner.

When a required continuity owner fails selection, this hold re-checks the
same-owner selection for a short bounded wait while the owner is unavailable
only because it is transiently drained or probing. Recovery proceeds on the
same owner; hold expiry marks the failure with ``owner_hold_expired`` so
callers answer 503 + ``Retry-After`` with the stable
``previous_response_owner_unavailable`` body instead of an instant 502.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from app.core.config.settings import get_settings
from app.modules.proxy.owner_drain import required_owner_transient_drain_seconds

if TYPE_CHECKING:
    from app.modules.proxy.load_balancer import AccountSelection, LoadBalancer

logger = logging.getLogger("app.modules.proxy.service")

# Poll cadence for the bounded continuity-owner drain hold; re-checks
# selection without hot-looping.
_OWNER_HOLD_POLL_INTERVAL_SECONDS = 0.5


def _remaining_budget_seconds(deadline: float) -> float:
    return max(0.0, deadline - time.monotonic())


async def hold_for_transient_required_owner(
    load_balancer: LoadBalancer,
    *,
    failed_selection: AccountSelection,
    run_selection: Callable[[], Awaitable[AccountSelection]],
    describe_account_id: Callable[[str | None], str | None],
    deadline: float,
    request_id: str,
    kind: str,
    request_stage: str,
    account_id: str,
    model: str | None,
    service_tier: str | None = None,
    additional_limit_name: str | None = None,
    settings: Any | None = None,
) -> AccountSelection:
    """Hold a required-owner failure while the owner is only transiently drained.

    The failed selection must already be fail-closed on a required owner
    (the caller checked ``fallback_on_preferred_account_unavailable``).
    When the owner is unavailable only because it is transiently drained
    or probing, re-check selection for up to the bounded hold (bounded
    also by the request budget); if it becomes selectable, proceed
    normally on that same owner — never a different account. If the hold
    expires, return the failure marked ``owner_hold_expired`` so callers
    answer 503 + ``Retry-After`` with the stable error body instead of
    an instant 502. Permanent unavailability returns the failure
    unmarked, keeping today's behavior.

    Poll waits are plain ``asyncio.sleep`` so client cancellation
    propagates, and no account lease or stream slot is held while
    waiting (failed selections carry no lease; one acquired by a poll is
    released immediately).
    """
    settings = settings or get_settings()
    hold_seconds = float(getattr(settings, "proxy_continuity_owner_hold_seconds", 0.0))
    last_failure = failed_selection
    if hold_seconds <= 0:
        return last_failure

    async def classify_transient_drain() -> float | None:
        return await required_owner_transient_drain_seconds(
            load_balancer,
            account_id=account_id,
            model=model,
            service_tier=service_tier,
            additional_limit_name=additional_limit_name,
        )

    drain_seconds = await classify_transient_drain()
    if drain_seconds is None:
        return last_failure
    budget_remaining = _remaining_budget_seconds(deadline)
    if budget_remaining <= 0:
        return last_failure
    hold_deadline = time.monotonic() + min(hold_seconds, budget_remaining)
    logger.info(
        "Holding request for transiently drained continuity owner request_id=%s kind=%s request_stage=%s "
        "account_id=%s hold_seconds=%.2f drain_seconds=%.2f",
        request_id,
        kind,
        request_stage,
        describe_account_id(account_id),
        min(hold_seconds, budget_remaining),
        drain_seconds,
    )
    while True:
        now = time.monotonic()
        if now >= hold_deadline:
            break
        await asyncio.sleep(min(_OWNER_HOLD_POLL_INTERVAL_SECONDS, hold_deadline - now))
        if time.monotonic() >= hold_deadline:
            break
        retried = await run_selection()
        if retried.account is not None:
            logger.info(
                "Continuity owner recovered during hold request_id=%s kind=%s request_stage=%s account_id=%s",
                request_id,
                kind,
                request_stage,
                describe_account_id(retried.account.id),
            )
            return retried
        if retried.lease is not None:
            await load_balancer.release_account_lease(retried.lease)
        drain_seconds = await classify_transient_drain()
        if drain_seconds is None:
            logger.info(
                "Continuity owner hold aborted: owner no longer transiently drained request_id=%s kind=%s "
                "request_stage=%s account_id=%s error_code=%s",
                request_id,
                kind,
                request_stage,
                describe_account_id(account_id),
                retried.error_code,
            )
            return retried
        last_failure = retried
    logger.warning(
        "Continuity owner hold expired request_id=%s kind=%s request_stage=%s account_id=%s error_code=%s",
        request_id,
        kind,
        request_stage,
        describe_account_id(account_id),
        last_failure.error_code,
    )
    return replace(last_failure, owner_hold_expired=True)
