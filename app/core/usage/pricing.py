from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Iterable, Mapping

from app.core.models.local import load_local_catalog, local_aliases, local_prices
from app.core.models.types import ModelPrice as ModelPrice
from app.core.openai.models import ResponseUsage
from app.core.usage.model_ids import resolve_versioned_model_id, strip_known_sidecar_prefix
from app.core.usage.types import UsageCostByModel, UsageCostSummary

# Anthropic bills a prompt-cache write at 2x the base input rate for the 1-hour
# TTL (1.25x for 5 minutes). CLIProxyAPI upgrades every Claude Code cache
# breakpoint to the 1-hour TTL, and its OpenAI-compatible usage does not split
# writes by TTL, so every reported write is priced at the 1-hour rate.
# https://platform.claude.com/docs/en/build-with-claude/prompt-caching
CACHE_WRITE_INPUT_RATE_MULTIPLIER = 2.0


@dataclass(frozen=True)
class UsageTokens:
    """Token counts for one request.

    ``input_tokens`` is the whole prompt. ``cached_input_tokens`` (cache reads)
    and ``cache_write_input_tokens`` (cache writes) are both parts of it; what
    remains is billed at the plain input rate.
    """

    input_tokens: float
    output_tokens: float
    cached_input_tokens: float = 0.0
    cache_write_input_tokens: float = 0.0


@dataclass(frozen=True)
class UsageCostBreakdown:
    input_usd: float | None
    cached_input_usd: float | None
    output_usd: float | None
    total_usd: float | None
    cache_write_input_usd: float | None = None


@dataclass(frozen=True)
class CostItem:
    model: str
    usage: UsageTokens
    service_tier: str | None = None


FREE_MODEL_PRICE = ModelPrice(input_per_1m=0.0, output_per_1m=0.0, cached_input_per_1m=0.0)
_FREE_MODEL_RE = re.compile(r"(^|[/:_-])free($|[/:_-])")
_OPAQUE_FREE_MODELS = frozenset(
    {
        "big-pickle",
        "oc/big-pickle",
    }
)


def is_known_free_model(model: str | None) -> bool:
    if not model:
        return False
    normalized = model.strip().lower()
    return normalized in _OPAQUE_FREE_MODELS or bool(_FREE_MODEL_RE.search(normalized))


def model_price_is_billable(price: ModelPrice | None) -> bool:
    """Whether ``price`` charges a real, nonzero amount per token.

    A free model's ``0.0`` rates are a price settlement can record, but they
    measure nothing: a request at them costs exactly nothing. Callers that may
    only serve models whose use is actually paid for (shared API keys) treat
    such a price as no price at all.
    """
    if price is None:
        return False
    return any(
        rate is not None and math.isfinite(rate) and rate > 0
        for rate in (price.input_per_1m, price.output_per_1m, price.cached_input_per_1m)
    )


def _as_number(value: int | float | None) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _normalize_usage(usage: UsageTokens | ResponseUsage | None) -> UsageTokens | None:
    if isinstance(usage, UsageTokens):
        input_tokens = _as_number(usage.input_tokens)
        output_tokens = _as_number(usage.output_tokens)
        cached_tokens = _as_number(usage.cached_input_tokens)
        write_tokens = _as_number(usage.cache_write_input_tokens)
        if input_tokens is None or output_tokens is None:
            return None
        cached_tokens = max(0.0, min(cached_tokens or 0.0, input_tokens))
        # Writes are the part of the prompt that is neither a read nor plain
        # input, so they can never exceed what the reads left over.
        write_tokens = max(0.0, min(write_tokens or 0.0, input_tokens - cached_tokens))
        return UsageTokens(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_tokens,
            cache_write_input_tokens=write_tokens,
        )
    if not usage:
        return None
    input_tokens = _as_number(usage.input_tokens)
    output_tokens = _as_number(usage.output_tokens)
    if output_tokens is None and usage.output_tokens_details is not None:
        output_tokens = _as_number(usage.output_tokens_details.reasoning_tokens)
    if input_tokens is None or output_tokens is None:
        return None
    cached_tokens = 0.0
    if usage.input_tokens_details is not None:
        cached_tokens = _as_number(usage.input_tokens_details.cached_tokens) or 0.0
    cached_tokens = max(0.0, min(cached_tokens, input_tokens))
    return UsageTokens(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_input_tokens=cached_tokens,
    )


