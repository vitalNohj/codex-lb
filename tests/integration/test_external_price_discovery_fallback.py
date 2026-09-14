"""A discovered model with no price of its own must still reach a price source.

This is the path a newly integrated provider actually takes. Its own listing
carries no rates - OpenCode Go's ``/models`` publishes ``{id, object, created,
owned_by}`` and nothing else, and CLIProxyAPI publishes no rates by design - so
every id it serves arrives at the resolver unpriced and the answer has to come
from a pricing reference.

Two defects made that fail, and they are independent:

* the only pricing reference was OpenRouter, so an id OpenRouter does not list
  was unpriced even when the operator's own OrcaRouter integration listed it,
  and an OpenRouter outage removed the entire fallback; and
* a provider that was declared externally priced without registering a
  serving-context loader read as a permanently unavailable serving catalog,
  which held the references off on behalf of a catalog that was never coming.

Everything here runs against the real resolution, store, and service layers with
catalogs supplied from fixtures. Nothing reaches the network and nothing touches
a real integration's settings.
"""

from __future__ import annotations

import asyncio

import pytest

from app.core.usage.external_pricing import service as pricing_service
from app.core.usage.external_pricing.catalogs import (
    OPENROUTER_REFERENCE_SOURCE,
    ORCAROUTER_REFERENCE_SOURCE,
    Catalog,
    CatalogEntry,
    parse_openai_style_catalog,
)
from app.core.usage.external_pricing.providers import EXTERNAL_PRICED_PROVIDERS
from app.core.usage.external_pricing.resolution import UnpricedReason
from app.core.usage.external_pricing.service import (
    CatalogAvailability,
    ServingContext,
    calculated_cost_for_request,
    get_lookup_coordinator,
    load_orcarouter_reference,
    register_serving_context_loader,
    registered_serving_context_providers,
    reset_serving_context_loaders,
)
from app.core.usage.pricing import ModelPrice, UsageTokens
from app.db.models import ExternalPriceStatus

pytestmark = pytest.mark.integration


ONE_MILLION = UsageTokens(input_tokens=1_000_000, output_tokens=1_000_000, cached_input_tokens=0)

# The provider under test stands in for any integration that serves models and
# publishes no rates for them. ``cliproxy`` already has exactly that shape in
# this build, so using it keeps these tests about the pricing machinery rather
# than about one pending integration's registration.
CATALOGLESS_PROVIDER = "cliproxy"


def _catalog(source: str, entries: dict[str, ModelPrice | None]) -> Catalog:
    return Catalog.from_entries(
        source,
        [CatalogEntry(model_id=model_id, price=price) for model_id, price in entries.items()],
    )


def _unpriced_catalog(source: str, model_ids: tuple[str, ...]) -> Catalog:
    """A listing that names models and publishes no rate fields at all.

    The shape a subscription provider's ``/models`` returns. It is not a failure
    and not an empty catalog, and the difference decides whether the references
    are consulted.
    """

    return Catalog.from_entries(
        source,
        [
            CatalogEntry(model_id=model_id, price=None, unpriced_reason=UnpricedReason.NO_TOKEN_RATE)
            for model_id in model_ids
        ],
    )


@pytest.fixture(autouse=True)
def _clean_loaders():
    reset_serving_context_loaders()
    yield
    reset_serving_context_loaders()


@pytest.fixture(autouse=True)
def _offline_reference(monkeypatch):
    """No test here may reach the real OpenRouter catalog.

    A test that did would be measuring the internet. Each test that needs a
    reference installs its own with ``_install_reference``.
    """

    async def _fetch():
        return None

    monkeypatch.setattr(pricing_service, "_load_reference_catalog", _fetch)


def _install_reference(monkeypatch, catalog: Catalog | None) -> dict[str, int]:
    calls = {"count": 0}

    async def _fetch():
        calls["count"] += 1
        return catalog

    monkeypatch.setattr(pricing_service, "_load_reference_catalog", _fetch)
    return calls


def _install_serving(
    provider: str,
    *,
    catalog: Catalog | None,
    publishes_price_catalog: bool = True,
    prefixes: tuple[tuple[str, bool], ...] = (),
    aliases: dict[str, str] | None = None,
    enabled: bool = True,
) -> dict[str, int]:
    calls = {"count": 0}

    async def _loader(_provider: str) -> ServingContext:
        calls["count"] += 1
        if not enabled:
            return ServingContext.disabled(aliases=aliases or {}, prefixes=prefixes)
        return ServingContext(
            catalog=catalog,
            aliases=aliases or {},
            prefixes=prefixes,
            publishes_price_catalog=publishes_price_catalog,
        )

    register_serving_context_loader(provider, _loader)
    return calls


