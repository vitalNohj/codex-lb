"""Behavioral coverage for external-integration model price resolution.

Each test names a way the substring-glob table this module replaces produced a
wrong number rather than a missing one, or a way an over-eager resolver would
reintroduce that class of defect.
"""

from __future__ import annotations

import pytest

from app.core.usage.external_pricing.resolution import (
    Catalog,
    CatalogEntry,
    ResolutionOutcome,
    resolve_model_price,
)
from app.core.usage.pricing import ModelPrice

pytestmark = pytest.mark.unit


def _price(input_per_1m: float, output_per_1m: float) -> ModelPrice:
    return ModelPrice(input_per_1m=input_per_1m, output_per_1m=output_per_1m)


def _catalog(source: str, entries: dict[str, ModelPrice | None]) -> Catalog:
    return Catalog.from_entries(
        source,
        [CatalogEntry(model_id=model_id, price=price) for model_id, price in entries.items()],
    )


ANTHROPIC_CATALOG = _catalog(
    "openrouter",
    {
        "anthropic/claude-opus-4.5": _price(5.0, 25.0),
        "anthropic/claude-opus-4": _price(15.0, 75.0),
        "anthropic/claude-fable-5": _price(10.0, 50.0),
        "anthropic/claude-opus-4.5:batch": _price(2.5, 12.5),
    },
)


def test_exact_catalog_id_resolves_to_that_entry() -> None:
    resolution = resolve_model_price("anthropic/claude-opus-4.5", catalogs=[ANTHROPIC_CATALOG])

    assert resolution.outcome is ResolutionOutcome.RESOLVED
    assert resolution.catalog_model == "anthropic/claude-opus-4.5"
    assert resolution.price is not None
    assert resolution.price.input_per_1m == pytest.approx(5.0)


def test_version_punctuation_variants_resolve_to_the_same_price() -> None:
    """``claude-opus-4.5`` and ``claude-opus-4-5`` are one model.

    The glob table keyed on dashes, so the dotted spelling missed exact match and
    fell through to ``*claude-opus-4*`` -- Opus 4.0's rate, 3x the real one. Both
    spellings must reach the same entry or neither should.
    """

    dotted = resolve_model_price("anthropic/claude-opus-4.5", catalogs=[ANTHROPIC_CATALOG])
    dashed = resolve_model_price("anthropic/claude-opus-4-5", catalogs=[ANTHROPIC_CATALOG])

    assert dotted.outcome is ResolutionOutcome.RESOLVED
    assert dashed.outcome is ResolutionOutcome.RESOLVED
    assert dotted.price == dashed.price
    assert dashed.price is not None
    assert dashed.price.input_per_1m == pytest.approx(5.0)


def test_underscore_punctuation_variant_resolves_to_the_same_price() -> None:
    resolution = resolve_model_price("anthropic/claude-opus-4_5", catalogs=[ANTHROPIC_CATALOG])

    assert resolution.outcome is ResolutionOutcome.RESOLVED
    assert resolution.price is not None
    assert resolution.price.input_per_1m == pytest.approx(5.0)


def test_batch_variant_resolves_to_its_own_entry_not_the_base_rate() -> None:
    """A ``:batch`` id is billed at its own rate, half the base one."""

    resolution = resolve_model_price("anthropic/claude-opus-4.5:batch", catalogs=[ANTHROPIC_CATALOG])

    assert resolution.outcome is ResolutionOutcome.RESOLVED
    assert resolution.catalog_model == "anthropic/claude-opus-4.5:batch"
    assert resolution.price is not None
    assert resolution.price.input_per_1m == pytest.approx(2.5)


def test_unlisted_variant_suffix_never_inherits_the_base_model_price() -> None:
    """An unlisted variant is unresolved, never silently priced as its base.

    ``anthropic/claude-opus-4.5:turbo`` is not in the catalog. Falling back to the
    base entry would record a confident number for a rate nobody published.
    """

    resolution = resolve_model_price("anthropic/claude-opus-4.5:turbo", catalogs=[ANTHROPIC_CATALOG])

    assert resolution.outcome is ResolutionOutcome.UNRESOLVED
    assert resolution.price is None


