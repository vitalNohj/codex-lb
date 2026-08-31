from __future__ import annotations

from typing import Protocol

from app.core.usage.external_pricing.providers import is_external_priced_log_source
from app.core.usage.pricing import (
    ModelPrice,
    UsageCostBreakdown,
    UsageTokens,
    calculate_cost_breakdown_from_usage,
    calculate_cost_from_usage,
    get_pricing_for_model,
)
from app.db.models import CostSource


class RequestLogLike(Protocol):
    @property
    def model(self) -> str | None: ...

    @property
    def service_tier(self) -> str | None: ...

    @property
    def input_tokens(self) -> int | None: ...

    @property
    def output_tokens(self) -> int | None: ...

    @property
    def cached_input_tokens(self) -> int | None: ...

    @property
    def reasoning_tokens(self) -> int | None: ...

    @property
    def cost_usd(self) -> float | None: ...


def declares_price_provenance(log: RequestLogLike) -> bool:
    """Whether the row's writer already settled what its cost is.

    Any row priced from a resolved source other than the static table states that
    source in ``cost_source``, and a row written by an integration that
    participates in external price resolution states a ``price_status``. Either
    way the persisted ``cost_usd`` is the answer, so nothing may overwrite it with
    a substring-matched static-table figure.
    """

    if getattr(log, "price_status", None) is not None:
        return True
    cost_source = getattr(log, "cost_source", None)
    return cost_source is not None and cost_source != CostSource.STATIC_TABLE.value


def participates_in_external_pricing(log: RequestLogLike) -> bool:
    """Whether the external price resolver owns this row's cost.

    Deliberately narrower than :func:`declares_price_provenance`. Only these rows
    can carry a cost the resolver intentionally left NULL, and only for them is
    the static table barred from supplying the component split, because its
    aliases match by substring and so answer for ids they have never heard of.

    An operator-configured model-source row, or an Ollama/OmniRoute row whose
    upstream reported a billed amount, states its own provenance without
    participating here. Their totals stay authoritative and their split is still
    shown when the static-table computation reproduces that total, exactly as
    before external price resolution existed.

    ``price_status`` alone is not sufficient. A participating row whose upstream
    reported a billed amount for a model id that normalizes to nothing carries
    ``cost_source=upstream_billed`` with no status, so the serving integration is
    consulted too. A row written before this resolver existed states no
    ``cost_source`` at all and keeps its historical static-table split.
    """

    if getattr(log, "price_status", None) is not None:
        return True
    cost_source = getattr(log, "cost_source", None)
    if cost_source == CostSource.CATALOG_CALCULATED.value:
        return True
    return (
        cost_source is not None
        and cost_source != CostSource.STATIC_TABLE.value
        and is_external_priced_log_source(getattr(log, "source", None))
    )


def cached_input_tokens_from_log(log: RequestLogLike) -> int | None:
    cached_tokens = log.cached_input_tokens
    if cached_tokens is None:
        return None
    cached_tokens = max(0, int(cached_tokens))
    input_tokens = log.input_tokens
    if input_tokens is not None:
        cached_tokens = min(cached_tokens, int(input_tokens))
    return cached_tokens


def usage_tokens_from_log(log: RequestLogLike) -> UsageTokens | None:
    input_tokens = log.input_tokens
    if input_tokens is None:
        return None
    output_tokens = output_tokens_from_log(log)
    if output_tokens is None:
        return None
    cached_tokens = cached_input_tokens_from_log(log) or 0
    return UsageTokens(
        input_tokens=float(input_tokens),
        output_tokens=float(output_tokens),
        cached_input_tokens=float(cached_tokens),
    )


def output_tokens_from_log(log: RequestLogLike) -> int | None:
    output_tokens = log.output_tokens
    if output_tokens is not None:
        return int(output_tokens)
    reasoning_tokens = log.reasoning_tokens
    if reasoning_tokens is None:
        return None
    return int(reasoning_tokens)


def calculated_cost_from_log(log: RequestLogLike, *, precision: int | None = None) -> float | None:
    if not log.model:
        return None
    if declares_price_provenance(log):
        return None
    usage = usage_tokens_from_log(log)
    if not usage:
        return None
    resolved = get_pricing_for_model(log.model, None, None)
    if not resolved:
        return None
    _, price = resolved
    cost = calculate_cost_from_usage(usage, price, service_tier=log.service_tier)
    if cost is None:
        return None
    if precision is None:
        return cost
    return round(cost, precision)


def cost_from_log(log: RequestLogLike, *, precision: int | None = None) -> float | None:
    cost = log.cost_usd
    if cost is None:
        return None
    if precision is None:
        return float(cost)
    return round(float(cost), precision)


def _totals_match(left: float | None, right: float | None, *, precision: int | None) -> bool:
    if left is None or right is None:
        return False
    if precision is None:
        return left == right
    return abs(left - right) < (10 ** (-precision)) / 2