def _install_failing_serving(provider: str) -> dict[str, int]:
    calls = {"count": 0}

    async def _loader(_provider: str) -> ServingContext:
        calls["count"] += 1
        raise RuntimeError(f"{provider} /models timed out")

    register_serving_context_loader(provider, _loader)
    return calls


async def _settle(provider: str, model: str, *, usage: UsageTokens | None = ONE_MILLION):
    """Drive one id to a persisted conclusion and report what it concluded.

    Two calls on purpose: the first is the first sighting that dispatches the
    background lookup, the second is what a later request actually sees. That is
    the end-user path, and asserting on the second call is what keeps these tests
    about observable behavior rather than about the coordinator's internals.
    """

    await calculated_cost_for_request(provider=provider, model=model, usage=usage)
    await get_lookup_coordinator().drain()
    return await calculated_cost_for_request(provider=provider, model=model, usage=usage)


# --------------------------------------------------------------------------
# Discovery reaching each price source
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_discovered_model_without_a_price_resolves_from_openrouter(db_setup, monkeypatch) -> None:
    """The captain's primary path: no rate of our own, so OpenRouter supplies it."""

    del db_setup
    _install_reference(monkeypatch, _catalog(OPENROUTER_REFERENCE_SOURCE, {"z-ai/glm-5.3": ModelPrice(0.6, 2.2)}))
    _install_serving(
        CATALOGLESS_PROVIDER,
        catalog=None,
        publishes_price_catalog=False,
        prefixes=(("go/", True),),
    )

    cost, status = await _settle(CATALOGLESS_PROVIDER, "go/glm-5.3")

    assert status is ExternalPriceStatus.RESOLVED
    assert cost is not None
    assert cost.cost_usd == pytest.approx(2.8)
    assert cost.catalog_source == OPENROUTER_REFERENCE_SOURCE
    assert cost.catalog_model == "z-ai/glm-5.3"


@pytest.mark.asyncio
async def test_orcarouter_prices_a_model_openrouter_does_not_list(db_setup, monkeypatch) -> None:
    """The captain's stated fallback. OpenRouter answered; it just does not list it."""

    del db_setup
    _install_reference(monkeypatch, _catalog(OPENROUTER_REFERENCE_SOURCE, {"openai/gpt-4o": ModelPrice(2.5, 10.0)}))
    _install_serving("orcarouter", catalog=_catalog("orcarouter", {"z-ai/glm-5.3": ModelPrice(0.6, 2.2)}))
    _install_serving(
        CATALOGLESS_PROVIDER,
        catalog=None,
        publishes_price_catalog=False,
        prefixes=(("go/", True),),
    )

    cost, status = await _settle(CATALOGLESS_PROVIDER, "go/glm-5.3")

    assert status is ExternalPriceStatus.RESOLVED
    assert cost is not None
    assert cost.cost_usd == pytest.approx(2.8)
    # Borrowed as a reference, not serving. The distinct label is what stops a
    # later pass treating OrcaRouter as authoritative over an id it never billed.
    assert cost.catalog_source == ORCAROUTER_REFERENCE_SOURCE


@pytest.mark.asyncio
async def test_orcarouter_still_answers_while_openrouter_is_unreachable(db_setup, monkeypatch) -> None:
    """An outage of one reference must not remove the other."""

    del db_setup
    _install_reference(monkeypatch, None)
    _install_serving("orcarouter", catalog=_catalog("orcarouter", {"z-ai/glm-5.3": ModelPrice(0.6, 2.2)}))
    _install_serving(CATALOGLESS_PROVIDER, catalog=None, publishes_price_catalog=False, prefixes=(("go/", True),))

    cost, status = await _settle(CATALOGLESS_PROVIDER, "go/glm-5.3")

    assert status is ExternalPriceStatus.RESOLVED
    assert cost is not None
    assert cost.catalog_source == ORCAROUTER_REFERENCE_SOURCE


