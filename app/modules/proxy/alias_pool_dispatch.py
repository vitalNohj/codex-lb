"""Alias pool failover for ``POST /v1/chat/completions``.

A pool is an alias whose ordered ``targets`` has two or more entries. The loop
here tries them in order and moves to the next target only when the attempt
failed **before any byte reached the client** with a retryable upstream
failure (see ``alias_pool_attempts.RETRYABLE_UPSTREAM_STATUSES``). Everything
else - a 400, a Cursor context-length synthetic success, a mid-stream failure -
is the response, exactly as the single-provider path returns it.

The loop does not know how to talk to a provider. The caller supplies
``dispatch(target, attribution)``, which resolves the route for one target and
calls that provider's ``proxy_chat_to_*`` with the pool attribution and
``allow_failover=True``. The provider raises :class:`PoolTargetFailed` when its
open failed in a retryable way, without settling the reservation or writing a
log row; the loop records the cooldown and either moves on or, when no target
is left, renders that failure through the provider that produced it. So the
reservation is settled exactly once, by the attempt that ends the request, and
every retryable failure - the last one included - refreshes its cooldown.

A target that cannot be attempted at all - no route, or an integration with no
usable API key - raises :class:`PoolTargetUnavailable` before anything is sent.
It is skipped without a cooldown and is not counted as an attempt: attempts
count targets the request was actually sent to.

Access comes first. :func:`authorize_pool_targets` narrows the pool to the
targets the key may use, checking each target as itself - the provider and
model the loop will send to - because an allowlist that names the alias must
not become a way to reach a target the key may not use directly. The caller
runs it before reserving usage, so a refused request holds no budget. Limits
and the reservation are then the caller's business, once against the alias.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from fastapi import Request, Response

from app.core.exceptions import ProxyModelNotAllowed
from app.core.utils.request_id import get_request_id
from app.modules.api_keys.service import ApiKeyData
from app.modules.proxy.alias_pool_attempts import (
    POOL_ATTEMPTS_HEADER,
    AliasPoolCooldownRegistry,
    ChatRequestAttribution,
    PoolTargetFailed,
    PoolTargetUnavailable,
    PoolTargetUnavailableReason,
    get_alias_pool_cooldowns,
)
from app.modules.proxy.request_policy import validate_model_access
from app.modules.proxy.sidecar_routing import SidecarRoutingEntry

logger = logging.getLogger(__name__)

PoolTargetDispatch = Callable[[str, ChatRequestAttribution], Awaitable[Response]]
"""``dispatch(target, attribution) -> Response``.