def test_a_suffixed_model_name_does_not_match_a_shorter_catalog_stem() -> None:
    """``gpt-4o-mini-tts`` is a different model from ``gpt-4o-mini``.

    The glob ``*gpt-4o-mini*`` matched it and priced audio output at the text rate,
    4% of the real figure.
    """

    catalog = _catalog("openrouter", {"openai/gpt-4o-mini": _price(0.15, 0.6)})

    resolution = resolve_model_price("openai/gpt-4o-mini-tts", catalogs=[catalog])

    assert resolution.outcome is ResolutionOutcome.UNRESOLVED


def test_a_third_party_finetune_does_not_inherit_the_base_model_price() -> None:
    """``aion-labs/aion-rp-llama-3.1-8b`` is priced 8x the base Llama model.

    ``*llama-3.1-8b*`` matched it and recorded an eighth of the real rate.
    """

    catalog = _catalog("openrouter", {"meta-llama/llama-3.1-8b-instruct": _price(0.1, 0.1)})

    resolution = resolve_model_price("aion-labs/aion-rp-llama-3.1-8b", catalogs=[catalog])

    assert resolution.outcome is ResolutionOutcome.UNRESOLVED


def test_a_dated_release_does_not_inherit_a_shorter_family_price() -> None:
    """``cohere/command-r7b-12-2024`` is not ``cohere/command-r``.

    The glob mispriced it by 13.3x, the largest error measured. The trailing
    segment here is not a ``-YYYYMMDD`` release stamp, so nothing is removed.
    """

    catalog = _catalog("openrouter", {"cohere/command-r": _price(0.5, 1.5)})

    resolution = resolve_model_price("cohere/command-r7b-12-2024", catalogs=[catalog])

    assert resolution.outcome is ResolutionOutcome.UNRESOLVED


CLAUDE_VENDOR_CATALOG = _catalog(
    "openrouter",
    {
        "anthropic/claude-sonnet-4.5": _price(3.0, 15.0),
        "anthropic/claude-opus-4.1": _price(15.0, 75.0),
        "anthropic/claude-3.5-haiku": _price(0.8, 4.0),
    },
)


@pytest.mark.parametrize(
    ("incoming", "expected", "expected_input_per_1m"),
    [
        ("claude-sonnet-4-5-20250929", "anthropic/claude-sonnet-4.5", 3.0),
        ("claude-opus-4-1-20250805", "anthropic/claude-opus-4.1", 15.0),
        ("claude-3-5-haiku-20241022", "anthropic/claude-3.5-haiku", 0.8),
    ],
)
def test_a_dated_vendor_release_resolves_to_its_canonical_catalog_entry(
    incoming: str,
    expected: str,
    expected_input_per_1m: float,
) -> None:
    """CLIProxyAPI serves date-stamped Claude ids; catalogs publish undated ones.

    A trailing ``-YYYYMMDD`` names a release of one model, not a second model.
    Without this every CLIProxyAPI row rendered ``!!`` and accrued no cost quota,
    for ids whose real Anthropic rate the catalog does publish.
    """

    resolution = resolve_model_price(incoming, catalogs=[CLAUDE_VENDOR_CATALOG])

    assert resolution.outcome is ResolutionOutcome.RESOLVED
    assert resolution.catalog_model == expected
    assert resolution.price is not None
    assert resolution.price.input_per_1m == pytest.approx(expected_input_per_1m)


@pytest.mark.parametrize("incoming", ["cc/claude-sonnet-4-5-20250929", "cp-claude-sonnet-4-5-20250929"])
def test_a_prefixed_dated_release_resolves_through_the_prefix_then_the_date(incoming: str) -> None:
    resolution = resolve_model_price(
        incoming,
        catalogs=[CLAUDE_VENDOR_CATALOG],
        prefixes=[("cc/", True), ("cp-", True)],
    )

    assert resolution.outcome is ResolutionOutcome.RESOLVED
    assert resolution.catalog_model == "anthropic/claude-sonnet-4.5"
    assert resolution.price is not None
    assert resolution.price.input_per_1m == pytest.approx(3.0)