@pytest.mark.asyncio
async def test_openrouter_wins_when_both_references_list_the_model(db_setup, monkeypatch) -> None:
    """Precedence is fixed, so the same id cannot price differently run to run.

    Both references list ``z-ai/glm-5.3`` at different rates. Without a defined
    order the recorded price would depend on which catalog happened to be built
    first, which is a silently wrong number rather than a missing one.
    """

    del db_setup
    _install_reference(monkeypatch, _catalog(OPENROUTER_REFERENCE_SOURCE, {"z-ai/glm-5.3": ModelPrice(0.6, 2.2)}))
    _install_serving("orcarouter", catalog=_catalog("orcarouter", {"z-ai/glm-5.3": ModelPrice(9.0, 90.0)}))
    _install_serving(CATALOGLESS_PROVIDER, catalog=None, publishes_price_catalog=False, prefixes=(("go/", True),))

    cost, status = await _settle(CATALOGLESS_PROVIDER, "go/glm-5.3")

    assert status is ExternalPriceStatus.RESOLVED
    assert cost is not None
    assert cost.catalog_source == OPENROUTER_REFERENCE_SOURCE
    assert cost.cost_usd == pytest.approx(2.8)


@pytest.mark.asyncio
async def test_neither_reference_has_it_so_the_price_stays_unknown(db_setup, monkeypatch) -> None:
    """Availability is not a price. Unknown is preserved, never invented."""

    del db_setup
    _install_reference(monkeypatch, _catalog(OPENROUTER_REFERENCE_SOURCE, {"openai/gpt-4o": ModelPrice(2.5, 10.0)}))
    _install_serving("orcarouter", catalog=_catalog("orcarouter", {"deepseek/deepseek-chat": ModelPrice(0.27, 1.1)}))
    _install_serving(CATALOGLESS_PROVIDER, catalog=None, publishes_price_catalog=False, prefixes=(("go/", True),))

    cost, status = await _settle(CATALOGLESS_PROVIDER, "go/hy3-preview")

    assert cost is None
    assert status is ExternalPriceStatus.UNRESOLVED
    record = await _record(CATALOGLESS_PROVIDER, "go/hy3-preview")
    assert record is not None
    assert record.price is None
    # The detail names the id that failed, so an operator reading the row can
    # tell "no source lists this" from "a source could not be reached".
    assert record.detail is not None and "hy3-preview" in record.detail


@pytest.mark.asyncio
async def test_an_orcarouter_outage_is_not_read_as_an_absent_price(db_setup, monkeypatch) -> None:
    """A source that failed to answer must not be recorded as having said no."""

    del db_setup
    _install_reference(monkeypatch, _catalog(OPENROUTER_REFERENCE_SOURCE, {"openai/gpt-4o": ModelPrice(2.5, 10.0)}))
    orca_calls = _install_failing_serving("orcarouter")
    _install_serving(CATALOGLESS_PROVIDER, catalog=None, publishes_price_catalog=False, prefixes=(("go/", True),))

    cost, status = await _settle(CATALOGLESS_PROVIDER, "go/glm-5.3")

    assert orca_calls["count"] >= 1
    assert cost is None
    assert status is ExternalPriceStatus.UNRESOLVED
    record = await _record(CATALOGLESS_PROVIDER, "go/glm-5.3")
    assert record is not None
    # Retryable, so the id is re-asked once OrcaRouter recovers rather than
    # being settled against a source that never spoke.
    assert record.next_retry_at is not None


# --------------------------------------------------------------------------
# The registration gap
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_eligible_provider_without_a_loader_still_gets_a_reference_price(db_setup, monkeypatch) -> None:
    """Declaring a provider externally priced must be enough to price it.

    A provider added to ``EXTERNAL_PRICED_PROVIDERS`` without a serving-context
    loader previously read as a serving catalog that could not be fetched. That
    is indistinguishable from an outage, so the references were withheld and
    every one of the provider's models stayed unpriced permanently while the
    operator was told a catalog was unavailable.
    """

    del db_setup
    _install_reference(monkeypatch, _catalog(OPENROUTER_REFERENCE_SOURCE, {"z-ai/glm-5.3": ModelPrice(0.6, 2.2)}))

    assert CATALOGLESS_PROVIDER not in registered_serving_context_providers()

    cost, status = await _settle(CATALOGLESS_PROVIDER, "z-ai/glm-5.3")

    assert status is ExternalPriceStatus.RESOLVED
    assert cost is not None
    assert cost.catalog_source == OPENROUTER_REFERENCE_SOURCE


def test_every_externally_priced_provider_declares_how_to_be_consulted() -> None:
    """The registration gap above is caught at its source, not at a price row.

    ``EXTERNAL_PRICED_PROVIDERS`` and the registered loaders are two lists that
    must agree. They are edited in different files by different changes, so the
    agreement is asserted rather than assumed; a provider missing here prices
    from the references alone and loses its own prefixes and aliases.
    """

    from app.modules.proxy.external_pricing_sources import register_external_pricing_sources

    reset_serving_context_loaders()
    register_external_pricing_sources()
    try:
        missing = EXTERNAL_PRICED_PROVIDERS - registered_serving_context_providers()
    finally:
        reset_serving_context_loaders()

    assert not missing, f"externally priced providers with no serving-context loader: {sorted(missing)}"


