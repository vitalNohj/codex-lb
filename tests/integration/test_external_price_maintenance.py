"""Behavioral coverage for the one-pass external price maintenance command.

The pass exists so prices can be refreshed deliberately rather than polled. Its
value depends on two properties: it must not change anything when nothing
changed, and it must never trade a known rate for nothing because a fetch failed.
"""

from __future__ import annotations

import pytest

from app.core.usage.external_pricing import service as pricing_service
from app.core.usage.external_pricing.catalogs import Catalog, CatalogEntry
from app.core.usage.external_pricing.maintenance import run_maintenance_pass
from app.core.usage.external_pricing.service import (
    ServingContext,
    register_serving_context_loader,
    reset_serving_context_loaders,
)
from app.core.usage.external_pricing.store import ExternalModelPriceStore
from app.core.usage.pricing import ModelPrice
from app.db.models import ExternalPriceStatus
from app.db.session import SessionLocal

pytestmark = pytest.mark.integration


def _catalog(source: str, entries: dict[str, ModelPrice | None]) -> Catalog:
    return Catalog.from_entries(
        source,
        [CatalogEntry(model_id=model_id, price=price) for model_id, price in entries.items()],
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


async def _seed_resolved(model: str, price: ModelPrice, *, provider: str = "orcarouter") -> None:
    async with SessionLocal() as session:
        await ExternalModelPriceStore(session).record_resolved(
            provider=provider,
            incoming_model=model,
            catalog_model=model,
            catalog_source=provider,
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