def test_a_dated_id_whose_shortened_form_matches_two_vendors_abstains() -> None:
    """Removing the date must not become a licence to guess.

    The shortened id re-enters resolution from the top, so it abstains exactly as
    the undated form would.
    """

    catalog = _catalog(
        "openrouter",
        {
            "vendor-a/model-x": _price(1.0, 1.0),
            "vendor-b/model-x": _price(9.0, 9.0),
        },
    )

    resolution = resolve_model_price("model-x-20250929", catalogs=[catalog])

    assert resolution.outcome is ResolutionOutcome.AMBIGUOUS
    assert resolution.price is None


@pytest.mark.parametrize(
    "incoming",
    [
        # Not eight digits.
        "claude-sonnet-4-5-2025092",
        # Eight digits that are not a calendar date.
        "claude-sonnet-4-5-20259999",
        "claude-sonnet-4-5-20250230",
        # A trailing segment that is not a date at all.
        "claude-sonnet-4-5-turbo",
    ],
)
def test_a_trailing_segment_that_is_not_a_release_date_is_never_removed(incoming: str) -> None:
    """Only a real ``-YYYYMMDD`` stamp is a release marker on the same model.

    Anything looser is the stem matching this module exists to remove.
    """

    resolution = resolve_model_price(incoming, catalogs=[CLAUDE_VENDOR_CATALOG])

    assert resolution.outcome is ResolutionOutcome.UNRESOLVED
    assert resolution.price is None


def test_an_exact_dated_catalog_id_wins_over_removing_its_date() -> None:
    """A catalog that lists the dated id itself is answering about that id."""

    catalog = _catalog(
        "openrouter",
        {
            "anthropic/claude-sonnet-4.5": _price(3.0, 15.0),
            "anthropic/claude-sonnet-4-5-20250929": _price(7.0, 21.0),
        },
    )

    resolution = resolve_model_price("anthropic/claude-sonnet-4-5-20250929", catalogs=[catalog])

    assert resolution.outcome is ResolutionOutcome.RESOLVED
    assert resolution.catalog_model == "anthropic/claude-sonnet-4-5-20250929"
    assert resolution.price is not None
    assert resolution.price.input_per_1m == pytest.approx(7.0)


def test_an_operator_alias_for_a_dated_id_wins_over_removing_its_date() -> None:
    resolution = resolve_model_price(
        "claude-sonnet-4-5-20250929",
        catalogs=[CLAUDE_VENDOR_CATALOG],
        aliases={"claude-sonnet-4-5-20250929": "anthropic/claude-opus-4.1"},
    )

    assert resolution.outcome is ResolutionOutcome.RESOLVED
    assert resolution.catalog_model == "anthropic/claude-opus-4.1"


def test_a_dated_variant_id_still_refuses_to_inherit_its_base_rate() -> None:
    """``:free``/``:batch`` are billed differently; the date changes nothing."""

    catalog = _catalog("openrouter", {"anthropic/claude-sonnet-4.5": _price(3.0, 15.0)})

    resolution = resolve_model_price("claude-sonnet-4-5-20250929:free", catalogs=[catalog])

    assert resolution.outcome is ResolutionOutcome.UNRESOLVED
    assert resolution.price is None


def test_bare_name_resolves_to_a_uniquely_vendor_qualified_catalog_id() -> None:
    resolution = resolve_model_price("claude-fable-5", catalogs=[ANTHROPIC_CATALOG])

    assert resolution.outcome is ResolutionOutcome.RESOLVED
    assert resolution.catalog_model == "anthropic/claude-fable-5"
    assert resolution.step == "vendor-qualified"