# --------------------------------------------------------------------------
# Rate correctness: units, zero, invalid, collisions
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_explicit_zero_rate_is_kept_as_a_price(db_setup, monkeypatch) -> None:
    """Zero is a published rate, not a missing one.

    A free model must cost 0.00 with a real source, never render as unknown, and
    never be confused with an id nobody priced.
    """

    del db_setup
    payload = {
        "data": [
            {"id": "vendor/free-model", "pricing": {"prompt": "0", "completion": "0"}},
        ]
    }
    _install_reference(monkeypatch, parse_openai_style_catalog(payload, source=OPENROUTER_REFERENCE_SOURCE))
    _install_serving(CATALOGLESS_PROVIDER, catalog=None, publishes_price_catalog=False, prefixes=(("go/", True),))

    cost, status = await _settle(CATALOGLESS_PROVIDER, "go/vendor/free-model")

    assert status is ExternalPriceStatus.RESOLVED
    assert cost is not None
    assert cost.cost_usd == pytest.approx(0.0)
    assert cost.catalog_source == OPENROUTER_REFERENCE_SOURCE


@pytest.mark.asyncio
async def test_reference_rates_are_converted_from_per_token_to_per_million(db_setup, monkeypatch) -> None:
    """Both references publish per-token USD; the store holds per-1M.

    Getting this wrong is silent and off by a factor of a million, so the
    conversion is asserted on the observable cost rather than trusted.
    """

    del db_setup
    payload = {
        "data": [
            {"id": "vendor/priced", "pricing": {"prompt": "0.0000006", "completion": "0.0000022"}},
        ]
    }
    _install_reference(monkeypatch, parse_openai_style_catalog(payload, source=OPENROUTER_REFERENCE_SOURCE))
    _install_serving(CATALOGLESS_PROVIDER, catalog=None, publishes_price_catalog=False, prefixes=(("go/", True),))

    cost, _ = await _settle(CATALOGLESS_PROVIDER, "go/vendor/priced")

    assert cost is not None
    # 1M input at $0.60/1M plus 1M output at $2.20/1M.
    assert cost.cost_usd == pytest.approx(2.8)


@pytest.mark.asyncio
async def test_an_unreadable_published_rate_does_not_settle_the_question(db_setup, monkeypatch) -> None:
    """A shape this build cannot parse is a parse failure, not a free model."""

    del db_setup
    payload = {
        "data": [
            {"id": "vendor/weird", "pricing": {"prompt": {"per_token": "0.6"}, "completion": "0.0000022"}},
        ]
    }
    catalog = parse_openai_style_catalog(payload, source=OPENROUTER_REFERENCE_SOURCE)
    assert catalog.exact("vendor/weird").unpriced_reason is UnpricedReason.UNPARSEABLE
    _install_reference(monkeypatch, catalog)
    _install_serving(CATALOGLESS_PROVIDER, catalog=None, publishes_price_catalog=False, prefixes=(("go/", True),))

    cost, status = await _settle(CATALOGLESS_PROVIDER, "go/vendor/weird")

    assert cost is None
    assert status is not ExternalPriceStatus.NOT_TOKEN_PRICED, "an unreadable rate must not settle as unpriced"
    record = await _record(CATALOGLESS_PROVIDER, "go/vendor/weird")
    assert record is not None and record.next_retry_at is not None


@pytest.mark.asyncio
async def test_a_half_published_rate_never_becomes_a_price(db_setup, monkeypatch) -> None:
    """An input rate with no output rate cannot be multiplied by output tokens."""

    del db_setup
    payload = {"data": [{"id": "vendor/half", "pricing": {"prompt": "0.0000006"}}]}
    _install_reference(monkeypatch, parse_openai_style_catalog(payload, source=OPENROUTER_REFERENCE_SOURCE))
    _install_serving(CATALOGLESS_PROVIDER, catalog=None, publishes_price_catalog=False, prefixes=(("go/", True),))

    cost, _ = await _settle(CATALOGLESS_PROVIDER, "go/vendor/half")

    assert cost is None


