"""Client-visible token prices, derived from the request billing rates."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.usage.pricing import ModelPrice, UsageTokens, effective_cache_write_rate, effective_rates


class TokenPrices(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input: float
    output: float
    cache_read: float
    cache_write: float


class LongContextPrices(TokenPrices):
    threshold_tokens: float


class TierPrices(TokenPrices):
    long_context: LongContextPrices | None = Field(default=None, exclude_if=lambda value: value is None)


class ModelPricing(TierPrices):
    unit: Literal["usd_per_million_tokens"] = "usd_per_million_tokens"
    priority: TierPrices | None = Field(default=None, exclude_if=lambda value: value is None)
    flex: TierPrices | None = Field(default=None, exclude_if=lambda value: value is None)


def model_pricing(price: ModelPrice, *, source_rates: bool = False) -> ModelPricing:
    """Expose effective billing rates, including fallbacks, multipliers and tiers.

    Model sources only meter plain and cached input, not cache writes or service
    tiers. Other request paths use the stored cache-write rate for the active
    context/tier, falling back to 2x input only when no rate was published.
    """

    def rates(input_tokens: float, service_tier: str | None) -> TokenPrices:
        usage = UsageTokens(input_tokens=input_tokens, output_tokens=0)
        input_rate, cached_rate, output_rate = effective_rates(usage, price, service_tier=service_tier)
        return TokenPrices(
            input=input_rate,
            output=output_rate,
            cache_read=cached_rate,
            cache_write=(
                0.0
                if source_rates
                else effective_cache_write_rate(usage, price, service_tier=service_tier, input_rate=input_rate)
            ),
        )

    def tier(service_tier: str | None) -> TierPrices:
        short = rates(0, service_tier)
        long_context = None
        threshold = price.long_context_threshold_tokens
        if threshold is not None and threshold > 0:
            long_context = LongContextPrices(
                **rates(threshold + 1, service_tier).model_dump(), threshold_tokens=threshold
            )
        return TierPrices(**short.model_dump(), long_context=long_context)

    has_priority = (
        price.priority_multiplier is not None
        or (price.priority_input_per_1m is not None and price.priority_output_per_1m is not None)
        or (
            price.priority_long_context_input_per_1m is not None
            and price.priority_long_context_output_per_1m is not None
        )
    )
    has_flex = (price.flex_input_per_1m is not None and price.flex_output_per_1m is not None) or (
        price.flex_long_context_input_per_1m is not None and price.flex_long_context_output_per_1m is not None
    )
    standard = tier(None)
    return ModelPricing(
        **standard.model_dump(),
        priority=tier("priority") if has_priority and not source_rates else None,
        flex=tier("flex") if has_flex and not source_rates else None,
    )