Raises :class:`PoolTargetFailed` for a retryable open failure,
:class:`PoolTargetUnavailable` when the target cannot be attempted (no enabled
pool-capable route, or no usable API key), and returns the provider's response
otherwise.
"""


class AliasPoolUnavailable(Exception):
    """No target of the pool could be attempted, so nothing was sent anywhere.

    Every target was skipped as :class:`PoolTargetUnavailable`. That is an
    operator configuration gap (integrations turned off or without an API key),
    not a client error, and the caller surfaces it as one.
    """

    def __init__(self, alias: str, *, reasons: frozenset[PoolTargetUnavailableReason]) -> None:
        super().__init__(f"no target of alias pool {alias!r} can be attempted (reasons={sorted(reasons)})")
        self.alias = alias
        self.reasons = reasons


@dataclass(frozen=True, slots=True)
class AuthorizedPool:
    """The targets of ``alias`` this request's key may use, in pool order.

    Only :func:`authorize_pool_targets` builds one, so the failover loop cannot
    run on a target list that skipped the per-target access check.
    """

    alias: str
    targets: tuple[str, ...]


def authorize_pool_targets(
    *,
    alias: str,
    targets: Sequence[str],
    api_key: ApiKeyData | None,
    routing_entries: tuple[SidecarRoutingEntry, ...],
) -> AuthorizedPool:
    """Narrow ``targets`` to the ones this key may use, keeping pool order.

    Each target is authorized as itself: the provider and canonical model its
    route resolves to are exactly what the loop dispatches, so a grant for one
    model can never approve a request that is then sent to another. A key with
    an enforced model never pools - the enforced model replaces the alias - so
    there is no second identity to authorize.

    Raises the last rejection when nothing is allowed, so a key allowed on the
    alias but on none of its targets gets the same "no access" answer it would
    get requesting any target directly. Call this before reserving usage: a
    request refused here must hold no budget, the same order the
    single-provider path uses.
    """

    if api_key is not None and api_key.enforced_model is not None:
        raise ValueError("an API key with an enforced model never pools")
    request_id = get_request_id()
    allowed: list[str] = []
    last_rejection: ProxyModelNotAllowed | None = None
    for target in targets:
        try:
            validate_model_access(api_key, target, routing_entries=routing_entries)
        except ProxyModelNotAllowed as exc:
            last_rejection = exc
            logger.info(
                "alias_pool_attempt request_id=%s alias=%s target=%s attempt=0 outcome=rejected reason=access",
                request_id,
                alias,
                target,
            )
            continue
        allowed.append(target)
    if not allowed:
        assert last_rejection is not None
        raise last_rejection
    return AuthorizedPool(alias=alias, targets=tuple(allowed))


async def dispatch_chat_with_failover(
    request: Request,
    pool: AuthorizedPool,
    *,
    dispatch: PoolTargetDispatch,
    cooldowns: AliasPoolCooldownRegistry | None = None,
) -> Response:
    """Try ``pool.targets`` in pool order and return the first response produced.

    ``dispatch`` is described on :data:`PoolTargetDispatch`.
    """

    registry = cooldowns or get_alias_pool_cooldowns()
    request_id = get_request_id()
    loop_started_at = time.monotonic()
    alias = pool.alias

    ordered = _order_by_cooldown(registry, pool.targets, alias=alias, request_id=request_id)

    attempts = 0
    unavailable: set[PoolTargetUnavailableReason] = set()
    last_failure: PoolTargetFailed | None = None
    last_failed_target: str | None = None
    for target in ordered:
        if attempts > 0 and await request.is_disconnected():
            logger.info(
                "alias_pool_abandoned request_id=%s alias=%s attempts=%d reason=client_disconnected",
                request_id,
                alias,
                attempts,
            )
            break
        # Numbered before the dispatch because the attribution carries it, but
        # only committed once the target was actually sent the request.
        attempt = attempts + 1
        queue_ms = int((time.monotonic() - loop_started_at) * 1000) if attempt > 1 else None
        attribution = ChatRequestAttribution(
            model=alias,
            upstream_model=target,
            pool_attempts=attempt,
            queue_ms=queue_ms,
        )
        try:
            response = await dispatch(target, attribution)
        except PoolTargetUnavailable as exc:
            # Nothing was sent: not an attempt, and no upstream health to cool.
            unavailable.add(exc.reason)
            logger.warning(
                "alias_pool_attempt request_id=%s alias=%s target=%s attempt=0 outcome=rejected reason=%s provider=%s",
                request_id,
                alias,
                target,
                exc.reason,
                exc.provider,
            )
            continue
        except PoolTargetFailed as exc:
            attempts = attempt
            registry.record_failure(target, exc.failure)
            logger.info(
                "alias_pool_attempt request_id=%s alias=%s target=%s attempt=%d outcome=failover status=%d "
                "cooldown_s=%.0f",
                request_id,
                alias,
                target,
                attempts,
                exc.failure.status_code,
                exc.failure.cooldown_seconds(),
            )
            last_failure = exc
            last_failed_target = target
            continue
        attempts = attempt
        logger.info(
            "alias_pool_attempt request_id=%s alias=%s target=%s attempt=%d outcome=served status=%d",
            request_id,
            alias,
            target,
            attempts,
            response.status_code,
        )
        if response.status_code < 400:
            registry.record_success(target)
        _set_attempts_header(response, attempts)
        return response

    if last_failure is not None:
        # Every remaining target was tried (or the client left): render the last
        # retryable failure through the provider that produced it, so the
        # settlement and log row happen exactly once, on this attempt.
        logger.info(
            "alias_pool_exhausted request_id=%s alias=%s attempts=%d last_target=%s status=%d",
            request_id,
            alias,
            attempts,
            last_failed_target,
            last_failure.failure.status_code,
        )
        response = await last_failure.render()
        _set_attempts_header(response, attempts)
        return response

    # Nothing was sent anywhere: every target lost its route after it was saved
    # or has no usable API key. An operator configuration gap, not a client one.
    raise AliasPoolUnavailable(alias, reasons=frozenset(unavailable))


def _order_by_cooldown(
    registry: AliasPoolCooldownRegistry,
    targets: tuple[str, ...],
    *,
    alias: str,
    request_id: str | None,
) -> list[str]:
    """Ready targets in pool order, then cooling ones soonest-to-expire first.

    Cooling targets stay in the list on purpose: when everything is cooling
    the request still goes somewhere, and the best guess is the target whose
    cooldown ends first. They are only *deprioritized* behind ready targets.
    """

    ready, cooling = registry.order_targets(targets)
    for target in cooling:
        logger.info(
            "alias_pool_attempt request_id=%s alias=%s target=%s attempt=0 outcome=skipped_cooling",
            request_id,
            alias,
            target,
        )
    return [*ready, *cooling]


def _set_attempts_header(response: Response, attempts: int) -> None:
    response.headers[POOL_ATTEMPTS_HEADER] = str(attempts)