@pytest.mark.asyncio
async def test_two_references_naming_different_models_abstains(db_setup, monkeypatch) -> None:
    """A bare id that two vendors qualify differently is a collision, not a match.

    OpenRouter lists ``alpha/shared-name`` and OrcaRouter lists
    ``beta/shared-name`` at a very different rate. Choosing either is a guess,
    and the guess is wrong roughly half the time it matters.
    """

    del db_setup
    _install_reference(monkeypatch, _catalog(OPENROUTER_REFERENCE_SOURCE, {"alpha/shared-name": ModelPrice(1.0, 2.0)}))
    _install_serving("orcarouter", catalog=_catalog("orcarouter", {"beta/shared-name": ModelPrice(30.0, 60.0)}))
    _install_serving(CATALOGLESS_PROVIDER, catalog=None, publishes_price_catalog=False, prefixes=(("go/", True),))

    cost, status = await _settle(CATALOGLESS_PROVIDER, "go/shared-name")

    assert cost is None
    assert status is ExternalPriceStatus.AMBIGUOUS


@pytest.mark.asyncio
async def test_a_variant_suffix_never_inherits_the_base_models_rate(db_setup, monkeypatch) -> None:
    """``:free`` is billed differently, so the base rate is a wrong number."""

    del db_setup
    _install_reference(monkeypatch, _catalog(OPENROUTER_REFERENCE_SOURCE, {"z-ai/glm-5.3": ModelPrice(0.6, 2.2)}))
    _install_serving(CATALOGLESS_PROVIDER, catalog=None, publishes_price_catalog=False, prefixes=(("go/", True),))

    cost, status = await _settle(CATALOGLESS_PROVIDER, "go/z-ai/glm-5.3:free")

    assert cost is None
    assert status is ExternalPriceStatus.UNRESOLVED


@pytest.mark.asyncio
async def test_a_provider_catalog_that_lists_models_without_rates_falls_through(db_setup, monkeypatch) -> None:
    """A subscription listing is a listing, and must not stop the search.

    A provider whose ``/models`` returns ids with no ``pricing`` block at all
    supplies no price catalog. Contributing one - even an accurate one that
    simply prices nothing - settles every id as "listed without a per-token
    price" before any reference is consulted, which is the difference between a
    priced model and a permanently blank cost column.
    """

    del db_setup
    # Two ids the reference prices identically. The only thing that differs
    # between the halves is how the serving integration describes itself.
    reference = {"z-ai/glm-5.3": ModelPrice(0.6, 2.2), "z-ai/glm-5.2": ModelPrice(0.6, 2.2)}

    # The mistake being guarded against: publishing the bare listing as a catalog.
    # The ids are unprefixed so the serving catalog is genuinely consulted for
    # them, rather than the prefix step rewriting the question first.
    _install_reference(monkeypatch, _catalog(OPENROUTER_REFERENCE_SOURCE, reference))
    _install_serving(
        CATALOGLESS_PROVIDER,
        catalog=_unpriced_catalog(CATALOGLESS_PROVIDER, ("z-ai/glm-5.3", "z-ai/glm-5.2")),
    )

    blocked_cost, blocked_status = await _settle(CATALOGLESS_PROVIDER, "z-ai/glm-5.3")

    assert blocked_cost is None
    assert blocked_status is ExternalPriceStatus.NOT_TOKEN_PRICED, (
        "a bare listing published as a catalog settles the id before any reference is asked"
    )

    # The correct shape for such a provider: declare that it publishes no price
    # catalog at all. Same provider, same references, equally-priced sibling id.
    reset_serving_context_loaders()
    _install_reference(monkeypatch, _catalog(OPENROUTER_REFERENCE_SOURCE, reference))
    _install_serving(CATALOGLESS_PROVIDER, catalog=None, publishes_price_catalog=False)

    cost, status = await _settle(CATALOGLESS_PROVIDER, "z-ai/glm-5.2")

    assert status is ExternalPriceStatus.RESOLVED
    assert cost is not None and cost.cost_usd == pytest.approx(2.8)
    assert cost.catalog_source == OPENROUTER_REFERENCE_SOURCE


@pytest.mark.asyncio
async def test_a_subscription_id_is_not_equated_with_a_similar_public_name(db_setup, monkeypatch) -> None:
    """A near-name is not an identity.

    ``glm-5.3-flash`` and ``glm-5.3`` are different models at different rates.
    Stripping a meaningful suffix to reach a listed entry would price one at the
    other's rate, which is the exact class of defect the resolver exists to
    prevent.
    """

    del db_setup
    _install_reference(monkeypatch, _catalog(OPENROUTER_REFERENCE_SOURCE, {"z-ai/glm-5.3": ModelPrice(0.6, 2.2)}))
    _install_serving(CATALOGLESS_PROVIDER, catalog=None, publishes_price_catalog=False, prefixes=(("go/", True),))

    cost, status = await _settle(CATALOGLESS_PROVIDER, "go/glm-5.3-flash")

    assert cost is None
    assert status is ExternalPriceStatus.UNRESOLVED


