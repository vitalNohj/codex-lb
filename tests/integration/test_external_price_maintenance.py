"""Behavioral coverage for the one-pass external price maintenance command.

The pass exists so prices can be refreshed deliberately rather than polled. Its
value depends on two properties: it must not change anything when nothing
changed, and it must never trade a known rate for nothing because a fetch failed.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.core.usage.external_pricing import service as pricing_service
from app.core.usage.external_pricing.catalogs import (
    OPENROUTER_REFERENCE_SOURCE,
    Catalog,
    CatalogEntry,
)
from app.core.usage.external_pricing.maintenance import run_maintenance_pass
from app.core.usage.external_pricing.resolution import UnpricedReason
from app.core.usage.external_pricing.service import (
    ServingContext,
    calculated_cost_for_request,
    register_serving_context_loader,
    reset_serving_context_loaders,
)
from app.core.usage.external_pricing.store import ExternalModelPriceStore
from app.core.usage.pricing import ModelPrice, UsageTokens
from app.core.utils.time import utcnow
from app.db.models import ExternalModelPrice, ExternalPriceStatus
from app.db.session import SessionLocal

pytestmark = pytest.mark.integration


def _catalog(source: str, entries: dict[str, ModelPrice | None]) -> Catalog:
    return Catalog.from_entries(
        source,
        [CatalogEntry(model_id=model_id, price=price) for model_id, price in entries.items()],
    )


def _catalog_with_unparseable(source: str, model_id: str) -> Catalog:
    """A catalog that still lists ``model_id`` but priced it unreadably."""

    return Catalog.from_entries(
        source,
        [CatalogEntry(model_id=model_id, price=None, unpriced_reason=UnpricedReason.UNPARSEABLE)],
    )


@pytest.fixture(autouse=True)
def _offline_reference(monkeypatch):
    """Keep the pricing reference out of these tests.

    They are about the maintenance pass's own behavior over serving catalogs; a
    live OpenRouter fetch would make them measure the internet.
    """

    import app.core.usage.external_pricing.maintenance as maintenance_module

    async def _no_reference():
        return None

    async def _fetch_reference():
        return None, None

    monkeypatch.setattr(pricing_service, "_load_reference_catalog", _no_reference)
    monkeypatch.setattr(maintenance_module, "_fetch_reference", _fetch_reference)
    yield


@pytest.fixture(autouse=True)
def _clean_loaders():
    reset_serving_context_loaders()
    yield
    reset_serving_context_loaders()


def _install_catalog(provider: str, entries: dict[str, ModelPrice | None] | None) -> None:
    async def _loader(_provider: str) -> ServingContext | None:
        if entries is None:
            return None
        return ServingContext(catalog=_catalog(provider, entries), aliases={}, prefixes=())

    register_serving_context_loader(provider, _loader)


def _install_priceless_provider(provider: str, *, prefixes: tuple[tuple[str, bool], ...] = ()) -> None:
    """A provider that contributes routing identity but no rates, like CLIProxyAPI."""

    async def _loader(_provider: str) -> ServingContext | None:
        return ServingContext(
            catalog=None,
            aliases={},
            prefixes=prefixes,
            publishes_price_catalog=False,
        )

    register_serving_context_loader(provider, _loader)


def _install_disabled_provider(
    provider: str,
    *,
    aliases: dict[str, str] | None = None,
    prefixes: tuple[tuple[str, bool], ...] = (),
) -> None:
    """An integration the operator switched off, not one that failed to answer."""

    async def _loader(_provider: str) -> ServingContext:
        return ServingContext.disabled(aliases=aliases, prefixes=prefixes)

    register_serving_context_loader(provider, _loader)


async def _seed_not_token_priced(model: str, *, provider: str = "orcarouter") -> None:
    async with SessionLocal() as session:
        await ExternalModelPriceStore(session).record_not_token_priced(
            provider=provider,
            incoming_model=model,
            catalog_model=model,
            catalog_source=provider,
            resolution_step="exact",
            detail="catalog lists the model without a per-token price",
        )


async def _seed_resolved(
    model: str,
    price: ModelPrice,
    *,
    provider: str = "orcarouter",
    catalog_source: str | None = None,
) -> None:
    async with SessionLocal() as session:
        await ExternalModelPriceStore(session).record_resolved(
            provider=provider,
            incoming_model=model,
            catalog_model=model,
            catalog_source=catalog_source or provider,
            price=price,
            resolution_step="exact",
        )


async def _record(model: str, *, provider: str = "orcarouter"):
    async with SessionLocal() as session:
        return await ExternalModelPriceStore(session).get(provider, model)


@pytest.mark.asyncio
async def test_a_pass_over_unchanged_catalogs_reports_no_changes(db_setup) -> None:
    """Idempotence: running twice against the same catalog changes nothing."""

    del db_setup
    _install_catalog("orcarouter", {"vendor/model-x": ModelPrice(2.0, 4.0)})
    await _seed_resolved("vendor/model-x", ModelPrice(2.0, 4.0))

    first = await run_maintenance_pass()
    second = await run_maintenance_pass()

    for report in (first, second):
        assert report.examined == 1
        assert report.updated == []
        assert report.newly_resolved == []
        assert report.unchanged == 1


@pytest.mark.asyncio
async def test_a_changed_catalog_rate_is_applied_and_reported(db_setup) -> None:
    del db_setup
    await _seed_resolved("vendor/model-x", ModelPrice(2.0, 4.0))
    _install_catalog("orcarouter", {"vendor/model-x": ModelPrice(3.5, 7.0)})

    report = await run_maintenance_pass()

    assert len(report.updated) == 1
    assert report.updated[0].incoming_model == "vendor/model-x"
    record = await _record("vendor/model-x")
    assert record is not None and record.price is not None
    assert record.price.input_per_1m == pytest.approx(3.5)
    assert record.price.output_per_1m == pytest.approx(7.0)


@pytest.mark.asyncio
async def test_a_previously_unresolved_id_that_now_matches_is_reported_as_newly_resolved(db_setup) -> None:
    del db_setup
    async with SessionLocal() as session:
        await ExternalModelPriceStore(session).record_unresolved(
            provider="orcarouter",
            incoming_model="vendor/late-arrival",
            status=ExternalPriceStatus.UNRESOLVED,
            detail="no catalog entry",
        )
    _install_catalog("orcarouter", {"vendor/late-arrival": ModelPrice(1.0, 2.0)})

    report = await run_maintenance_pass()

    assert len(report.newly_resolved) == 1
    record = await _record("vendor/late-arrival")
    assert record is not None
    assert record.status is ExternalPriceStatus.RESOLVED
    assert record.attempt_count == 0


@pytest.mark.asyncio
async def test_an_unreachable_serving_catalog_preserves_the_known_rate(db_setup) -> None:
    """A fetch failure is not a delisting; the last good rate stays."""

    del db_setup
    await _seed_resolved("vendor/model-x", ModelPrice(2.0, 4.0))
    _install_catalog("orcarouter", None)

    report = await run_maintenance_pass()

    assert report.preserved_on_failure == 1
    assert report.updated == []
    assert any("serving catalog unavailable" in failure for failure in report.catalog_failures)
    record = await _record("vendor/model-x")
    assert record is not None and record.price is not None
    assert record.price.input_per_1m == pytest.approx(2.0)


@pytest.mark.asyncio
async def test_a_model_dropped_from_a_reachable_catalog_becomes_unresolved(db_setup) -> None:
    """A reachable catalog that no longer lists an id is authoritative.

    Distinct from the unreachable case above: here the source answered and did not
    include the model, so continuing to report its old rate would serve a price no
    live listing backs.
    """

    del db_setup
    await _seed_resolved("vendor/dropped", ModelPrice(2.0, 4.0))
    _install_catalog("orcarouter", {"vendor/still-here": ModelPrice(1.0, 1.0)})

    report = await run_maintenance_pass()

    assert len(report.unresolved) == 1
    assert report.unresolved[0].incoming_model == "vendor/dropped"
    record = await _record("vendor/dropped")
    assert record is not None
    assert record.status is ExternalPriceStatus.UNRESOLVED
    assert record.price is None


@pytest.mark.asyncio
async def test_a_newly_ambiguous_id_is_reported_and_loses_its_price(db_setup) -> None:
    """A second vendor publishing the same bare name makes the answer unsafe."""

    del db_setup
    await _seed_resolved("qwen3.8-27b", ModelPrice(0.33, 2.4))
    _install_catalog(
        "orcarouter",
        {
            "qwen/qwen3.8-27b": ModelPrice(0.33, 2.4),
            "obsidian/qwen3.8-27b": ModelPrice(0.4, 4.21),
        },
    )

    report = await run_maintenance_pass()

    assert len(report.ambiguous) == 1
    record = await _record("qwen3.8-27b")
    assert record is not None
    assert record.status is ExternalPriceStatus.AMBIGUOUS
    assert record.price is None


@pytest.mark.asyncio
async def test_a_provider_that_publishes_no_rates_is_not_reported_as_a_failure(db_setup, monkeypatch) -> None:
    """CLIProxyAPI contributes no catalog by design; that is not a fetch failure."""

    del db_setup
    import app.core.usage.external_pricing.maintenance as maintenance_module

    async def _reference():
        return _catalog("openrouter", {"claude-fable-5": ModelPrice(5.0, 25.0)}), None

    monkeypatch.setattr(maintenance_module, "_fetch_reference", _reference)
    _install_priceless_provider("cliproxy", prefixes=(("cc/", True),))
    await _seed_resolved("cc/claude-fable-5", ModelPrice(1.0, 2.0), provider="cliproxy")

    report = await run_maintenance_pass()

    assert report.catalog_failures == []
    assert report.preserved_on_failure == 0
    assert len(report.updated) == 1
    record = await _record("cc/claude-fable-5", provider="cliproxy")
    assert record is not None and record.price is not None
    assert record.price.input_per_1m == pytest.approx(5.0)


@pytest.mark.asyncio
async def test_a_priceless_providers_record_dropped_by_the_reference_becomes_unresolved(
    db_setup,
    monkeypatch,
) -> None:
    """The reference answered in full for a provider with no catalog of its own.

    Treating that as "a source failed" would keep a stale rate forever behind a
    failure that never happened.
    """

    del db_setup
    import app.core.usage.external_pricing.maintenance as maintenance_module

    async def _reference():
        return _catalog("openrouter", {"claude-still-listed": ModelPrice(5.0, 25.0)}), None

    monkeypatch.setattr(maintenance_module, "_fetch_reference", _reference)
    _install_priceless_provider("cliproxy", prefixes=(("cc/", True),))
    await _seed_resolved("cc/claude-delisted", ModelPrice(1.0, 2.0), provider="cliproxy")

    report = await run_maintenance_pass()

    assert report.preserved_on_failure == 0
    assert len(report.unresolved) == 1
    assert report.unresolved[0].incoming_model == "cc/claude-delisted"
    record = await _record("cc/claude-delisted", provider="cliproxy")
    assert record is not None
    assert record.status is ExternalPriceStatus.UNRESOLVED
    assert record.price is None


@pytest.mark.asyncio
async def test_an_unreachable_reference_preserves_a_record_its_serving_catalog_dropped(
    db_setup,
    monkeypatch,
) -> None:
    """A reference outage must not delete rates the reference itself supplied.

    The record was resolved from OpenRouter precisely because OrcaRouter does not
    list it. When OrcaRouter answers (without it, as always) and OpenRouter times
    out, no source that could price this id actually answered, so the rate stays.
    """

    del db_setup
    import app.core.usage.external_pricing.maintenance as maintenance_module

    async def _reference_times_out():
        return None, "openrouter: failed to fetch openrouter catalog: timeout"

    monkeypatch.setattr(maintenance_module, "_fetch_reference", _reference_times_out)
    await _seed_resolved(
        "vendor/reference-priced",
        ModelPrice(2.0, 4.0),
        catalog_source="openrouter",
    )
    # OrcaRouter is reachable and, as always, does not list the id.
    _install_catalog("orcarouter", {"vendor/orca-native": ModelPrice(1.0, 1.0)})

    report = await run_maintenance_pass()

    assert report.preserved_on_failure == 1
    assert report.unresolved == []
    record = await _record("vendor/reference-priced")
    assert record is not None and record.price is not None
    assert record.price.input_per_1m == pytest.approx(2.0)
    assert record.status is ExternalPriceStatus.RESOLVED
    assert record.next_retry_at is not None


@pytest.mark.asyncio
async def test_a_serving_price_replaces_a_reference_rate_during_reference_outage(
    db_setup,
    monkeypatch,
) -> None:
    del db_setup
    import app.core.usage.external_pricing.maintenance as maintenance_module

    async def _reference_times_out():
        return None, "openrouter: failed to fetch openrouter catalog: timeout"

    monkeypatch.setattr(maintenance_module, "_fetch_reference", _reference_times_out)
    await _seed_resolved(
        "vendor/newly-native",
        ModelPrice(2.0, 4.0),
        catalog_source="openrouter",
    )
    _install_catalog("orcarouter", {"vendor/newly-native": ModelPrice(1.0, 3.0)})

    report = await run_maintenance_pass()

    assert report.preserved_on_failure == 0
    assert len(report.updated) == 1
    record = await _record("vendor/newly-native")
    assert record is not None and record.price is not None
    assert record.catalog_source == "orcarouter"
    assert record.price.input_per_1m == pytest.approx(1.0)
    assert record.price.output_per_1m == pytest.approx(3.0)
    assert record.next_retry_at is None


@pytest.mark.asyncio
async def test_a_reachable_reference_that_drops_a_record_still_marks_it_unresolved(
    db_setup,
    monkeypatch,
) -> None:
    """Preservation is scoped to failures; a source that answered is authoritative."""

    del db_setup
    import app.core.usage.external_pricing.maintenance as maintenance_module

    async def _reference():
        return _catalog("openrouter", {"vendor/something-else": ModelPrice(9.0, 9.0)}), None

    monkeypatch.setattr(maintenance_module, "_fetch_reference", _reference)
    await _seed_resolved(
        "vendor/reference-priced",
        ModelPrice(2.0, 4.0),
        catalog_source="openrouter",
    )
    _install_catalog("orcarouter", {"vendor/orca-native": ModelPrice(1.0, 1.0)})

    report = await run_maintenance_pass()

    assert report.preserved_on_failure == 0
    assert len(report.unresolved) == 1
    record = await _record("vendor/reference-priced")
    assert record is not None
    assert record.status is ExternalPriceStatus.UNRESOLVED
    assert record.price is None


@pytest.mark.asyncio
async def test_an_unreadable_published_price_keeps_the_last_parsed_rate(db_setup) -> None:
    """Carried forward from PR 24: a parse failure is not a delisting.

    Settling this as "not token priced" would clear the rate, set no retry so the
    model reads ``--`` forever, and count under "Unchanged" so the operator sees
    no signal. One upstream schema rename would erase every rate in one pass.
    """

    del db_setup
    await _seed_resolved("vendor/model-x", ModelPrice(2.0, 4.0))

    async def _loader(_provider: str) -> ServingContext:
        return ServingContext(
            catalog=_catalog_with_unparseable("orcarouter", "vendor/model-x"),
            aliases={},
            prefixes=(),
        )

    register_serving_context_loader("orcarouter", _loader)

    report = await run_maintenance_pass()

    assert len(report.preserved_unparseable) == 1
    assert report.unchanged == 0, "a dropped rate must never be reported as unchanged"
    assert report.unresolved == []

    record = await _record("vendor/model-x")
    assert record is not None and record.price is not None
    assert record.price.input_per_1m == pytest.approx(2.0)
    assert record.price.output_per_1m == pytest.approx(4.0)
    assert record.status is ExternalPriceStatus.RESOLVED
    assert record.next_retry_at is not None, "the source must be re-read, not settled"
    assert "Preserved after an unreadable published price" in report.render()


@pytest.mark.asyncio
async def test_a_genuinely_unpriced_model_is_still_settled_as_not_token_priced(db_setup) -> None:
    """The distinction must not turn every unpriced listing into a retry loop."""

    del db_setup
    await _seed_resolved("vendor/router-model", ModelPrice(2.0, 4.0))
    _install_catalog("orcarouter", {"vendor/router-model": None})

    await run_maintenance_pass()

    record = await _record("vendor/router-model")
    assert record is not None
    assert record.status is ExternalPriceStatus.NOT_TOKEN_PRICED
    assert record.next_retry_at is None


@pytest.mark.asyncio
async def test_an_unreadable_price_preserves_a_settled_not_token_priced_model(db_setup) -> None:
    del db_setup
    await _seed_not_token_priced("vendor/router-model")
    before = await _record("vendor/router-model")
    assert before is not None

    async def _loader(_provider: str) -> ServingContext:
        return ServingContext(
            catalog=_catalog_with_unparseable("orcarouter", "vendor/router-model"),
            aliases={},
            prefixes=(),
        )

    register_serving_context_loader("orcarouter", _loader)

    report = await run_maintenance_pass()

    record = await _record("vendor/router-model")
    assert record is not None
    assert record.status is ExternalPriceStatus.NOT_TOKEN_PRICED
    assert record.price is None
    assert record.catalog_model == "vendor/router-model"
    assert record.catalog_source == "orcarouter"
    assert record.resolution_step == "exact"
    assert record.retrieved_at == before.retrieved_at
    assert record.attempt_count == 1
    assert record.next_retry_at is not None
    assert len(report.preserved_unparseable) == 1

    cost, status = await calculated_cost_for_request(
        provider="orcarouter",
        model="vendor/router-model",
        usage=UsageTokens(input_tokens=10, output_tokens=5),
    )
    assert cost is None
    assert status is ExternalPriceStatus.NOT_TOKEN_PRICED


@pytest.mark.asyncio
async def test_a_never_priced_id_with_an_unreadable_price_stays_unresolved(db_setup) -> None:
    """Preserving a last parsed value must not invent one that never existed."""

    del db_setup
    async with SessionLocal() as session:
        await ExternalModelPriceStore(session).record_unresolved(
            provider="orcarouter",
            incoming_model="vendor/never-priced",
            status=ExternalPriceStatus.UNRESOLVED,
            detail="no catalog entry",
        )

    async def _loader(_provider: str) -> ServingContext:
        return ServingContext(
            catalog=_catalog_with_unparseable("orcarouter", "vendor/never-priced"),
            aliases={},
            prefixes=(),
        )

    register_serving_context_loader("orcarouter", _loader)

    await run_maintenance_pass()

    record = await _record("vendor/never-priced")
    assert record is not None
    assert record.status is ExternalPriceStatus.UNRESOLVED
    assert record.price is None
    assert record.next_retry_at is not None


@pytest.mark.asyncio
async def test_a_settled_unpriced_record_survives_a_serving_catalog_outage(db_setup, monkeypatch) -> None:
    """A router model already settled as not token priced is an answer.

    A serving-catalog outage says nothing about it, so turning it unresolved would
    put ``!!`` on a model that legitimately has no per-token rate, and would file
    it under "Still unresolved" rather than as preserved.
    """

    del db_setup
    import app.core.usage.external_pricing.maintenance as maintenance_module

    async def _reference():
        return _catalog("openrouter", {"vendor/something-else": ModelPrice(9.0, 9.0)}), None

    monkeypatch.setattr(maintenance_module, "_fetch_reference", _reference)
    await _seed_not_token_priced("orcarouter/fusion")
    _install_catalog("orcarouter", None)

    report = await run_maintenance_pass()

    assert report.preserved_on_failure == 1
    assert report.unresolved == []
    record = await _record("orcarouter/fusion")
    assert record is not None
    assert record.status is ExternalPriceStatus.NOT_TOKEN_PRICED
    assert record.next_retry_at is not None


@pytest.mark.asyncio
async def test_an_unsettled_record_is_not_resolved_by_reference_during_serving_outage(
    db_setup,
    monkeypatch,
) -> None:
    del db_setup
    import app.core.usage.external_pricing.maintenance as maintenance_module

    async with SessionLocal() as session:
        await ExternalModelPriceStore(session).record_unresolved(
            provider="orcarouter",
            incoming_model="deepseek/deepseek-chat",
            status=ExternalPriceStatus.UNRESOLVED,
            detail="serving catalog unavailable",
        )

    async def _reference():
        return _catalog("openrouter", {"deepseek/deepseek-chat": ModelPrice(0.9, 0.9)}), None

    monkeypatch.setattr(maintenance_module, "_fetch_reference", _reference)
    _install_catalog("orcarouter", None)

    report = await run_maintenance_pass()

    assert report.preserved_on_failure == 1
    assert report.newly_resolved == []
    record = await _record("deepseek/deepseek-chat")
    assert record is not None
    assert record.status is ExternalPriceStatus.UNRESOLVED
    assert record.price is None
    assert record.attempt_count == 2
    assert record.next_retry_at is not None


@pytest.mark.asyncio
async def test_an_ambiguous_reference_cannot_erase_a_serving_rate_during_an_outage(
    db_setup,
    monkeypatch,
) -> None:
    del db_setup
    import app.core.usage.external_pricing.maintenance as maintenance_module

    await _seed_resolved("model-x", ModelPrice(2.0, 4.0))
    _install_catalog("orcarouter", None)

    async def _reference():
        return (
            _catalog(
                "openrouter",
                {
                    "first/model-x": ModelPrice(9.0, 9.0),
                    "second/model-x": ModelPrice(10.0, 10.0),
                },
            ),
            None,
        )

    monkeypatch.setattr(maintenance_module, "_fetch_reference", _reference)

    report = await run_maintenance_pass()

    assert report.preserved_on_failure == 1
    assert report.ambiguous == []
    record = await _record("model-x")
    assert record is not None
    assert record.status is ExternalPriceStatus.RESOLVED
    assert record.price == ModelPrice(2.0, 4.0)


@pytest.mark.asyncio
async def test_a_stale_maintenance_write_cannot_clear_a_concurrent_resolution(db_setup, monkeypatch) -> None:
    del db_setup
    async with SessionLocal() as session:
        await ExternalModelPriceStore(session).record_unresolved(
            provider="orcarouter",
            incoming_model="vendor/race",
            status=ExternalPriceStatus.UNRESOLVED,
            detail="not found",
        )
    _install_catalog("orcarouter", {"vendor/other": ModelPrice(1.0, 1.0)})

    original = ExternalModelPriceStore.record_unresolved
    raced = False

    async def _race_then_record(self, **kwargs):
        nonlocal raced
        if not raced:
            raced = True
            async with SessionLocal() as session:
                await ExternalModelPriceStore(session).record_resolved(
                    provider="orcarouter",
                    incoming_model="vendor/race",
                    catalog_model="vendor/race",
                    catalog_source="orcarouter",
                    price=ModelPrice(2.0, 4.0),
                    resolution_step="exact",
                )
        return await original(self, **kwargs)

    monkeypatch.setattr(ExternalModelPriceStore, "record_unresolved", _race_then_record)

    report = await run_maintenance_pass()

    assert raced is True
    assert report.unresolved == []
    record = await _record("vendor/race")
    assert record is not None
    assert record.status is ExternalPriceStatus.RESOLVED
    assert record.price == ModelPrice(2.0, 4.0)


@pytest.mark.asyncio
async def test_maintenance_skips_an_active_lookup_until_a_later_pass(db_setup) -> None:
    del db_setup
    async with SessionLocal() as session:
        claim = await ExternalModelPriceStore(session).claim_lookup("orcarouter", "vendor/race")
    assert claim is not None

    async def _failing_loader(_provider: str) -> ServingContext | None:
        raise RuntimeError("serving catalog timed out")

    register_serving_context_loader("orcarouter", _failing_loader)

    await run_maintenance_pass()

    async with SessionLocal() as session:
        active = (
            await session.execute(
                select(ExternalModelPrice).where(
                    ExternalModelPrice.provider == "orcarouter",
                    ExternalModelPrice.incoming_model == "vendor/race",
                )
            )
        ).scalar_one()
        assert active.lookup_token == claim.token
        applied = await ExternalModelPriceStore(session).record_resolved(
            provider="orcarouter",
            incoming_model="vendor/race",
            catalog_model="vendor/race",
            catalog_source="orcarouter",
            price=ModelPrice(2.0, 4.0),
            resolution_step="exact",
            claim_token=claim.token,
        )
    assert applied is True

    _install_catalog("orcarouter", {"vendor/race": ModelPrice(3.0, 6.0)})

    report = await run_maintenance_pass()

    assert len(report.updated) == 1
    record = await _record("vendor/race")
    assert record is not None
    assert record.status is ExternalPriceStatus.RESOLVED
    assert record.price == ModelPrice(3.0, 6.0)


@pytest.mark.asyncio
async def test_maintenance_refreshes_an_expired_lookup_claim(db_setup) -> None:
    del db_setup
    async with SessionLocal() as session:
        claim = await ExternalModelPriceStore(session).claim_lookup("orcarouter", "vendor/orphaned")
        assert claim is not None
        await session.execute(
            update(ExternalModelPrice)
            .where(
                ExternalModelPrice.provider == "orcarouter",
                ExternalModelPrice.incoming_model == "vendor/orphaned",
            )
            .values(next_retry_at=utcnow() - timedelta(seconds=1))
        )
        await session.commit()

    _install_catalog("orcarouter", {"vendor/orphaned": ModelPrice(3.0, 6.0)})

    report = await run_maintenance_pass()

    assert len(report.newly_resolved) == 1
    record = await _record("vendor/orphaned")
    assert record is not None
    assert record.status is ExternalPriceStatus.RESOLVED
    assert record.price == ModelPrice(3.0, 6.0)


@pytest.mark.asyncio
async def test_a_rate_that_becomes_unpriced_is_reported_rather_than_counted_unchanged(db_setup) -> None:
    """Clearing a stored rate is a state change the operator must see."""

    del db_setup
    await _seed_resolved("vendor/model-x", ModelPrice(2.0, 4.0))
    _install_catalog("orcarouter", {"vendor/model-x": None})

    first = await run_maintenance_pass()

    assert len(first.became_not_token_priced) == 1
    assert first.became_not_token_priced[0].incoming_model == "vendor/model-x"
    assert first.unchanged == 0, "a dropped rate must never read as unchanged"
    assert "Now listed without a per-token price" in first.render()

    # Idempotence: the second pass confirms the same settled answer, which is
    # genuinely unchanged.
    second = await run_maintenance_pass()
    assert second.became_not_token_priced == []
    assert second.unchanged == 1


@pytest.mark.asyncio
async def test_a_disabled_integration_is_not_reported_as_a_catalog_failure(db_setup) -> None:
    """Switching an integration off is not the same as it failing to answer."""

    del db_setup
    await _seed_resolved("vendor/model-x", ModelPrice(2.0, 4.0))
    _install_disabled_provider("orcarouter")

    report = await run_maintenance_pass()

    assert report.catalog_failures == []
    assert report.disabled_integrations == ["orcarouter"]
    assert report.skipped_disabled == 1
    assert report.preserved_on_failure == 0
    assert report.unresolved == []
    assert "Integrations disabled" in report.render()
    record = await _record("vendor/model-x")
    assert record is not None and record.price is not None
    assert record.price.input_per_1m == pytest.approx(2.0)


@pytest.mark.asyncio
async def test_a_disabled_integration_still_lets_the_reference_refresh_records_it_owns(
    db_setup,
    monkeypatch,
) -> None:
    """Switching an integration off must not freeze the whole pass.

    The pricing reference is a separate, reachable source and still owns the
    records it supplied. Skipping every record of a switched-off integration made
    the pass unable to apply a rate change the reference was publishing, and
    reported it as a healthy no-op.
    """

    del db_setup
    import app.core.usage.external_pricing.maintenance as maintenance_module

    await _seed_resolved(
        "vendor/model-x",
        ModelPrice(2.0, 4.0),
        catalog_source=OPENROUTER_REFERENCE_SOURCE,
    )
    _install_disabled_provider("orcarouter")

    async def _reference():
        return _catalog(OPENROUTER_REFERENCE_SOURCE, {"vendor/model-x": ModelPrice(3.0, 6.0)}), None

    monkeypatch.setattr(maintenance_module, "_fetch_reference", _reference)

    report = await run_maintenance_pass()

    assert report.catalog_failures == []
    assert report.disabled_integrations == ["orcarouter"]
    assert len(report.updated) == 1
    record = await _record("vendor/model-x")
    assert record is not None and record.price is not None
    assert record.price.input_per_1m == pytest.approx(3.0)


@pytest.mark.asyncio
async def test_disabled_openrouter_serving_owner_is_not_weakened_by_healthy_reference(
    db_setup,
    monkeypatch,
) -> None:
    del db_setup
    import app.core.usage.external_pricing.maintenance as maintenance_module

    original_price = ModelPrice(2.0, 4.0)
    await _seed_resolved(
        "vendor/model-x",
        original_price,
        provider="openrouter",
        catalog_source="openrouter",
    )
    _install_disabled_provider("openrouter")

    async def _reference():
        return _catalog(OPENROUTER_REFERENCE_SOURCE, {"vendor/model-x": None}), None

    monkeypatch.setattr(maintenance_module, "_fetch_reference", _reference)

    report = await run_maintenance_pass()

    assert report.became_not_token_priced == []
    assert report.preserved_while_disabled == 1
    record = await _record("vendor/model-x", provider="openrouter")
    assert record is not None
    assert record.status is ExternalPriceStatus.RESOLVED
    assert record.price == original_price
    assert record.catalog_source == "openrouter"


@pytest.mark.asyncio
async def test_a_disabled_cliproxy_prefix_preserves_reference_owned_price(
    db_setup,
    monkeypatch,
) -> None:
    del db_setup
    import app.core.usage.external_pricing.maintenance as maintenance_module

    price = ModelPrice(10.0, 50.0)
    await _seed_resolved(
        "cc/claude-fable-5",
        price,
        provider="cliproxy",
        catalog_source="openrouter",
    )
    _install_disabled_provider("cliproxy", prefixes=(("cc/", True),))

    async def _reference():
        return _catalog("openrouter", {"anthropic/claude-fable-5": price}), None

    monkeypatch.setattr(maintenance_module, "_fetch_reference", _reference)

    report = await run_maintenance_pass()

    assert report.unresolved == []
    assert report.unchanged == 1
    record = await _record("cc/claude-fable-5", provider="cliproxy")
    assert record is not None
    assert record.status is ExternalPriceStatus.RESOLVED
    assert record.price == price
    assert record.catalog_source == "openrouter"


@pytest.mark.asyncio
async def test_a_disabled_integration_alias_refreshes_reference_owned_price(
    db_setup,
    monkeypatch,
) -> None:
    del db_setup
    import app.core.usage.external_pricing.maintenance as maintenance_module

    await _seed_resolved(
        "team-default",
        ModelPrice(1.0, 2.0),
        provider="cliproxy",
        catalog_source="openrouter",
    )
    _install_disabled_provider(
        "cliproxy",
        aliases={"team-default": "anthropic/claude-fable-5"},
    )

    async def _reference():
        return _catalog(
            "openrouter",
            {"anthropic/claude-fable-5": ModelPrice(10.0, 50.0)},
        ), None

    monkeypatch.setattr(maintenance_module, "_fetch_reference", _reference)

    report = await run_maintenance_pass()

    assert len(report.updated) == 1
    record = await _record("team-default", provider="cliproxy")
    assert record is not None
    assert record.status is ExternalPriceStatus.RESOLVED
    assert record.catalog_model == "anthropic/claude-fable-5"
    assert record.price == ModelPrice(10.0, 50.0)
    assert record.catalog_source == "openrouter"


@pytest.mark.asyncio
async def test_a_disabled_serving_catalogs_record_is_not_re_sourced_to_the_reference(
    db_setup,
    monkeypatch,
) -> None:
    """A source that did not answer must not have its rate replaced by another's.

    ``deepseek/deepseek-chat`` is listed by both OrcaRouter and OpenRouter at
    different rates. With OrcaRouter switched off, adopting OpenRouter's number
    would price every later OrcaRouter request at a rate OrcaRouter does not
    charge -- and would settle it ``RESOLVED`` with no retry, so the request path
    would never revisit it.
    """

    del db_setup
    import app.core.usage.external_pricing.maintenance as maintenance_module

    await _seed_resolved("deepseek/deepseek-chat", ModelPrice(0.27, 1.1))
    _install_disabled_provider("orcarouter")

    async def _reference():
        return _catalog("openrouter", {"deepseek/deepseek-chat": ModelPrice(0.9, 0.9)}), None

    monkeypatch.setattr(maintenance_module, "_fetch_reference", _reference)

    report = await run_maintenance_pass()

    assert report.updated == [], "a switched-off source's rate must not be re-sourced"
    assert report.preserved_while_disabled == 1
    assert report.preserved_on_failure == 0, "a switched-off integration has not failed"
    assert "Preserved after a source failure: 0" in report.render()
    record = await _record("deepseek/deepseek-chat")
    assert record is not None and record.price is not None
    assert record.price.input_per_1m == pytest.approx(0.27)
    assert record.catalog_source == "orcarouter"


@pytest.mark.asyncio
async def test_an_unreachable_serving_catalogs_record_is_not_re_sourced_to_the_reference(
    db_setup,
    monkeypatch,
) -> None:
    """Same rule for an outage as for a switched-off integration.

    A timeout is not permission for another source to take ownership of a rate.
    """

    del db_setup
    import app.core.usage.external_pricing.maintenance as maintenance_module

    await _seed_resolved("deepseek/deepseek-chat", ModelPrice(0.27, 1.1))
    _install_catalog("orcarouter", None)

    async def _reference():
        return _catalog("openrouter", {"deepseek/deepseek-chat": ModelPrice(0.9, 0.9)}), None

    monkeypatch.setattr(maintenance_module, "_fetch_reference", _reference)

    report = await run_maintenance_pass()

    assert report.updated == []
    assert report.preserved_on_failure == 1
    record = await _record("deepseek/deepseek-chat")
    assert record is not None and record.price is not None
    assert record.price.input_per_1m == pytest.approx(0.27)
    assert record.catalog_source == "orcarouter"


@pytest.mark.asyncio
async def test_a_disabled_integrations_silence_is_no_evidence_against_a_settled_record(
    db_setup,
    monkeypatch,
) -> None:
    """An integration that was never asked cannot delist anything."""

    del db_setup
    import app.core.usage.external_pricing.maintenance as maintenance_module

    await _seed_resolved("vendor/model-x", ModelPrice(2.0, 4.0))
    _install_disabled_provider("orcarouter")

    async def _reference():
        return _catalog("openrouter", {"vendor/other": ModelPrice(9.0, 9.0)}), None

    monkeypatch.setattr(maintenance_module, "_fetch_reference", _reference)

    report = await run_maintenance_pass()

    assert report.unresolved == [], "a switched-off integration must not delist a record"
    assert report.preserved_while_disabled == 1
    assert report.preserved_on_failure == 0, "a switched-off integration has not failed"
    record = await _record("vendor/model-x")
    assert record is not None and record.price is not None
    assert record.price.input_per_1m == pytest.approx(2.0)


@pytest.mark.asyncio
async def test_a_pass_over_an_empty_store_is_a_no_op(db_setup) -> None:
    del db_setup
    _install_catalog("orcarouter", {"vendor/model-x": ModelPrice(2.0, 4.0)})

    report = await run_maintenance_pass()

    assert report.examined == 0
    assert report.render().startswith("External model price maintenance")


@pytest.mark.asyncio
async def test_the_report_names_every_record_needing_attention(db_setup) -> None:
    del db_setup
    await _seed_resolved("vendor/dropped", ModelPrice(2.0, 4.0))
    _install_catalog("orcarouter", {"vendor/other": ModelPrice(1.0, 1.0)})

    rendered = (await run_maintenance_pass()).render()

    assert "Records examined: 1" in rendered
    assert "orcarouter/vendor/dropped" in rendered
