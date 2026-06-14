from __future__ import annotations

import pytest

from app.core.usage.pricing import ModelPrice, UsageTokens
from app.core.usage.runtime_pricing import (
    calculate_reference_cost,
    get_reference_pricing_for_model,
    get_runtime_pricing_registry,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clear_registry():
    registry = get_runtime_pricing_registry()
    registry.clear()
    yield
    registry.clear()


def test_runtime_pricing_preferred_for_model_absent_from_static_table() -> None:
    get_runtime_pricing_registry().update_models(
        [("vendor/model-x", ModelPrice(input_per_1m=0.8, output_per_1m=4.0))]
    )
    price = get_reference_pricing_for_model("vendor/model-x")
    assert price is not None
    assert price.input_per_1m == pytest.approx(0.8)
    assert price.output_per_1m == pytest.approx(4.0)


def test_static_table_used_when_runtime_price_unavailable() -> None:
    # gpt-4o exists in the static DEFAULT_PRICING_MODELS table.
    price = get_reference_pricing_for_model("gpt-4o")
    assert price is not None
    assert price.input_per_1m == pytest.approx(2.50)


def test_free_variant_resolves_to_paid_pricing() -> None:
    get_runtime_pricing_registry().update_models(
        [("vendor/model-x", ModelPrice(input_per_1m=0.8, output_per_1m=4.0))]
    )
    price = get_reference_pricing_for_model("vendor/model-x:free")
    assert price is not None
    assert price.input_per_1m == pytest.approx(0.8)


def test_free_model_without_paid_equivalent_returns_none() -> None:
    assert get_reference_pricing_for_model("totally-unknown-model:free") is None


def test_calculate_reference_cost_for_free_model() -> None:
    get_runtime_pricing_registry().update_models(
        [("vendor/model-x", ModelPrice(input_per_1m=0.8, output_per_1m=4.0))]
    )
    cost = calculate_reference_cost(
        "vendor/model-x:free",
        UsageTokens(input_tokens=10_000, output_tokens=2_000, cached_input_tokens=0),
    )
    # 10000 * 0.8/1e6 + 2000 * 4.0/1e6 = 0.008 + 0.008
    assert cost == pytest.approx(0.016)


def test_calculate_reference_cost_none_when_unresolvable() -> None:
    cost = calculate_reference_cost(
        "totally-unknown-model:free",
        UsageTokens(input_tokens=10_000, output_tokens=2_000),
    )
    assert cost is None


def test_calculate_reference_cost_none_without_usage() -> None:
    assert calculate_reference_cost("gpt-4o", None) is None