def resolved_cost_breakdown(
    log: RequestLogLike,
    price: ModelPrice,
    *,
    precision: int | None = None,
) -> UsageCostBreakdown | None:
    """Split a declared-provenance row's persisted total using its own rate.

    ``price`` must be the rate the resolver persisted for this model, not a
    static-table guess. The split is only returned when recomputing it reproduces
    the total already stored on the row, which is what proves the rate is the one
    that produced that total: an upstream-billed amount, or a rate changed since
    the request, will not reconcile and yields no components rather than a
    plausible-looking fiction.
    """

    persisted_raw = cost_from_log(log)
    if persisted_raw is None:
        return None
    usage = usage_tokens_from_log(log)
    if usage is None:
        return None
    raw = calculate_cost_breakdown_from_usage(usage, price, service_tier=log.service_tier)
    if raw is None or not _totals_match(persisted_raw, raw.total_usd, precision=precision):
        return None
    return calculate_cost_breakdown_from_usage(usage, price, service_tier=log.service_tier, precision=precision)


def cost_breakdown_from_log(
    log: RequestLogLike,
    *,
    precision: int | None = None,
    resolved_price: ModelPrice | None = None,
) -> UsageCostBreakdown:
    full_breakdown: UsageCostBreakdown | None = None
    input_usd: float | None = None
    cached_input_usd: float | None = None
    output_usd: float | None = None
    raw_total_usd: float | None = None
    total_usd: float | None = None
    if participates_in_external_pricing(log):
        # The resolver owns this row's price. A NULL cost here means the model
        # stayed unresolved, and it must stay NULL end to end so the API and the
        # UI mark it instead of showing a glob-matched rate.
        persisted = cost_from_log(log, precision=precision)
        if persisted is None:
            return UsageCostBreakdown(
                input_usd=None,
                cached_input_usd=None,
                output_usd=None,
                total_usd=None,
            )
        # The row does have a settled cost, so the components are still worth
        # showing -- but only when derived from the rate that actually produced
        # it. The static table is not that rate, and reaching for it here is what
        # would put another model's split under a correct total.
        components = resolved_cost_breakdown(log, resolved_price, precision=precision) if resolved_price else None
        return UsageCostBreakdown(
            input_usd=components.input_usd if components is not None else None,
            cached_input_usd=components.cached_input_usd if components is not None else None,
            output_usd=components.output_usd if components is not None else None,
            total_usd=persisted,
        )
    if log.model:
        resolved = get_pricing_for_model(log.model, None, None)
        if resolved is not None:
            _, price = resolved
            input_tokens = log.input_tokens
            cached_tokens = cached_input_tokens_from_log(log)
            output_tokens = output_tokens_from_log(log)
            usage = usage_tokens_from_log(log)
            if usage is not None:
                raw_full_breakdown = calculate_cost_breakdown_from_usage(usage, price, service_tier=log.service_tier)
                if raw_full_breakdown is not None:
                    raw_total_usd = raw_full_breakdown.total_usd
                full_breakdown = calculate_cost_breakdown_from_usage(
                    usage,
                    price,
                    service_tier=log.service_tier,
                    precision=precision,
                )
                if full_breakdown is not None:
                    total_usd = full_breakdown.total_usd
            if input_tokens is not None and cached_tokens is not None:
                input_breakdown = calculate_cost_breakdown_from_usage(
                    UsageTokens(
                        input_tokens=float(input_tokens),
                        output_tokens=0.0,
                        cached_input_tokens=float(cached_tokens),
                    ),
                    price,
                    service_tier=log.service_tier,
                    precision=precision,
                )
                if input_breakdown is not None:
                    input_usd = input_breakdown.input_usd
                    cached_input_usd = input_breakdown.cached_input_usd
            if output_tokens is not None:
                output_breakdown = calculate_cost_breakdown_from_usage(
                    UsageTokens(
                        input_tokens=float(input_tokens or 0),
                        output_tokens=float(output_tokens),
                        cached_input_tokens=float(cached_tokens or 0),
                    ),
                    price,
                    service_tier=log.service_tier,
                    precision=precision,
                )
                if output_breakdown is not None:
                    output_usd = output_breakdown.output_usd

    persisted_cost = cost_from_log(log, precision=precision)
    if persisted_cost is not None:
        persisted_raw_cost = cost_from_log(log)
        if not _totals_match(persisted_raw_cost, raw_total_usd, precision=precision):
            return UsageCostBreakdown(
                input_usd=None,
                cached_input_usd=None,
                output_usd=None,
                total_usd=persisted_cost,
            )
        return UsageCostBreakdown(
            input_usd=input_usd,
            cached_input_usd=cached_input_usd,
            output_usd=output_usd,
            total_usd=persisted_cost,
        )
    if full_breakdown is not None:
        return UsageCostBreakdown(
            input_usd=input_usd,
            cached_input_usd=cached_input_usd,
            output_usd=output_usd,
            total_usd=total_usd,
        )
    return UsageCostBreakdown(
        input_usd=input_usd,
        cached_input_usd=cached_input_usd,
        output_usd=output_usd,
        total_usd=None,
    )


def total_tokens_from_log(log: RequestLogLike) -> int | None:
    input_tokens = log.input_tokens
    output_tokens = output_tokens_from_log(log)
    if input_tokens is None and output_tokens is None:
        return None
    return (input_tokens or 0) + (output_tokens or 0)