# --------------------------------------------------------------------------
# Caching, concurrency, and source-role separation
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_resolved_id_is_never_looked_up_again(db_setup, monkeypatch) -> None:
    """Once priced, the request path answers from the store alone."""

    del db_setup
    reference_calls = _install_reference(
        monkeypatch, _catalog(OPENROUTER_REFERENCE_SOURCE, {"z-ai/glm-5.3": ModelPrice(0.6, 2.2)})
    )
    orca_calls = _install_serving("orcarouter", catalog=_catalog("orcarouter", {"x/y": ModelPrice(1.0, 1.0)}))
    serving_calls = _install_serving(
        CATALOGLESS_PROVIDER, catalog=None, publishes_price_catalog=False, prefixes=(("go/", True),)
    )

    await _settle(CATALOGLESS_PROVIDER, "go/glm-5.3")
    after_first = (reference_calls["count"], orca_calls["count"], serving_calls["count"])

    for _ in range(5):
        cost, status = await calculated_cost_for_request(
            provider=CATALOGLESS_PROVIDER, model="go/glm-5.3", usage=ONE_MILLION
        )
    await get_lookup_coordinator().drain()

    assert status is ExternalPriceStatus.RESOLVED
    assert cost is not None
    assert (reference_calls["count"], orca_calls["count"], serving_calls["count"]) == after_first


@pytest.mark.asyncio
async def test_concurrent_first_sightings_collapse_onto_one_lookup(db_setup, monkeypatch) -> None:
    """A burst of traffic to a newly routed id must not fan out into catalog fetches."""

    del db_setup
    reference_calls = _install_reference(
        monkeypatch, _catalog(OPENROUTER_REFERENCE_SOURCE, {"z-ai/glm-5.3": ModelPrice(0.6, 2.2)})
    )
    orca_calls = _install_serving("orcarouter", catalog=_catalog("orcarouter", {"x/y": ModelPrice(1.0, 1.0)}))
    _install_serving(CATALOGLESS_PROVIDER, catalog=None, publishes_price_catalog=False, prefixes=(("go/", True),))

    await asyncio.gather(
        *(
            calculated_cost_for_request(provider=CATALOGLESS_PROVIDER, model="go/glm-5.3", usage=ONE_MILLION)
            for _ in range(8)
        )
    )
    await get_lookup_coordinator().drain()

    assert reference_calls["count"] == 1
    assert orca_calls["count"] == 1
    _, status = await calculated_cost_for_request(provider=CATALOGLESS_PROVIDER, model="go/glm-5.3", usage=ONE_MILLION)
    assert status is ExternalPriceStatus.RESOLVED


@pytest.mark.asyncio
async def test_an_exact_match_does_not_fetch_the_secondary_reference(db_setup, monkeypatch) -> None:
    """The fallback is a fallback, not a toll on every lookup.

    An id OpenRouter lists exactly is already settled: ``exact`` returns the
    first catalog in precedence order that lists it, so a lower-precedence
    catalog cannot change the answer. Fetching OrcaRouter anyway would add a
    catalog request and its latency to every uncached lookup.
    """

    del db_setup
    _install_reference(monkeypatch, _catalog(OPENROUTER_REFERENCE_SOURCE, {"z-ai/glm-5.3": ModelPrice(0.6, 2.2)}))
    orca_calls = _install_serving("orcarouter", catalog=_catalog("orcarouter", {"z-ai/glm-5.3": ModelPrice(9.0, 90.0)}))
    _install_serving(CATALOGLESS_PROVIDER, catalog=None, publishes_price_catalog=False, prefixes=(("go/", True),))

    cost, status = await _settle(CATALOGLESS_PROVIDER, "go/z-ai/glm-5.3")

    assert status is ExternalPriceStatus.RESOLVED
    assert cost is not None
    assert cost.catalog_source == OPENROUTER_REFERENCE_SOURCE
    assert orca_calls["count"] == 0, "the secondary reference must not be consulted for an exact primary match"


