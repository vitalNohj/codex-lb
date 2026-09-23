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

Access, limits, and the reservation are the caller's business and happen once
against the alias before the loop runs. Per-target access is re-checked here
because an allowlist that names the alias must not become a way to reach a
target the key may not use directly.
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
    get_alias_pool_cooldowns,
)
from app.modules.proxy.request_policy import validate_model_access
from app.modules.proxy.sidecar_routing import SidecarRoutingEntry

logger = logging.getLogger(__name__)

PoolTargetDispatch = Callable[[str, ChatRequestAttribution], Awaitable[Response]]
"""``dispatch(target, attribution) -> Response``.

Raises :class:`PoolTargetFailed` for a retryable open failure,
:class:`PoolTargetUnroutable` when the target has no enabled pool-capable
route, and returns the provider's response otherwise.
"""


class PoolTargetUnroutable(Exception):
    """The target resolves to no route, or to one that cannot fail over.

    Save-time validation rejects these, but validation does not re-run when an
    integration is disabled afterwards, so the loop must tolerate it: the
    target is skipped as a non-retryable rejection and the request continues.
    """

    def __init__(self, target: str, *, provider: str | None) -> None:
        super().__init__(f"alias pool target {target!r} has no pool-capable route (provider={provider})")
        self.target = target
        self.provider = provider


@dataclass(frozen=True, slots=True)
class _Candidate:
    target: str
    effective_model: str


async def dispatch_chat_with_failover(
    request: Request,
    *,
    alias: str,
    targets: Sequence[str],
    api_key: ApiKeyData | None,
    routing_entries: tuple[SidecarRoutingEntry, ...],
    effective_model_for: Callable[[str], str],
    dispatch: PoolTargetDispatch,
    cooldowns: AliasPoolCooldownRegistry | None = None,
) -> Response:
    """Try ``targets`` in pool order and return the first response produced.

    ``effective_model_for`` applies the API key's enforced model to a target;
    the loop validates access on that value, the same identity the single
    provider path validates. ``dispatch`` is described on
    :data:`PoolTargetDispatch`.
    """

    registry = cooldowns or get_alias_pool_cooldowns()
    request_id = get_request_id()
    loop_started_at = time.monotonic()

    candidates = _allowed_candidates(
        alias=alias,
        targets=targets,
        api_key=api_key,
        routing_entries=routing_entries,
        effective_model_for=effective_model_for,
        request_id=request_id,
    )

    ordered = _order_by_cooldown(registry, candidates, alias=alias, request_id=request_id)

    attempts = 0
    last_failure: PoolTargetFailed | None = None
    last_failed_target: str | None = None
    for candidate in ordered:
        if attempts > 0 and await request.is_disconnected():
            logger.info(
                "alias_pool_abandoned request_id=%s alias=%s attempts=%d reason=client_disconnected",
                request_id,
                alias,
                attempts,
            )
            break
        attempts += 1
        queue_ms = int((time.monotonic() - loop_started_at) * 1000) if attempts > 1 else None
        attribution = ChatRequestAttribution(
            model=alias,
            upstream_model=candidate.target,
            pool_attempts=attempts,
            queue_ms=queue_ms,
        )
        try:
            response = await dispatch(candidate.target, attribution)
        except PoolTargetUnroutable as exc:
            logger.warning(
                "alias_pool_attempt request_id=%s alias=%s target=%s attempt=%d outcome=rejected "
                "reason=unroutable provider=%s",
                request_id,
                alias,
                candidate.target,
                attempts,
                exc.provider,
            )
            continue
        except PoolTargetFailed as exc:
            registry.record_failure(candidate.target, exc.failure)
            logger.info(
                "alias_pool_attempt request_id=%s alias=%s target=%s attempt=%d outcome=failover status=%d "
                "cooldown_s=%.0f",
                request_id,
                alias,
                candidate.target,
                attempts,
                exc.failure.status_code,
                exc.failure.cooldown_seconds(),
            )
            last_failure = exc
            last_failed_target = candidate.target
            continue
        logger.info(
            "alias_pool_attempt request_id=%s alias=%s target=%s attempt=%d outcome=served status=%d",
            request_id,
            alias,
            candidate.target,
            attempts,
            response.status_code,
        )
        if response.status_code < 400:
            registry.record_success(candidate.target)
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

    # Nothing was dispatchable: every candidate lost its route after save-time
    # validation. That is an operator configuration problem, not a client one.
    raise PoolTargetUnroutable(alias, provider=None)


def _allowed_candidates(
    *,
    alias: str,
    targets: Sequence[str],
    api_key: ApiKeyData | None,
    routing_entries: tuple[SidecarRoutingEntry, ...],
    effective_model_for: Callable[[str], str],
    request_id: str | None,
) -> list[_Candidate]:
    """Filter ``targets`` to the ones this key may use, in pool order.

    Raises the last rejection when nothing is allowed, so a key allowed on the
    alias but on none of its targets gets the same "no access" answer it would
    get requesting any target directly.
    """

    allowed: list[_Candidate] = []
    last_rejection: ProxyModelNotAllowed | None = None
    for target in targets:
        effective_model = effective_model_for(target)
        try:
            validate_model_access(api_key, effective_model, routing_entries=routing_entries)
        except ProxyModelNotAllowed as exc:
            last_rejection = exc
            logger.info(
                "alias_pool_attempt request_id=%s alias=%s target=%s attempt=0 outcome=rejected reason=access",
                request_id,
                alias,
                target,
            )
            continue
        allowed.append(_Candidate(target=target, effective_model=effective_model))
    if not allowed:
        assert last_rejection is not None
        raise last_rejection
    return allowed


def _order_by_cooldown(
    registry: AliasPoolCooldownRegistry,
    candidates: list[_Candidate],
    *,
    alias: str,
    request_id: str | None,
) -> list[_Candidate]:
    """Ready targets in pool order, then cooling ones soonest-to-expire first.

    Cooling targets stay in the list on purpose: when everything is cooling
    the request still goes somewhere, and the best guess is the target whose
    cooldown ends first. They are only *deprioritized* behind ready targets.
    """

    by_target = {candidate.target: candidate for candidate in candidates}
    ready, cooling = registry.order_targets(tuple(by_target))
    for target in cooling:
        logger.info(
            "alias_pool_attempt request_id=%s alias=%s target=%s attempt=0 outcome=skipped_cooling",
            request_id,
            alias,
            target,
        )
    return [by_target[target] for target in (*ready, *cooling)]


def _set_attempts_header(response: Response, attempts: int) -> None:
    response.headers[POOL_ATTEMPTS_HEADER] = str(attempts)
