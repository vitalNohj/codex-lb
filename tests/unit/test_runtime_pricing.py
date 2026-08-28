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


def test_owner_that_stops_listing_an_id_releases_the_unqualified_entry() -> None:
    """Ownership must not outlive the listing that created it.

    ``update_models`` receives the owner's current catalogue, so an id the owner
    no longer lists is gone from that source. Merging the provider key space made
    the owner look like a live publisher forever, which froze its last price in
    the unqualified overlay that OmniRoute and Ollama dispatch read.
    """

    registry = get_runtime_pricing_registry()
    registry.update_models(
        [("vendor/dropped", ModelPrice(input_per_1m=9.0, output_per_1m=9.0))],
        provider="orcarouter",
    )
    # The owner refreshes and no longer lists the id.
    registry.update_models(
        [("vendor/still-here", ModelPrice(input_per_1m=5.0, output_per_1m=5.0))],
        provider="orcarouter",
    )
    registry.update_models(
        [("vendor/dropped", ModelPrice(input_per_1m=1.0, output_per_1m=1.0))],
        provider="openrouter",
    )

    released = get_reference_pricing_for_model("vendor/dropped")

    assert released is not None
    assert released.input_per_1m == pytest.approx(1.0)
    # The former owner's retired 9.0 is gone, not merely shadowed: an
    # OrcaRouter-qualified lookup now inherits the live OpenRouter listing.
    former_owner_price = get_reference_pricing_for_model("vendor/dropped", provider="orcarouter")
    assert former_owner_price is not None
    assert former_owner_price.input_per_1m == pytest.approx(1.0)
    # The id the owner still publishes is untouched by the eviction.
    still_here = get_reference_pricing_for_model("vendor/still-here", provider="orcarouter")
    assert still_here is not None
    assert still_here.input_per_1m == pytest.approx(5.0)


def test_delisted_id_no_other_provider_publishes_resolves_to_no_price() -> None:
    """A delisted id must have no runtime price at all, not a dead one.

    Releasing ownership alone left the last value in the unqualified overlay, so
    ``_log_omniroute_request`` and ``_log_ollama_request`` kept persisting a
    ``reference_cost_usd`` that no live listing backed. An id no source currently
    lists must resolve to no price rather than a retired one.
    """

    registry = get_runtime_pricing_registry()
    registry.update_models(
        [
            ("vendor/gone", ModelPrice(input_per_1m=9.0, output_per_1m=9.0)),
            ("vendor/kept", ModelPrice(input_per_1m=4.0, output_per_1m=4.0)),
        ],
        provider="orcarouter",
    )
    registry.update_models(
        [("vendor/kept", ModelPrice(input_per_1m=4.0, output_per_1m=4.0))],
        provider="orcarouter",
    )

    assert get_reference_pricing_for_model("vendor/gone") is None
    assert get_reference_pricing_for_model("vendor/gone", provider="orcarouter") is None
    assert (
        calculate_reference_cost(
            "vendor/gone",
            UsageTokens(input_tokens=1_000_000, output_tokens=1_000_000, cached_input_tokens=0),
        )
        is None
    )
    kept = get_reference_pricing_for_model("vendor/kept")
    assert kept is not None
    assert kept.input_per_1m == pytest.approx(4.0)


def test_listed_id_whose_price_stops_parsing_keeps_its_last_parsed_value() -> None:
    """An upstream pricing-shape change is not a delisting.

    Eviction used to key on the priced subset of a refresh, so a listing whose
    ``pricing`` objects all failed to parse read as an authoritative empty
    catalogue and wiped that source's entire runtime price set, zeroing every
    savings figure derived from it. The source still lists the id, so its last
    successfully parsed price must survive.
    """

    registry = get_runtime_pricing_registry()
    registry.update_models(
        [
            ("vendor/unparseable", ModelPrice(input_per_1m=10.0, output_per_1m=20.0)),
            ("vendor/also-listed", ModelPrice(input_per_1m=3.0, output_per_1m=6.0)),
        ],
        provider="orcarouter",
    )
    # The next refresh still lists both ids, but upstream renamed the pricing
    # fields, so every entry parses to no price.
    registry.update_models(
        [("vendor/unparseable", None), ("vendor/also-listed", None)],
        provider="orcarouter",
    )

    unqualified = get_reference_pricing_for_model("vendor/unparseable")
    assert unqualified is not None
    assert unqualified.input_per_1m == pytest.approx(10.0)
    assert unqualified.output_per_1m == pytest.approx(20.0)
    owner_price = get_reference_pricing_for_model("vendor/unparseable", provider="orcarouter")
    assert owner_price is not None
    assert owner_price.input_per_1m == pytest.approx(10.0)
    sibling = get_reference_pricing_for_model("vendor/also-listed", provider="orcarouter")
    assert sibling is not None
    assert sibling.input_per_1m == pytest.approx(3.0)


def test_id_listed_only_with_an_unparseable_price_never_gains_a_price() -> None:
    """Preserving a last parsed value must not invent one that never existed."""

    registry = get_runtime_pricing_registry()
    registry.update_models([("vendor/never-priced", None)], provider="orcarouter")

    assert get_reference_pricing_for_model("vendor/never-priced") is None
    assert get_reference_pricing_for_model("vendor/never-priced", provider="orcarouter") is None


