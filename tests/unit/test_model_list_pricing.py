from __future__ import annotations

import pytest

from app.core.usage.pricing import DEFAULT_PRICING_MODELS, ModelPrice, UsageTokens, calculate_cost_from_usage
from app.modules.proxy.model_pricing import model_pricing
from app.modules.proxy.schemas import ModelListItem

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("model, price", DEFAULT_PRICING_MODELS.items())
def test_catalog_rate_serialization_matches_every_static_price(model, price):
    published = model_pricing(price).model_dump(mode="json")
    for tier in (None, "priority", "flex"):
        rates = published.get(tier, published)
        long = rates.get("long_context")
        prompts = (1000,) if long is None else (1000, long["threshold_tokens"], long["threshold_tokens"] + 1)
        for input_tokens in prompts:
            usage = UsageTokens(input_tokens, 47, cached_input_tokens=113, cache_write_input_tokens=59)
            effective = long if long is not None and input_tokens > long["threshold_tokens"] else rates
            listed = (
                (input_tokens - 113 - 59) / 1_000_000 * effective["input"]
                + 113 / 1_000_000 * effective["cache_read"]
                + 47 / 1_000_000 * effective["output"]
                + 59 / 1_000_000 * effective["cache_write"]
            )
            assert listed == pytest.approx(calculate_cost_from_usage(usage, price, service_tier=tier), abs=1e-14), model


def test_missing_cache_read_rate_uses_the_billing_fallback_and_optional_tiers_are_absent():
    assert model_pricing(ModelPrice(input_per_1m=3, output_per_1m=5)).model_dump(mode="json") == {
        "unit": "usd_per_million_tokens",
        "input": 3,
        "output": 5,
        "cache_read": 3,
        "cache_write": 6,
    }


def test_unknown_model_omits_pricing_without_changing_other_fields():
    item = ModelListItem(id="unknown", owned_by="local", created=123)
    assert item.model_dump(mode="json") == {
        "id": "unknown",
        "object": "model",
        "owned_by": "local",
        "created": 123,
        "metadata": None,
    }