DEFAULT_PRICING_MODELS: dict[str, ModelPrice] = local_prices()
DEFAULT_MODEL_ALIASES: dict[str, str] = local_aliases()


def resolve_model_alias(model: str, aliases: Mapping[str, str]) -> str | None:
    if not model:
        return None
    normalized = model.lower()
    matched: list[tuple[int, str]] = []
    for pattern, target in aliases.items():
        if fnmatchcase(normalized, pattern.lower()):
            matched.append((len(pattern), target))
    if not matched:
        return None
    return max(matched, key=lambda item: item[0])[1]


def get_pricing_for_model(
    model: str,
    pricing: Mapping[str, ModelPrice] | None = None,
    aliases: Mapping[str, str] | None = None,
) -> tuple[str, ModelPrice] | None:
    if not model:
        return None
    if pricing is None:
        from app.core.models.catalog import catalog_prices, resolve_model

        if aliases is None:
            record = resolve_model(model)
            return (record.canonical_id, record.price) if record.price is not None else None
        pricing = catalog_prices()
    aliases = DEFAULT_MODEL_ALIASES if aliases is None else aliases

    normalized = model.lower()
    if is_known_free_model(normalized):
        return "free", FREE_MODEL_PRICE

    # Some official corrections own all bounded spellings, including when an
    # external snapshot still contains an obsolete exact alias row.
    native = resolve_versioned_model_id(strip_known_sidecar_prefix(normalized))
    local = load_local_catalog().models.get(native) if native is not None else None
    if native is not None and local is not None and local.prefer_canonical_price and native in pricing:
        return native, pricing[native]

    for key, value in pricing.items():
        if key.lower() == normalized:
            return key, value

    # Upstream's dated-release fallback, for every family except Claude: a
    # Claude id is priced only by its exact identity (below), so a dated Claude
    # release must not inherit the undated key's price.
    dated = re.fullmatch(r"(.+)-\d{4}-\d{2}-\d{2}", normalized)
    if dated and dated[1] in pricing and not strip_known_sidecar_prefix(normalized).startswith("claude"):
        return dated[1], pricing[dated[1]]

    # Versioned identity, then a non-Claude alias. A Claude id matches a key
    # only as that exact string, or after one leading cc/, cp-, or cp_ prefix.
    # A longer, dotted, dated, or effort-suffixed id does not inherit a shorter key.
    for alias in (resolve_versioned_model_id(normalized), resolve_model_alias(normalized, aliases)):
        if not alias or (alias == "gpt-5" and normalized.startswith("gpt-5.")):
            continue
        for key, value in pricing.items():
            if key.lower() == alias.lower():
                return key, value
    routed = strip_known_sidecar_prefix(normalized)
    if routed.lower() != normalized:
        for key, value in pricing.items():
            if key.lower() == routed.lower():
                return key, value
    return None


def _uses_priority_tier(service_tier: str | None) -> bool:
    normalized = _normalize_service_tier(service_tier)
    if normalized is None:
        return False
    return normalized in {"priority", "fast"}


def _uses_flex_tier(service_tier: str | None) -> bool:
    normalized = _normalize_service_tier(service_tier)
    if normalized is None:
        return False
    return normalized == "flex"


def _normalize_service_tier(service_tier: str | None) -> str | None:
    if service_tier is None:
        return None
    stripped = service_tier.strip().lower()
    return stripped or None


def _priced_tier(service_tier: str | None) -> str | None:
    tier = _normalize_service_tier(service_tier)
    if tier in {"priority", "fast"}:
        return "priority"
    return tier if tier in {"flex", "batch"} else None


