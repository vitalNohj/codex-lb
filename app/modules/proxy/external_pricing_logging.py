"""Cost fields for one external-integration request log row.

Collects the three facts a request log needs about money in one place so every
participating dispatch records them identically:

* ``cost_usd`` -- what to store, and
* ``cost_source`` -- where that number came from, and
* ``price_status`` -- whether an eligible model actually got priced.

Precedence is not a preference, it is a correctness rule. An amount the upstream
reported as billed is authoritative actual spend and is stored verbatim: it folds
in tiered pricing, peak multipliers, cache ratios, and rounding that are not
reproducible from published rates. A catalog-calculated list price is used only
when the upstream reported nothing, and is marked as such, because it is what the
request would list at rather than what was debited.

The two never merge. A calculated figure never overwrites a billed one, and a
billed one is never recomputed or reconciled against list pricing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from math import isfinite
from typing import Generic, Protocol, TypeVar

from app.core.usage.external_pricing import calculated_cost_for_request
from app.core.usage.pricing import UsageTokens
from app.db.models import CostSource, ExternalPriceStatus

logger = logging.getLogger(__name__)

_MAX_COST_MICRODOLLARS = (1 << 63) - 1


class SidecarUsageLike(Protocol):
    """Token counts every participating sidecar's usage object exposes."""

    @property
    def input_tokens(self) -> int: ...

    @property
    def output_tokens(self) -> int: ...

    @property
    def cached_input_tokens(self) -> int: ...


@dataclass(frozen=True, slots=True)
class ExternalRequestCost:
    cost_usd: float | None
    cost_source: str | None
    price_status: str | None


_SidecarUsage = TypeVar("_SidecarUsage", bound=SidecarUsageLike)


@dataclass(frozen=True, slots=True)
class ExternalStreamSettlement(Generic[_SidecarUsage]):
    usage: _SidecarUsage | None
    cost: ExternalRequestCost


def _cost_is_representable(cost_usd: float) -> bool:
    scaled_cost = cost_usd * 1_000_000
    return isfinite(cost_usd) and cost_usd >= 0 and isfinite(scaled_cost) and scaled_cost <= _MAX_COST_MICRODOLLARS


@dataclass(slots=True)
class BilledCostAccumulator:
    value: float | None = None

    def observe(self, reported_cost_usd: float | None) -> None:
        if reported_cost_usd is not None and _cost_is_representable(reported_cost_usd):
            self.value = reported_cost_usd


async def external_request_cost(
    *,
    provider: str,
    model: str,
    usage: UsageTokens | None,
    billed_cost_usd: float | None,
    service_tier: str | None = None,
    schedule_lookup: bool = True,
) -> ExternalRequestCost:
    """Resolve the cost fields for one request on a participating integration.

    Never raises and never blocks on remote work: the underlying resolver answers
    from persisted state and schedules any lookup in the background.
    """

    try:
        calculated, status = await calculated_cost_for_request(
            provider=provider,
            model=model,
            usage=usage,
            service_tier=service_tier,
            schedule_lookup=schedule_lookup,
        )
    except Exception:
        # Pricing is reporting, not routing. A failure here must cost the caller
        # a cost figure, never the request. It is reported as unresolved rather
        # than as "nothing to say": a participating provider that fell through
        # unmarked would let the caller reach the substring-glob static table,
        # which is the mispricing this resolver exists to remove.
        logger.warning("external price resolution failed provider=%s model=%s", provider, model, exc_info=True)
        calculated, status = None, ExternalPriceStatus.UNRESOLVED

    status_value = status.value if status is not None else None

    if billed_cost_usd is not None and _cost_is_representable(billed_cost_usd):
        return ExternalRequestCost(
            cost_usd=billed_cost_usd,
            cost_source=CostSource.UPSTREAM_BILLED.value,
            price_status=status_value,
        )

    if calculated is not None and _cost_is_representable(calculated.cost_usd):
        return ExternalRequestCost(
            cost_usd=calculated.cost_usd,
            cost_source=CostSource.CATALOG_CALCULATED.value,
            price_status=status_value,
        )

    return ExternalRequestCost(cost_usd=None, cost_source=None, price_status=status_value)


async def external_stream_settlement(
    *,
    provider: str,
    model: str,
    usage: _SidecarUsage | None,
    billed_cost_usd: float | None,
    completed: bool,
    service_tier: str | None = None,
) -> ExternalStreamSettlement[_SidecarUsage]:
    settled_usage = usage if completed else None
    cost = await external_request_cost(
        provider=provider,
        model=model,
        usage=usage_tokens_from_sidecar(settled_usage),
        billed_cost_usd=billed_cost_usd,
        service_tier=service_tier,
    )
    return ExternalStreamSettlement(usage=settled_usage, cost=cost)


def cost_microdollars(cost: ExternalRequestCost | None) -> int:
    """What one already-resolved request cost may charge a cost limit.

    A cost-limited API key must accrue the same number the request log records.
    Left to itself, reservation settlement prices the model from the substring-glob
    static table, so an id the resolver deliberately left unpriced would still be
    debited at some other model's rate -- and would then disagree with the NULL the
    log stored, which is also what a re-created limit backfills from.

    An unknown price therefore charges nothing rather than a fabricated amount.
    Only the cost accrues differently: the request is served and its tokens are
    counted exactly as before, so allow and deny behavior is unchanged.

    Takes an already-resolved cost rather than resolving its own so the quota and
    the log row are literally the same answer. This is the only conversion entry
    point on purpose: a second one that resolved its own cost would reintroduce
    two reads of the same fact, and a concurrent lookup landing between them would
    charge nothing against a row that recorded a price.

    ``None`` is a caller that has no resolved cost to state, which charges nothing
    for the same reason an unresolved price does.
    """

    if cost is None or cost.cost_usd is None:
        return 0
    if not _cost_is_representable(cost.cost_usd):
        return 0
    return int(cost.cost_usd * 1_000_000)


def usage_tokens_from_sidecar(usage: SidecarUsageLike | None) -> UsageTokens | None:
    """Adapt a sidecar usage object to the shared token-usage shape."""

    if usage is None:
        return None
    return UsageTokens(
        input_tokens=float(usage.input_tokens),
        output_tokens=float(usage.output_tokens),
        cached_input_tokens=float(usage.cached_input_tokens),
    )