def test_bare_name_listed_by_two_vendors_abstains() -> None:
    """Two vendors publishing the same bare name price it differently.

    The live collisions differ by up to 2.8x, so picking either member is wrong
    most of the time it matters.
    """

    catalog = _catalog(
        "orcarouter",
        {
            "obsidian/qwen3.8-27b": _price(0.4, 4.21),
            "qwen/qwen3.8-27b": _price(0.33, 2.4),
        },
    )

    resolution = resolve_model_price("qwen3.8-27b", catalogs=[catalog])

    assert resolution.outcome is ResolutionOutcome.AMBIGUOUS
    assert resolution.price is None
    assert resolution.detail is not None
    assert "obsidian/qwen3.8-27b" in resolution.detail
    assert "qwen/qwen3.8-27b" in resolution.detail


def test_a_bare_name_prefers_the_unsuffixed_entry_over_its_own_variants() -> None:
    """A base id and its ``:free``/``:batch`` variants are not rival answers."""

    catalog = _catalog(
        "openrouter",
        {
            "vendor/model-x": _price(2.0, 4.0),
            "vendor/model-x:free": _price(0.0, 0.0),
        },
    )

    resolution = resolve_model_price("model-x", catalogs=[catalog])

    assert resolution.outcome is ResolutionOutcome.RESOLVED
    assert resolution.catalog_model == "vendor/model-x"


def test_a_free_model_resolves_to_its_published_zero_rate() -> None:
    """Zero is a published price, not a missing one."""

    catalog = _catalog("openrouter", {"vendor/model-x:free": _price(0.0, 0.0)})

    resolution = resolve_model_price("vendor/model-x:free", catalogs=[catalog])

    assert resolution.outcome is ResolutionOutcome.RESOLVED
    assert resolution.price is not None
    assert resolution.price.input_per_1m == pytest.approx(0.0)


def test_a_model_the_catalog_lists_without_token_rates_is_not_a_failure() -> None:
    """Per-request and router models have no token rate to find.

    Recording them as unresolved would retry a lookup that can never succeed and
    would mark them in the UI as though something were broken.
    """

    catalog = _catalog("orcarouter", {"orcarouter/fusion": None})

    resolution = resolve_model_price("orcarouter/fusion", catalogs=[catalog])

    assert resolution.outcome is ResolutionOutcome.NOT_TOKEN_PRICED
    assert resolution.catalog_model == "orcarouter/fusion"
    assert resolution.price is None


def test_serving_catalog_wins_over_the_pricing_reference_for_a_shared_id() -> None:
    """37 of 98 shared ids are priced differently on the two services.

    The catalog of the service that actually served the request is authoritative
    for it; the reference only fills gaps.
    """

    serving = _catalog("orcarouter", {"deepseek/deepseek-chat": _price(0.147, 0.3)})
    reference = _catalog("openrouter", {"deepseek/deepseek-chat": _price(0.2574, 0.6)})

    resolution = resolve_model_price("deepseek/deepseek-chat", catalogs=[serving, reference])

    assert resolution.outcome is ResolutionOutcome.RESOLVED
    assert resolution.catalog_source == "orcarouter"
    assert resolution.price is not None
    assert resolution.price.input_per_1m == pytest.approx(0.147)


def test_pricing_reference_fills_a_gap_the_serving_catalog_does_not_price() -> None:
    serving = _catalog("orcarouter", {"vendor/other": _price(1.0, 1.0)})
    reference = _catalog("openrouter", {"vendor/wanted": _price(3.0, 9.0)})

    resolution = resolve_model_price("vendor/wanted", catalogs=[serving, reference])

    assert resolution.outcome is ResolutionOutcome.RESOLVED
    assert resolution.catalog_source == "openrouter"


def test_an_exact_reference_match_beats_a_fuzzy_serving_match() -> None:
    """A precise answer anywhere beats a weaker answer in the preferred catalog."""

    serving = _catalog("orcarouter", {"vendor/claude-opus-4.5": _price(99.0, 99.0)})
    reference = _catalog("openrouter", {"claude-opus-4.5": _price(5.0, 25.0)})

    resolution = resolve_model_price("claude-opus-4.5", catalogs=[serving, reference])

    assert resolution.outcome is ResolutionOutcome.RESOLVED
    assert resolution.catalog_source == "openrouter"
    assert resolution.catalog_model == "claude-opus-4.5"