def test_listed_id_with_a_changed_price_is_replaced_immediately() -> None:
    """A newer authoritative price always wins for its own source."""

    registry = get_runtime_pricing_registry()
    registry.update_models(
        [("vendor/repriced", ModelPrice(input_per_1m=10.0, output_per_1m=20.0))],
        provider="orcarouter",
    )
    registry.update_models(
        [("vendor/repriced", ModelPrice(input_per_1m=2.0, output_per_1m=4.0))],
        provider="orcarouter",
    )

    owner_price = get_reference_pricing_for_model("vendor/repriced", provider="orcarouter")
    assert owner_price is not None
    assert owner_price.input_per_1m == pytest.approx(2.0)
    assert owner_price.output_per_1m == pytest.approx(4.0)
    unqualified = get_reference_pricing_for_model("vendor/repriced")
    assert unqualified is not None
    assert unqualified.input_per_1m == pytest.approx(2.0)


def test_a_source_that_stops_listing_an_id_removes_only_its_own_entry() -> None:
    """Dropping an id from one source says nothing about another source."""

    registry = get_runtime_pricing_registry()
    registry.update_models(
        [("vendor/two-sources", ModelPrice(input_per_1m=9.0, output_per_1m=9.0))],
        provider="orcarouter",
    )
    registry.update_models(
        [("vendor/two-sources", ModelPrice(input_per_1m=1.0, output_per_1m=1.0))],
        provider="openrouter",
    )
    # OrcaRouter (the unqualified owner) stops listing it entirely.
    registry.update_models([("vendor/orca-other", None)], provider="orcarouter")

    orcarouter_price = get_reference_pricing_for_model("vendor/two-sources", provider="orcarouter")
    assert orcarouter_price is not None
    assert orcarouter_price.input_per_1m == pytest.approx(1.0)
    openrouter_price = get_reference_pricing_for_model("vendor/two-sources", provider="openrouter")
    assert openrouter_price is not None
    assert openrouter_price.input_per_1m == pytest.approx(1.0)
    unqualified = get_reference_pricing_for_model("vendor/two-sources")
    assert unqualified is not None
    assert unqualified.input_per_1m == pytest.approx(1.0)


def test_empty_refresh_evicts_only_the_refreshing_providers_ids() -> None:
    """An empty listing must not disturb another still-publishing provider."""

    registry = get_runtime_pricing_registry()
    registry.update_models(
        [("vendor/openrouter-only", ModelPrice(input_per_1m=2.0, output_per_1m=2.0))],
        provider="openrouter",
    )
    registry.update_models(
        [("vendor/orcarouter-only", ModelPrice(input_per_1m=7.0, output_per_1m=7.0))],
        provider="orcarouter",
    )
    # OrcaRouter's next refresh lists nothing at all.
    registry.update_models([], provider="orcarouter")

    assert get_reference_pricing_for_model("vendor/orcarouter-only") is None
    survivor = get_reference_pricing_for_model("vendor/openrouter-only")
    assert survivor is not None
    assert survivor.input_per_1m == pytest.approx(2.0)


def test_a_live_owner_still_blocks_another_provider_from_redefining_a_shared_id() -> None:
    """Releasing stale ownership must not reopen last-writer-wins."""

    registry = get_runtime_pricing_registry()
    registry.update_models(
        [("vendor/contested", ModelPrice(input_per_1m=1.0, output_per_1m=1.0))],
        provider="openrouter",
    )
    # The owner keeps publishing the id on its next refresh.
    registry.update_models(
        [("vendor/contested", ModelPrice(input_per_1m=2.0, output_per_1m=2.0))],
        provider="openrouter",
    )
    registry.update_models(
        [("vendor/contested", ModelPrice(input_per_1m=9.0, output_per_1m=9.0))],
        provider="orcarouter",
    )

    unqualified = get_reference_pricing_for_model("vendor/contested")

    assert unqualified is not None
    assert unqualified.input_per_1m == pytest.approx(2.0)
    challenger = get_reference_pricing_for_model("vendor/contested", provider="orcarouter")
    assert challenger is not None
    assert challenger.input_per_1m == pytest.approx(9.0)


def test_delisting_does_not_evict_an_id_another_provider_still_publishes() -> None:
    """The owner's eviction hands a shared id to a live publisher, not to nothing."""

    registry = get_runtime_pricing_registry()
    registry.update_models(
        [("vendor/shared-live", ModelPrice(input_per_1m=9.0, output_per_1m=9.0))],
        provider="orcarouter",
    )
    registry.update_models(
        [("vendor/shared-live", ModelPrice(input_per_1m=1.0, output_per_1m=1.0))],
        provider="openrouter",
    )
    # OrcaRouter (the unqualified owner) delists it; OpenRouter still lists it.
    registry.update_models([], provider="orcarouter")

    unqualified = get_reference_pricing_for_model("vendor/shared-live")
    assert unqualified is not None
    assert unqualified.input_per_1m == pytest.approx(1.0)
    openrouter_price = get_reference_pricing_for_model("vendor/shared-live", provider="openrouter")
    assert openrouter_price is not None
    assert openrouter_price.input_per_1m == pytest.approx(1.0)