@pytest.mark.asyncio
async def test_skipping_the_secondary_reference_never_hides_a_collision(db_setup, monkeypatch) -> None:
    """The skip is safe only for ``exact``; weaker steps must still see everything.

    ``normalized`` and ``vendor-qualified`` gather candidates across every
    catalog and abstain when they disagree. A catalog that was never loaded is a
    collision that was never detected, which would turn an honest abstention into
    a confidently wrong price - so a non-exact match must still fetch the
    fallback and must still abstain.
    """

    del db_setup
    # Neither source lists the bare name exactly; each qualifies it differently.
    _install_reference(monkeypatch, _catalog(OPENROUTER_REFERENCE_SOURCE, {"alpha/shared-name": ModelPrice(1.0, 2.0)}))
    orca_calls = _install_serving(
        "orcarouter", catalog=_catalog("orcarouter", {"beta/shared-name": ModelPrice(30.0, 60.0)})
    )
    _install_serving(CATALOGLESS_PROVIDER, catalog=None, publishes_price_catalog=False, prefixes=(("go/", True),))

    cost, status = await _settle(CATALOGLESS_PROVIDER, "go/shared-name")

    assert orca_calls["count"] >= 1, "a non-exact match must still consult the fallback"
    assert cost is None
    assert status is ExternalPriceStatus.AMBIGUOUS


@pytest.mark.asyncio
async def test_a_retry_after_an_outage_picks_up_the_now_available_rate(db_setup, monkeypatch) -> None:
    """Preserved-unknown is retryable, so recovery actually resolves the id."""

    del db_setup
    _install_reference(monkeypatch, None)
    _install_failing_serving("orcarouter")
    _install_serving(CATALOGLESS_PROVIDER, catalog=None, publishes_price_catalog=False, prefixes=(("go/", True),))

    _, first_status = await _settle(CATALOGLESS_PROVIDER, "go/glm-5.3")
    assert first_status is ExternalPriceStatus.UNRESOLVED

    # Both references recover. The memo window is what would otherwise hide it,
    # so it is cleared exactly as a later lookup outside the window would see.
    reset_serving_context_loaders()
    _install_reference(monkeypatch, _catalog(OPENROUTER_REFERENCE_SOURCE, {"z-ai/glm-5.3": ModelPrice(0.6, 2.2)}))
    _install_serving(CATALOGLESS_PROVIDER, catalog=None, publishes_price_catalog=False, prefixes=(("go/", True),))
    await _make_retry_due(CATALOGLESS_PROVIDER, "go/glm-5.3")

    cost, status = await _settle(CATALOGLESS_PROVIDER, "go/glm-5.3")

    assert status is ExternalPriceStatus.RESOLVED
    assert cost is not None
    assert cost.cost_usd == pytest.approx(2.8)


@pytest.mark.asyncio
async def test_orcarouters_own_ids_are_priced_by_orcarouter_as_the_serving_source(db_setup, monkeypatch) -> None:
    """The secondary reference must not shadow the serving role it is borrowed from.

    For OrcaRouter's own requests its catalog is authoritative and is recorded
    under ``orcarouter``. Recording them under the reference label would let a
    later pass treat OrcaRouter as a non-owner of prices it actually sets.
    """

    del db_setup
    _install_reference(
        monkeypatch, _catalog(OPENROUTER_REFERENCE_SOURCE, {"deepseek/deepseek-chat": ModelPrice(9.0, 9.0)})
    )
    _install_serving("orcarouter", catalog=_catalog("orcarouter", {"deepseek/deepseek-chat": ModelPrice(0.27, 1.1)}))

    cost, status = await _settle("orcarouter", "deepseek/deepseek-chat")

    assert status is ExternalPriceStatus.RESOLVED
    assert cost is not None
    assert cost.catalog_source == "orcarouter"
    assert cost.cost_usd == pytest.approx(0.27 + 1.1)


@pytest.mark.asyncio
async def test_a_disabled_orcarouter_is_not_a_failed_reference(db_setup) -> None:
    """An integration the operator switched off was never asked.

    Reporting it as unavailable would put a permanent failure line in front of an
    operator who turned it off deliberately, and would hold records in place on
    behalf of a source that is not coming back by itself.
    """

    del db_setup
    _install_serving("orcarouter", catalog=None, enabled=False)

    reference = await load_orcarouter_reference(CATALOGLESS_PROVIDER)

    assert reference.catalog is None
    assert reference.availability is CatalogAvailability.DISABLED
    assert not reference.availability.failed


@pytest.mark.asyncio
async def test_orcarouter_is_not_offered_to_itself_as_a_reference(db_setup) -> None:
    """Its catalog is already in play as the serving catalog."""

    del db_setup
    _install_serving("orcarouter", catalog=_catalog("orcarouter", {"x/y": ModelPrice(1.0, 1.0)}))

    reference = await load_orcarouter_reference("orcarouter")

    assert reference.catalog is None
    assert reference.availability is CatalogAvailability.DISABLED