def test_a_bare_name_that_maps_to_different_catalog_identities_abstains() -> None:
    serving = _catalog("orcarouter", {"vendor-a/model-x": _price(1.0, 2.0)})
    reference = _catalog("openrouter", {"vendor-b/model-x": _price(9.0, 18.0)})

    resolution = resolve_model_price("model-x", catalogs=[serving, reference])

    assert resolution.outcome is ResolutionOutcome.AMBIGUOUS
    assert resolution.price is None
    assert resolution.detail is not None
    assert "vendor-a/model-x" in resolution.detail
    assert "vendor-b/model-x" in resolution.detail


def test_a_bare_name_with_the_same_identity_in_both_catalogs_prefers_serving() -> None:
    serving = _catalog("orcarouter", {"vendor/model-x": _price(1.0, 2.0)})
    reference = _catalog("openrouter", {"vendor/model-x": _price(9.0, 18.0)})

    resolution = resolve_model_price("model-x", catalogs=[serving, reference])

    assert resolution.outcome is ResolutionOutcome.RESOLVED
    assert resolution.catalog_model == "vendor/model-x"
    assert resolution.catalog_source == "orcarouter"
    assert resolution.price == _price(1.0, 2.0)


def test_punctuation_variants_across_catalogs_prefer_serving_identity() -> None:
    serving = _catalog("orcarouter", {"vendor/model.x": _price(1.0, 2.0)})
    reference = _catalog("openrouter", {"vendor/model-x": _price(9.0, 18.0)})

    resolution = resolve_model_price("vendor/model_x", catalogs=[serving, reference])

    assert resolution.outcome is ResolutionOutcome.RESOLVED
    assert resolution.catalog_model == "vendor/model.x"
    assert resolution.catalog_source == "orcarouter"
    assert resolution.price == _price(1.0, 2.0)


def test_configured_routing_prefix_is_stripped_before_catalog_lookup() -> None:
    """A CLIProxyAPI id resolves via its configured prefix, not by guesswork.

    ``cc/claude-fable-5`` is a local routing handle for an Anthropic model. The
    operator's prefix table is what says so.
    """

    resolution = resolve_model_price(
        "cc/claude-fable-5",
        catalogs=[ANTHROPIC_CATALOG],
        prefixes=[("cc/", True)],
    )

    assert resolution.outcome is ResolutionOutcome.RESOLVED
    assert resolution.catalog_model == "anthropic/claude-fable-5"
    assert resolution.step is not None
    assert resolution.step.startswith("prefix+")


def test_a_prefix_the_operator_forwards_verbatim_is_not_stripped() -> None:
    """A non-strip prefix is part of the upstream's own id.

    Removing it would ask the catalog about a model that does not exist there.
    """

    catalog = _catalog("orcarouter", {"orcarouter/auto": _price(1.0, 2.0), "auto": _price(50.0, 50.0)})

    resolution = resolve_model_price(
        "orcarouter/auto",
        catalogs=[catalog],
        prefixes=[("orcarouter/", False)],
    )

    assert resolution.outcome is ResolutionOutcome.RESOLVED
    assert resolution.catalog_model == "orcarouter/auto"


def test_prefix_removal_that_leads_nowhere_stays_unresolved() -> None:
    resolution = resolve_model_price(
        "cc/claude-nebula-9",
        catalogs=[ANTHROPIC_CATALOG],
        prefixes=[("cc/", True)],
    )

    assert resolution.outcome is ResolutionOutcome.UNRESOLVED


def test_an_explicit_operator_alias_takes_precedence_over_every_other_step() -> None:
    """The operator said what the id means; nothing may override that."""

    catalog = _catalog(
        "openrouter",
        {
            "custom-r1": _price(99.0, 99.0),
            "anthropic/claude-fable-5": _price(10.0, 50.0),
        },
    )

    resolution = resolve_model_price(
        "custom-r1",
        catalogs=[catalog],
        aliases={"custom-r1": "anthropic/claude-fable-5"},
    )

    assert resolution.outcome is ResolutionOutcome.RESOLVED
    assert resolution.catalog_model == "anthropic/claude-fable-5"


