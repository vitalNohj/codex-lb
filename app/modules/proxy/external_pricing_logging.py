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
from typing import Protocol

from app.core.usage.external_pricing import calculated_cost_for_request
from app.core.usage.pricing import UsageTokens
from app.db.models import CostSource, ExternalPriceStatus

logger = logging.getLogger(__name__)


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


_NO_COST = ExternalRequestCost(cost_usd=None, cost_source=None, price_status=None)


async def external_request_cost(
    *,
    provider: str,
    model: str,
    usage: UsageTokens | None,
    billed_cost_usd: float | None,
    service_tier: str | None = None,
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

    if billed_cost_usd is not None:
        return ExternalRequestCost(
            cost_usd=billed_cost_usd,
            cost_source=CostSource.UPSTREAM_BILLED.value,
            price_status=status_value,
        )

    if calculated is not None:
        return ExternalRequestCost(
            cost_usd=calculated.cost_usd,
            cost_source=CostSource.CATALOG_CALCULATED.value,
            price_status=status_value,
        )

    return ExternalRequestCost(cost_usd=None, cost_source=None, price_status=status_value)


def no_external_cost() -> ExternalRequestCost:
    """Cost fields for an integration that does not participate.

    Ollama and OmniRoute land here. A NULL ``price_status`` is what tells the UI to
    render ``--`` rather than an unresolved marker: these rows were never expected
    to carry an external list price.
    """

    return _NO_COST


def is_unresolved_status(price_status: str | None) -> bool:
    """Whether a row should be marked as an eligible model that stayed unpriced."""

    return price_status in (ExternalPriceStatus.UNRESOLVED.value, ExternalPriceStatus.AMBIGUOUS.value)


def usage_tokens_from_sidecar(usage: SidecarUsageLike | None) -> UsageTokens | None:
    """Adapt a sidecar usage object to the shared token-usage shape."""

    if usage is None:
        return None
    return UsageTokens(
        input_tokens=float(usage.input_tokens),
        output_tokens=float(usage.output_tokens),
        cached_input_tokens=float(usage.cached_input_tokens),
    )