def effective_rates(
    usage: UsageTokens,
    price: ModelPrice,
    *,
    service_tier: str | None,
) -> tuple[float, float, float]:
    is_long_context = (
        price.long_context_threshold_tokens is not None
        and price.long_context_threshold_tokens > 0
        and usage.input_tokens > price.long_context_threshold_tokens
    )
    has_standard_long_context = (
        price.long_context_input_per_1m is not None and price.long_context_output_per_1m is not None
    )
    input_rate = price.input_per_1m
    cached_rate = price.cached_input_per_1m if price.cached_input_per_1m is not None else input_rate
    output_rate = price.output_per_1m

    if is_long_context:
        tier = _priced_tier(service_tier)
        if tier is not None:
            long_input = getattr(price, f"{tier}_long_context_input_per_1m")
            long_output = getattr(price, f"{tier}_long_context_output_per_1m")
            long_cached = getattr(price, f"{tier}_long_context_cached_input_per_1m")
            if long_input is not None and long_output is not None:
                return long_input, long_cached if long_cached is not None else long_input, long_output

    if _uses_priority_tier(service_tier):
        if price.priority_input_per_1m is not None and price.priority_output_per_1m is not None:
            priority_cached = (
                price.priority_cached_input_per_1m
                if price.priority_cached_input_per_1m is not None
                else price.priority_input_per_1m
            )
            return price.priority_input_per_1m, priority_cached, price.priority_output_per_1m
        if price.priority_multiplier is not None:
            input_rate *= price.priority_multiplier
            cached_rate *= price.priority_multiplier
            output_rate *= price.priority_multiplier
            return input_rate, cached_rate, output_rate

    if (
        _normalize_service_tier(service_tier) == "batch"
        and price.batch_input_per_1m is not None
        and price.batch_output_per_1m is not None
    ):
        return (
            price.batch_input_per_1m,
            price.batch_cached_input_per_1m
            if price.batch_cached_input_per_1m is not None
            else price.batch_input_per_1m,
            price.batch_output_per_1m,
        )

    if _uses_flex_tier(service_tier) and price.flex_input_per_1m is not None and price.flex_output_per_1m is not None:
        input_rate = price.flex_input_per_1m
        cached_rate = price.flex_cached_input_per_1m if price.flex_cached_input_per_1m is not None else input_rate
        output_rate = price.flex_output_per_1m
        if is_long_context and has_standard_long_context:
            input_rate *= 2.0
            cached_rate *= 2.0
            output_rate *= 1.5
        return input_rate, cached_rate, output_rate

    if is_long_context and has_standard_long_context:
        assert price.long_context_input_per_1m is not None
        assert price.long_context_output_per_1m is not None
        input_rate = price.long_context_input_per_1m
        cached_rate = (
            price.long_context_cached_input_per_1m if price.long_context_cached_input_per_1m is not None else input_rate
        )
        output_rate = price.long_context_output_per_1m

    return input_rate, cached_rate, output_rate


def effective_cache_write_rate(
    usage: UsageTokens,
    price: ModelPrice,
    *,
    service_tier: str | None,
    input_rate: float,
    retention_12h: bool = False,
) -> float:
    """Write rate for the same context and service tier as ``effective_rates``."""
    is_long_context = (
        price.long_context_threshold_tokens is not None
        and price.long_context_threshold_tokens > 0
        and usage.input_tokens > price.long_context_threshold_tokens
    )
    tier = _priced_tier(service_tier)
    if tier is not None and not (
        (getattr(price, f"{tier}_input_per_1m") is not None and getattr(price, f"{tier}_output_per_1m") is not None)
        or (
            is_long_context
            and getattr(price, f"{tier}_long_context_input_per_1m") is not None
            and getattr(price, f"{tier}_long_context_output_per_1m") is not None
        )
        or (tier == "priority" and price.priority_multiplier is not None)
    ):
        tier = None
    if retention_12h:
        prefix = f"{tier}_" if tier is not None else ""
        if is_long_context:
            prefix += "long_context_"
        rate = getattr(price, prefix + "cache_write_input_12h_per_1m")
        if rate is None:
            raise ValueError("No published 12-hour cache-write rate for this context and service tier")
        return rate
    if tier is not None:
        tier_has_long_rates = (
            getattr(price, f"{tier}_long_context_input_per_1m") is not None
            and getattr(price, f"{tier}_long_context_output_per_1m") is not None
        )
        flex_uses_long_rates = (
            tier == "flex"
            and price.long_context_input_per_1m is not None
            and price.long_context_output_per_1m is not None
        )
        if is_long_context and (tier_has_long_rates or flex_uses_long_rates):
            rate = getattr(price, f"{tier}_long_context_cache_write_input_per_1m")
        else:
            rate = getattr(price, f"{tier}_cache_write_input_per_1m")
        # Do not borrow a Standard write rate for a different service tier.
        return rate if rate is not None else input_rate * CACHE_WRITE_INPUT_RATE_MULTIPLIER

    # CLIProxyAPI upgrades Claude writes to 1h and usage has no TTL split.
    # Preserve both published rates, using 1h when the source supplies it.
    if is_long_context:
        rate = price.long_context_cache_write_input_1h_per_1m
        if rate is None:
            rate = price.long_context_cache_write_input_per_1m
    else:
        rate = price.cache_write_input_1h_per_1m
        if rate is None:
            rate = price.cache_write_input_per_1m
    return rate if rate is not None else input_rate * CACHE_WRITE_INPUT_RATE_MULTIPLIER