def test_a_configured_prefix_precedes_a_misleading_catalog_exact_match() -> None:
    catalog = _catalog(
        "openrouter",
        {
            "cc/foo": _price(99.0, 99.0),
            "vendor/foo": _price(1.0, 2.0),
        },
    )

    resolution = resolve_model_price(
        "cc/foo",
        catalogs=[catalog],
        prefixes=[("cc/", True)],
    )

    assert resolution.outcome is ResolutionOutcome.RESOLVED
    assert resolution.catalog_model == "vendor/foo"
    assert resolution.price == _price(1.0, 2.0)


def test_an_alias_applied_after_a_prefix_is_kept_in_the_recorded_provenance() -> None:
    """Provenance must name every step, including the operator's own alias.

    Recording only ``prefix+exact`` omits the strongest step in the chain, so a
    persisted price could no longer be explained by the record that holds it.
    """

    catalog = _catalog("openrouter", {"vendor/bar": _price(1.0, 2.0)})

    resolution = resolve_model_price(
        "cp-foo",
        catalogs=[catalog],
        aliases={"foo": "vendor/bar"},
        prefixes=[("cp-", True)],
    )

    assert resolution.outcome is ResolutionOutcome.RESOLVED
    assert resolution.catalog_model == "vendor/bar"
    assert resolution.step == "prefix+alias+exact"


def test_an_alias_applied_first_still_records_only_its_own_step() -> None:
    catalog = _catalog("openrouter", {"vendor/bar": _price(1.0, 2.0)})

    resolution = resolve_model_price("foo", catalogs=[catalog], aliases={"foo": "vendor/bar"})

    assert resolution.step == "alias+exact"


def test_an_alias_pointing_at_itself_terminates() -> None:
    """A self-referential alias must not spin the rewrite loop."""

    catalog = _catalog("openrouter", {"vendor/known": _price(1.0, 2.0)})

    resolution = resolve_model_price("loop", catalogs=[catalog], aliases={"loop": "loop"})

    assert resolution.outcome is ResolutionOutcome.UNRESOLVED


def test_an_alias_cycle_between_two_ids_terminates() -> None:
    catalog = _catalog("openrouter", {"vendor/known": _price(1.0, 2.0)})

    resolution = resolve_model_price(
        "alpha",
        catalogs=[catalog],
        aliases={"alpha": "beta", "beta": "alpha"},
    )

    assert resolution.outcome is ResolutionOutcome.UNRESOLVED


def test_resolution_is_case_insensitive_on_the_incoming_id() -> None:
    resolution = resolve_model_price("ANTHROPIC/Claude-Opus-4.5", catalogs=[ANTHROPIC_CATALOG])

    assert resolution.outcome is ResolutionOutcome.RESOLVED
    assert resolution.catalog_model == "anthropic/claude-opus-4.5"


def test_an_empty_model_id_is_unresolved_rather_than_an_error() -> None:
    assert resolve_model_price("", catalogs=[ANTHROPIC_CATALOG]).outcome is ResolutionOutcome.UNRESOLVED
    assert resolve_model_price("   ", catalogs=[ANTHROPIC_CATALOG]).outcome is ResolutionOutcome.UNRESOLVED


def test_no_catalogs_at_all_is_unresolved_rather_than_an_error() -> None:
    assert resolve_model_price("anything", catalogs=[]).outcome is ResolutionOutcome.UNRESOLVED


def test_ambiguity_ends_resolution_rather_than_falling_through_to_a_guess() -> None:
    """A weaker step cannot disambiguate what a stronger one could not."""

    catalog = _catalog(
        "openrouter",
        {
            "vendor-a/model.x": _price(1.0, 1.0),
            "vendor-a/model_x": _price(9.0, 9.0),
        },
    )

    resolution = resolve_model_price("vendor-a/model-x", catalogs=[catalog])

    assert resolution.outcome is ResolutionOutcome.AMBIGUOUS