# --------------------------------------------------------------------------
# Usage inputs
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_priced_model_with_no_reported_usage_is_not_an_unresolved_price(db_setup, monkeypatch) -> None:
    """Missing usage renders as ``--`` without a "no price found" marker."""

    del db_setup
    _install_reference(monkeypatch, _catalog(OPENROUTER_REFERENCE_SOURCE, {"z-ai/glm-5.3": ModelPrice(0.6, 2.2)}))
    _install_serving(CATALOGLESS_PROVIDER, catalog=None, publishes_price_catalog=False, prefixes=(("go/", True),))

    await _settle(CATALOGLESS_PROVIDER, "go/glm-5.3")
    cost, status = await calculated_cost_for_request(provider=CATALOGLESS_PROVIDER, model="go/glm-5.3", usage=None)

    assert cost is None
    assert status is ExternalPriceStatus.RESOLVED


@pytest.mark.asyncio
async def test_streaming_and_non_streaming_usage_price_identically(db_setup, monkeypatch) -> None:
    """The same tokens must cost the same regardless of how they were counted.

    A streaming response accumulates usage across SSE events and a non-streaming
    one reads it once, but both arrive here as the same token counts, so any
    difference in the resulting cost would be a bug in this layer.
    """

    del db_setup
    _install_reference(monkeypatch, _catalog(OPENROUTER_REFERENCE_SOURCE, {"z-ai/glm-5.3": ModelPrice(0.6, 2.2)}))
    _install_serving(CATALOGLESS_PROVIDER, catalog=None, publishes_price_catalog=False, prefixes=(("go/", True),))

    await _settle(CATALOGLESS_PROVIDER, "go/glm-5.3")

    non_streaming = UsageTokens(input_tokens=1200, output_tokens=340, cached_input_tokens=200)
    # What a stream decoder accumulates event by event for the same response.
    streamed = UsageTokens(
        input_tokens=sum((1000.0, 200.0)),
        output_tokens=sum((300.0, 40.0)),
        cached_input_tokens=sum((150.0, 50.0)),
    )

    non_streaming_cost, _ = await calculated_cost_for_request(
        provider=CATALOGLESS_PROVIDER, model="go/glm-5.3", usage=non_streaming
    )
    streamed_cost, _ = await calculated_cost_for_request(
        provider=CATALOGLESS_PROVIDER, model="go/glm-5.3", usage=streamed
    )

    assert non_streaming_cost is not None and streamed_cost is not None
    assert non_streaming_cost.cost_usd == pytest.approx(streamed_cost.cost_usd)


@pytest.mark.asyncio
async def test_a_negative_token_count_produces_no_cost(db_setup, monkeypatch) -> None:
    """Invalid usage yields no number rather than a negative charge."""

    del db_setup
    _install_reference(monkeypatch, _catalog(OPENROUTER_REFERENCE_SOURCE, {"z-ai/glm-5.3": ModelPrice(0.6, 2.2)}))
    _install_serving(CATALOGLESS_PROVIDER, catalog=None, publishes_price_catalog=False, prefixes=(("go/", True),))

    await _settle(CATALOGLESS_PROVIDER, "go/glm-5.3")
    cost, status = await calculated_cost_for_request(
        provider=CATALOGLESS_PROVIDER,
        model="go/glm-5.3",
        usage=UsageTokens(input_tokens=-5, output_tokens=10, cached_input_tokens=0),
    )

    assert cost is None
    assert status is ExternalPriceStatus.RESOLVED


# --------------------------------------------------------------------------
# Helpers that touch the store directly
# --------------------------------------------------------------------------


async def _record(provider: str, model: str):
    from app.core.usage.external_pricing.store import ExternalModelPriceStore
    from app.db.session import SessionLocal

    async with SessionLocal() as session:
        return await ExternalModelPriceStore(session).get(provider, model)


async def _make_retry_due(provider: str, model: str) -> None:
    """Bring a backoff deadline forward instead of sleeping through it."""

    from datetime import timedelta

    from sqlalchemy import select

    from app.core.usage.external_pricing.store import normalize_lookup_key
    from app.core.utils.time import utcnow
    from app.db.models import ExternalModelPrice
    from app.db.session import SessionLocal

    provider_key, model_key = normalize_lookup_key(provider, model)
    async with SessionLocal() as session:
        row = (
            await session.execute(
                select(ExternalModelPrice).where(
                    ExternalModelPrice.provider == provider_key,
                    ExternalModelPrice.incoming_model == model_key,
                )
            )
        ).scalar_one()
        row.next_retry_at = utcnow() - timedelta(seconds=1)
        await session.commit()