def calculate_cost_from_usage(
    usage: UsageTokens | ResponseUsage | None,
    price: ModelPrice,
    *,
    service_tier: str | None = None,
) -> float | None:
    breakdown = calculate_cost_breakdown_from_usage(usage, price, service_tier=service_tier)
    if breakdown is None:
        return None
    return breakdown.total_usd


def calculate_cost_breakdown_from_usage(
    usage: UsageTokens | ResponseUsage | None,
    price: ModelPrice,
    *,
    service_tier: str | None = None,
    precision: int | None = None,
) -> UsageCostBreakdown | None:
    normalized = _normalize_usage(usage)
    if not normalized:
        return None
    write_tokens = normalized.cache_write_input_tokens
    billable_input = max(0.0, normalized.input_tokens - normalized.cached_input_tokens - write_tokens)

    input_rate, cached_rate, output_rate = effective_rates(
        normalized,
        price,
        service_tier=service_tier,
    )

    input_usd = (billable_input / 1_000_000) * input_rate
    cached_input_usd = (normalized.cached_input_tokens / 1_000_000) * cached_rate
    output_usd = (normalized.output_tokens / 1_000_000) * output_rate
    # Zero writes leave every pre-existing total bit-identical: no extra term is
    # added, so persisted costs keep matching their recomputation.
    write_rate = effective_cache_write_rate(normalized, price, service_tier=service_tier, input_rate=input_rate)
    cache_write_input_usd = (write_tokens / 1_000_000) * write_rate if write_tokens > 0 else None

    if precision is not None:
        input_usd = round(input_usd, precision)
        cached_input_usd = round(cached_input_usd, precision)
        output_usd = round(output_usd, precision)
        if cache_write_input_usd is not None:
            cache_write_input_usd = round(cache_write_input_usd, precision)

    total_usd = input_usd + cached_input_usd + output_usd
    if cache_write_input_usd is not None:
        total_usd += cache_write_input_usd

    if precision is not None:
        total_usd = round(total_usd, precision)

    return UsageCostBreakdown(
        input_usd=input_usd,
        cached_input_usd=cached_input_usd,
        output_usd=output_usd,
        total_usd=total_usd,
        cache_write_input_usd=cache_write_input_usd,
    )


def calculate_costs(
    items: Iterable[CostItem],
    pricing: Mapping[str, ModelPrice] | None = None,
    aliases: Mapping[str, str] | None = None,
) -> UsageCostSummary:
    totals: dict[str, float] = defaultdict(float)
    total_usd = 0.0

    for item in items:
        model = item.model
        usage = item.usage
        resolved = get_pricing_for_model(model, pricing, aliases)
        if not resolved:
            continue
        canonical, price = resolved
        cost = calculate_cost_from_usage(usage, price, service_tier=item.service_tier)
        if cost is None:
            continue
        totals[canonical] += cost
        total_usd += cost

    by_model = [UsageCostByModel(model=model, usd=round(value, 6)) for model, value in sorted(totals.items())]
    return UsageCostSummary(
        currency="USD",
        total_usd_7d=round(total_usd, 6),
        by_model=by_model,
    )
