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


def test_each_provider_resolves_its_own_price_for_a_shared_model_id() -> None:
    """Two providers listing the same id must not overwrite each other.

    OpenRouter and OrcaRouter both publish ids such as ``deepseek/deepseek-chat``
    at their own list prices. With one unqualified key space, whichever refresh
    ran last defined the entry, so a request served by one provider could be
    priced from the other's list price and record a wrong ``reference_cost_usd``.
    """

    registry = get_runtime_pricing_registry()
    registry.update_models(
        [("deepseek/deepseek-chat", ModelPrice(input_per_1m=1.0, output_per_1m=2.0))],
        provider="openrouter",
    )
    registry.update_models(
        [("deepseek/deepseek-chat", ModelPrice(input_per_1m=10.0, output_per_1m=20.0))],
        provider="orcarouter",
    )

    usage = UsageTokens(input_tokens=1_000_000, output_tokens=1_000_000, cached_input_tokens=0)
    openrouter_cost = calculate_reference_cost("deepseek/deepseek-chat", usage, provider="openrouter")
    orcarouter_cost = calculate_reference_cost("deepseek/deepseek-chat", usage, provider="orcarouter")

    assert openrouter_cost == pytest.approx(3.0)
    assert orcarouter_cost == pytest.approx(30.0)


def test_provider_qualified_price_survives_a_later_refresh_by_another_provider() -> None:
    registry = get_runtime_pricing_registry()
    registry.update_models(
        [("vendor/shared", ModelPrice(input_per_1m=1.0, output_per_1m=1.0))],
        provider="openrouter",
    )
    registry.update_models(
        [("vendor/shared", ModelPrice(input_per_1m=9.0, output_per_1m=9.0))],
        provider="orcarouter",
    )
    # A second OrcaRouter refresh (the "last writer") must not move OpenRouter.
    registry.update_models(
        [("vendor/shared", ModelPrice(input_per_1m=9.5, output_per_1m=9.5))],
        provider="orcarouter",
    )

    openrouter_price = get_reference_pricing_for_model("vendor/shared", provider="openrouter")
    orcarouter_price = get_reference_pricing_for_model("vendor/shared", provider="orcarouter")

    assert openrouter_price is not None and openrouter_price.input_per_1m == pytest.approx(1.0)
    assert orcarouter_price is not None and orcarouter_price.input_per_1m == pytest.approx(9.5)


def test_free_variant_resolves_the_serving_providers_paid_price() -> None:
    registry = get_runtime_pricing_registry()
    registry.update_models(
        [("vendor/shared", ModelPrice(input_per_1m=0.8, output_per_1m=4.0))],
        provider="openrouter",
    )
    registry.update_models(
        [("vendor/shared", ModelPrice(input_per_1m=8.0, output_per_1m=40.0))],
        provider="orcarouter",
    )

    cost = calculate_reference_cost(
        "vendor/shared:free",
        UsageTokens(input_tokens=10_000, output_tokens=2_000, cached_input_tokens=0),
        provider="openrouter",
    )

    assert cost == pytest.approx(0.016)


def test_unqualified_lookup_still_resolves_a_runtime_price() -> None:
    """Callers without a provider keep the pre-existing overlay behavior."""

    get_runtime_pricing_registry().update_models(
        [("vendor/only-here", ModelPrice(input_per_1m=0.5, output_per_1m=1.5))],
        provider="orcarouter",
    )

    price = get_reference_pricing_for_model("vendor/only-here")

    assert price is not None
    assert price.input_per_1m == pytest.approx(0.5)


def test_provider_falls_back_to_another_providers_listing_when_it_publishes_none() -> None:
    get_runtime_pricing_registry().update_models(
        [("vendor/only-openrouter", ModelPrice(input_per_1m=2.0, output_per_1m=4.0))],
        provider="openrouter",
    )

    price = get_reference_pricing_for_model("vendor/only-openrouter", provider="orcarouter")

    assert price is not None
    assert price.input_per_1m == pytest.approx(2.0)


def test_second_provider_listing_a_shared_id_does_not_redefine_the_unqualified_price() -> None:
    """A provider-less lookup must not swing to whichever refresh ran last.

    ``_log_omniroute_request`` and ``_log_ollama_request`` resolve reference cost
    without naming a provider, so an overwrite here persisted another provider's
    list price as ``reference_cost_usd``.
    """

    registry = get_runtime_pricing_registry()
    registry.update_models(
        [("vendor/shared-id", ModelPrice(input_per_1m=1.0, output_per_1m=2.0))],
        provider="openrouter",
    )
    registry.update_models(
        [("vendor/shared-id", ModelPrice(input_per_1m=9.0, output_per_1m=9.0))],
        provider="orcarouter",
    )

    unqualified = get_reference_pricing_for_model("vendor/shared-id")
    openrouter_price = get_reference_pricing_for_model("vendor/shared-id", provider="openrouter")
    orcarouter_price = get_reference_pricing_for_model("vendor/shared-id", provider="orcarouter")

    assert unqualified is not None
    assert unqualified.input_per_1m == pytest.approx(1.0)
    # Each provider still resolves to its own published price.
    assert openrouter_price is not None
    assert openrouter_price.input_per_1m == pytest.approx(1.0)
    assert orcarouter_price is not None
    assert orcarouter_price.input_per_1m == pytest.approx(9.0)


def test_owning_provider_refresh_updates_the_unqualified_price() -> None:
    """A later refresh by the id's owner must not serve a retired list price.

    Refusing every overwrite froze the unqualified overlay for the process
    lifetime, so ``_log_omniroute_request`` and ``_log_ollama_request`` persisted
    a ``reference_cost_usd`` the publishing provider had already changed.
    """

    registry = get_runtime_pricing_registry()
    registry.update_models(
        [("vendor/owned", ModelPrice(input_per_1m=1.0, output_per_1m=2.0))],
        provider="orcarouter",
    )
    registry.update_models(
        [("vendor/owned", ModelPrice(input_per_1m=3.0, output_per_1m=6.0))],
        provider="orcarouter",
    )

    unqualified = get_reference_pricing_for_model("vendor/owned")
    owner_price = get_reference_pricing_for_model("vendor/owned", provider="orcarouter")

    assert unqualified is not None
    assert unqualified.input_per_1m == pytest.approx(3.0)
    assert unqualified.output_per_1m == pytest.approx(6.0)
    assert owner_price is not None
    assert owner_price.input_per_1m == pytest.approx(3.0)


def test_owner_refresh_after_another_provider_claims_nothing_keeps_ownership() -> None:
    """A non-owner refresh must never take over an already claimed id."""

    registry = get_runtime_pricing_registry()
    registry.update_models(
        [("vendor/claimed", ModelPrice(input_per_1m=1.0, output_per_1m=2.0))],
        provider="openrouter",
    )
    registry.update_models(
        [("vendor/claimed", ModelPrice(input_per_1m=9.0, output_per_1m=9.0))],
        provider="orcarouter",
    )
    registry.update_models(
        [("vendor/claimed", ModelPrice(input_per_1m=5.0, output_per_1m=7.0))],
        provider="openrouter",
    )

    unqualified = get_reference_pricing_for_model("vendor/claimed")
    orcarouter_price = get_reference_pricing_for_model("vendor/claimed", provider="orcarouter")

    assert unqualified is not None
    assert unqualified.input_per_1m == pytest.approx(5.0)
    assert orcarouter_price is not None
    assert orcarouter_price.input_per_1m == pytest.approx(9.0)
