"""Behavioral coverage for the persistent external price store and request path.

The properties under test are the ones that keep pricing off the request path:
a successfully priced id costs no network work, an unresolved id is retried on a
bounded schedule rather than per request, and concurrent first sightings produce
one lookup.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.usage.external_pricing import service as pricing_service
from app.core.usage.external_pricing.catalogs import Catalog, CatalogEntry, parse_openai_style_catalog
from app.core.usage.external_pricing.resolution import UnpricedReason
from app.core.usage.external_pricing.service import (
    ServingContext,
    calculated_cost_for_request,
    get_lookup_coordinator,
    register_serving_context_loader,
    reset_serving_context_loaders,
)
from app.core.usage.external_pricing.store import ExternalModelPriceStore, next_retry_at
from app.core.usage.pricing import ModelPrice, UsageTokens
from app.core.utils.time import utcnow
from app.db.models import ExternalModelPrice, ExternalPriceStatus
from app.db.session import SessionLocal

pytestmark = pytest.mark.integration


ONE_MILLION = UsageTokens(input_tokens=1_000_000, output_tokens=1_000_000, cached_input_tokens=0)


def _catalog(source: str, entries: dict[str, ModelPrice | None]) -> Catalog:
    return Catalog.from_entries(
        source,
        [CatalogEntry(model_id=model_id, price=price) for model_id, price in entries.items()],
    )


class _CountingLoader:
    """Serving-context loader that records how often it was consulted."""

    def __init__(self, context: ServingContext | None) -> None:
        self.context = context
        self.calls = 0

    async def __call__(self, _provider: str) -> ServingContext | None:
        self.calls += 1
        return self.context


@pytest.fixture(autouse=True)
def _no_reference_catalog(monkeypatch):
    """Keep every test offline.

    A test that reached the real OpenRouter catalog would be measuring the
    internet, not the code.
    """

    calls = {"count": 0}

    async def _fetch():
        calls["count"] += 1
        return None

    monkeypatch.setattr(pricing_service, "_load_reference_catalog", _fetch)
    yield calls


@pytest.fixture(autouse=True)
def _clean_loaders():
    reset_serving_context_loaders()
    yield
    reset_serving_context_loaders()


async def _install_serving_catalog(
    provider: str,
    entries: dict[str, ModelPrice | None],
    *,
    prefixes: tuple[tuple[str, bool], ...] = (),
    aliases: dict[str, str] | None = None,
) -> _CountingLoader:
    loader = _CountingLoader(
        ServingContext(
            catalog=_catalog(provider, entries),
            aliases=aliases or {},
            prefixes=prefixes,
        )
    )
    register_serving_context_loader(provider, loader)
    return loader


async def _records() -> list[ExternalModelPrice]:
    async with SessionLocal() as session:
        result = await session.execute(select(ExternalModelPrice))
        return list(result.scalars().all())


@pytest.mark.asyncio
async def test_first_sighting_returns_no_cost_and_schedules_one_lookup(db_setup) -> None:
    """The request reports what is known now and never waits on remote work."""

    del db_setup
    loader = await _install_serving_catalog("orcarouter", {"vendor/model-x": ModelPrice(2.0, 4.0)})

    cost, status = await calculated_cost_for_request(
        provider="orcarouter",
        model="vendor/model-x",
        usage=ONE_MILLION,
    )

    assert cost is None
    # Pending, not unresolved. Nothing has concluded that this model has no
    # published price, and this very lookup is about to resolve it; recording
    # UNRESOLVED here would put a permanent "no price found" marker on the first
    # request for every newly routed model.
    assert status is ExternalPriceStatus.PENDING
    await get_lookup_coordinator().drain()
    assert loader.calls == 1
    records = await _records()
    assert len(records) == 1
    assert records[0].status == ExternalPriceStatus.RESOLVED.value
    assert records[0].input_per_1m == pytest.approx(2.0)


@pytest.mark.asyncio
async def test_a_second_sighting_of_an_unpriceable_id_reports_it_as_unresolved(db_setup) -> None:
    """The marker is earned once a lookup has actually run and found nothing."""

    del db_setup
    await _install_serving_catalog("orcarouter", {"vendor/something-else": ModelPrice(2.0, 4.0)})

    _cost, first_status = await calculated_cost_for_request(
        provider="orcarouter",
        model="vendor/never-listed",
        usage=ONE_MILLION,
    )
    await get_lookup_coordinator().drain()
    _cost, second_status = await calculated_cost_for_request(
        provider="orcarouter",
        model="vendor/never-listed",
        usage=ONE_MILLION,
    )

    assert first_status is ExternalPriceStatus.PENDING
    assert second_status is ExternalPriceStatus.UNRESOLVED


@pytest.mark.asyncio
async def test_a_known_priced_id_costs_no_lookup_and_no_rewrite(db_setup) -> None:
    """Idempotence on the hot path: a resolved id never re-does any work."""

    del db_setup
    loader = await _install_serving_catalog("orcarouter", {"vendor/model-x": ModelPrice(2.0, 4.0)})
    await calculated_cost_for_request(provider="orcarouter", model="vendor/model-x", usage=ONE_MILLION)
    await get_lookup_coordinator().drain()
    assert loader.calls == 1
    before = (await _records())[0]

    for _ in range(5):
        cost, status = await calculated_cost_for_request(
            provider="orcarouter",
            model="vendor/model-x",
            usage=ONE_MILLION,
        )
        assert status is ExternalPriceStatus.RESOLVED
        assert cost is not None
        # 1M input at $2/M + 1M output at $4/M.
        assert cost.cost_usd == pytest.approx(6.0)

    await get_lookup_coordinator().drain()
    assert loader.calls == 1, "a resolved id must not trigger another lookup"
    after = (await _records())[0]
    assert after.updated_at == before.updated_at, "a resolved id must not be rewritten per request"


@pytest.mark.asyncio
async def test_concurrent_first_sightings_collapse_into_one_lookup(db_setup) -> None:
    """A burst of traffic to a new model must produce one catalog fetch."""

    del db_setup

    started = asyncio.Event()
    release = asyncio.Event()

    class _SlowLoader(_CountingLoader):
        async def __call__(self, _provider: str) -> ServingContext | None:
            self.calls += 1
            started.set()
            await release.wait()
            return self.context

    loader = _SlowLoader(
        ServingContext(catalog=_catalog("orcarouter", {"vendor/burst": ModelPrice(1.0, 1.0)}), aliases={}, prefixes=())
    )
    register_serving_context_loader("orcarouter", loader)

    first = await calculated_cost_for_request(provider="orcarouter", model="vendor/burst", usage=ONE_MILLION)
    await started.wait()
    others = await asyncio.gather(
        *(
            calculated_cost_for_request(provider="orcarouter", model="vendor/burst", usage=ONE_MILLION)
            for _ in range(20)
        )
    )
    release.set()
    await get_lookup_coordinator().drain()

    assert first[0] is None
    assert all(cost is None for cost, _ in others)
    assert loader.calls == 1
    assert len(await _records()) == 1


@pytest.mark.asyncio
async def test_lookup_work_times_out_before_a_second_job_can_be_claimed(db_setup, monkeypatch) -> None:
    del db_setup
    monkeypatch.setattr(pricing_service, "LOOKUP_WORK_TIMEOUT_SECONDS", 0.01)

    class _StalledLoader(_CountingLoader):
        async def __call__(self, _provider: str) -> ServingContext | None:
            self.calls += 1
            await asyncio.Event().wait()
            return self.context

    loader = _StalledLoader(None)
    register_serving_context_loader("orcarouter", loader)

    await calculated_cost_for_request(provider="orcarouter", model="vendor/stalled", usage=ONE_MILLION)
    await asyncio.wait_for(get_lookup_coordinator().drain(), timeout=1.0)

    record = (await _records())[0]
    assert record.status == ExternalPriceStatus.UNRESOLVED.value
    assert record.next_retry_at is not None

    await calculated_cost_for_request(provider="orcarouter", model="vendor/stalled", usage=ONE_MILLION)
    await get_lookup_coordinator().drain()
    assert loader.calls == 1


@pytest.mark.asyncio
async def test_retryable_failure_preserves_unsettled_ownership_and_provenance(db_setup) -> None:
    del db_setup
    async with SessionLocal() as session:
        store = ExternalModelPriceStore(session)
        await store.record_retryable_failure(
            provider="orcarouter",
            incoming_model="vendor/unreadable",
            record=None,
            catalog_model="vendor/unreadable",
            catalog_source="orcarouter",
            detail="catalog price could not be parsed",
        )
        before = await store.get("orcarouter", "vendor/unreadable")
        assert before is not None
        applied = await store.record_retryable_failure(
            provider="orcarouter",
            incoming_model="vendor/unreadable",
            record=before,
            detail="serving source timed out",
            previous_attempts=before.attempt_count,
        )
        after = await store.get("orcarouter", "vendor/unreadable")

    assert applied is True
    assert after is not None
    assert after.status is before.status
    assert after.catalog_model == before.catalog_model
    assert after.catalog_source == before.catalog_source
    assert after.resolution_step == before.resolution_step
    assert after.retrieved_at == before.retrieved_at
    assert after.attempt_count == before.attempt_count + 1
    assert after.next_retry_at is not None and after.next_retry_at > before.next_retry_at


@pytest.mark.asyncio
async def test_an_unresolved_id_is_not_retried_until_its_backoff_expires(db_setup) -> None:
    """Traffic must not drive repeated lookup work for an unknown model."""

    del db_setup
    loader = await _install_serving_catalog("orcarouter", {"vendor/other": ModelPrice(1.0, 1.0)})

    await calculated_cost_for_request(provider="orcarouter", model="vendor/unknown", usage=ONE_MILLION)
    await get_lookup_coordinator().drain()
    assert loader.calls == 1
    record = (await _records())[0]
    assert record.status == ExternalPriceStatus.UNRESOLVED.value
    assert record.attempt_count == 1
    assert record.next_retry_at is not None

    for _ in range(10):
        cost, status = await calculated_cost_for_request(
            provider="orcarouter",
            model="vendor/unknown",
            usage=ONE_MILLION,
        )
        assert cost is None
        assert status is ExternalPriceStatus.UNRESOLVED
    await get_lookup_coordinator().drain()

    assert loader.calls == 1, "a backed-off record must not be retried per request"


@pytest.mark.asyncio
async def test_a_due_retry_runs_exactly_one_more_lookup_and_extends_the_backoff(db_setup) -> None:
    del db_setup
    loader = await _install_serving_catalog("orcarouter", {"vendor/other": ModelPrice(1.0, 1.0)})
    await calculated_cost_for_request(provider="orcarouter", model="vendor/unknown", usage=ONE_MILLION)
    await get_lookup_coordinator().drain()

    async with SessionLocal() as session:
        result = await session.execute(select(ExternalModelPrice))
        record = result.scalar_one()
        first_deadline = record.next_retry_at
        record.next_retry_at = utcnow() - timedelta(seconds=1)
        await session.commit()

    await calculated_cost_for_request(provider="orcarouter", model="vendor/unknown", usage=ONE_MILLION)
    await get_lookup_coordinator().drain()

    assert loader.calls == 2
    record = (await _records())[0]
    assert record.attempt_count == 2
    assert first_deadline is not None
    assert record.next_retry_at is not None
    assert record.next_retry_at > first_deadline, "backoff must widen after a repeated failure"


@pytest.mark.asyncio
async def test_an_ambiguous_id_is_persisted_and_never_priced(db_setup) -> None:
    """Abstaining is the answer, and it is remembered like any other."""

    del db_setup
    await _install_serving_catalog(
        "orcarouter",
        {
            "obsidian/qwen3.8-27b": ModelPrice(0.4, 4.21),
            "qwen/qwen3.8-27b": ModelPrice(0.33, 2.4),
        },
    )

    await calculated_cost_for_request(provider="orcarouter", model="qwen3.8-27b", usage=ONE_MILLION)
    await get_lookup_coordinator().drain()

    record = (await _records())[0]
    assert record.status == ExternalPriceStatus.AMBIGUOUS.value
    assert record.input_per_1m is None
    assert record.detail is not None and "qwen/qwen3.8-27b" in record.detail

    cost, status = await calculated_cost_for_request(
        provider="orcarouter",
        model="qwen3.8-27b",
        usage=ONE_MILLION,
    )
    assert cost is None
    assert status is ExternalPriceStatus.AMBIGUOUS


@pytest.mark.asyncio
async def test_a_non_token_priced_model_settles_without_retry_state(db_setup) -> None:
    """A router with no per-token rate is a settled answer, not a failure."""

    del db_setup
    loader = await _install_serving_catalog("orcarouter", {"orcarouter/fusion": None})

    await calculated_cost_for_request(provider="orcarouter", model="orcarouter/fusion", usage=ONE_MILLION)
    await get_lookup_coordinator().drain()

    record = (await _records())[0]
    assert record.status == ExternalPriceStatus.NOT_TOKEN_PRICED.value
    assert record.next_retry_at is None

    await calculated_cost_for_request(provider="orcarouter", model="orcarouter/fusion", usage=ONE_MILLION)
    await get_lookup_coordinator().drain()
    assert loader.calls == 1, "a settled non-token-priced model must not be retried"


@pytest.mark.asyncio
async def test_a_catalog_sentinel_price_settles_the_model_without_retry_state(db_setup) -> None:
    """``openrouter/auto`` publishes ``-1`` to say it has no per-token rate.

    Reading that sentinel as a parse failure marked a genuine router model ``!!``
    and re-looked it up on the backoff schedule forever. It must settle as ``--``.
    """

    del db_setup
    sentinel_catalog = parse_openai_style_catalog(
        {"data": [{"id": "openrouter/auto", "pricing": {"prompt": "-1", "completion": "-1", "request": "-1"}}]},
        source="orcarouter",
    )
    loader = _CountingLoader(ServingContext(catalog=sentinel_catalog, aliases={}, prefixes=()))
    register_serving_context_loader("orcarouter", loader)

    await calculated_cost_for_request(provider="orcarouter", model="openrouter/auto", usage=ONE_MILLION)
    await get_lookup_coordinator().drain()

    record = (await _records())[0]
    assert record.status == ExternalPriceStatus.NOT_TOKEN_PRICED.value
    assert record.next_retry_at is None

    cost, status = await calculated_cost_for_request(
        provider="orcarouter",
        model="openrouter/auto",
        usage=ONE_MILLION,
    )
    await get_lookup_coordinator().drain()

    assert cost is None
    assert status is ExternalPriceStatus.NOT_TOKEN_PRICED
    assert loader.calls == 1, "a settled router model must never be looked up again"


@pytest.mark.asyncio
async def test_an_unreadable_upstream_price_widens_its_backoff_each_round(db_setup) -> None:
    """Preserving a rate must still bound the work that re-reads the source.

    A reset attempt count pins the deadline at the first backoff step, so an
    upstream schema change that lasts a day re-fetches every five minutes forever.
    """

    del db_setup
    unreadable = Catalog.from_entries(
        "orcarouter",
        [CatalogEntry(model_id="vendor/model-x", price=None, unpriced_reason=UnpricedReason.UNPARSEABLE)],
    )
    loader = _CountingLoader(ServingContext(catalog=unreadable, aliases={}, prefixes=()))
    register_serving_context_loader("orcarouter", loader)
    async with SessionLocal() as session:
        await ExternalModelPriceStore(session).record_resolved(
            provider="orcarouter",
            incoming_model="vendor/model-x",
            catalog_model="vendor/model-x",
            catalog_source="orcarouter",
            price=ModelPrice(2.0, 4.0),
            resolution_step="exact",
        )

    deadlines = []
    for expected_attempts in (1, 2, 3):
        async with SessionLocal() as session:
            record = (await session.execute(select(ExternalModelPrice))).scalar_one()
            record.next_retry_at = utcnow() - timedelta(seconds=1)
            await session.commit()
        await calculated_cost_for_request(provider="orcarouter", model="vendor/model-x", usage=ONE_MILLION)
        await get_lookup_coordinator().drain()
        record = (await _records())[0]
        assert record.attempt_count == expected_attempts
        assert record.input_per_1m == pytest.approx(2.0), "the last parsed rate must survive"
        assert record.next_retry_at is not None
        deadlines.append(record.next_retry_at)

    gaps = [later - earlier for earlier, later in zip(deadlines, deadlines[1:])]
    assert all(gap > timedelta(0) for gap in gaps), "the retry schedule must widen, not repeat"


@pytest.mark.asyncio
async def test_ollama_and_omniroute_never_reach_the_store(db_setup) -> None:
    """Excluded integrations produce no record and no unresolved marker."""

    del db_setup
    for provider in ("ollama", "omniroute"):
        cost, status = await calculated_cost_for_request(
            provider=provider,
            model="llama3",
            usage=ONE_MILLION,
        )
        assert cost is None
        assert status is None

    await get_lookup_coordinator().drain()
    assert await _records() == []


@pytest.mark.asyncio
async def test_a_cliproxy_prefixed_id_resolves_through_its_configured_prefix(db_setup) -> None:
    """``cc/claude-fable-5`` maps to the vendor entry, not by trimming blindly."""

    del db_setup
    await _install_serving_catalog(
        "cliproxy",
        {"anthropic/claude-fable-5": ModelPrice(10.0, 50.0)},
        prefixes=(("cc/", True),),
    )

    await calculated_cost_for_request(provider="cliproxy", model="cc/claude-fable-5", usage=ONE_MILLION)
    await get_lookup_coordinator().drain()

    record = (await _records())[0]
    assert record.status == ExternalPriceStatus.RESOLVED.value
    assert record.catalog_model == "anthropic/claude-fable-5"
    assert record.incoming_model == "cc/claude-fable-5"

    cost, _ = await calculated_cost_for_request(
        provider="cliproxy",
        model="cc/claude-fable-5",
        usage=ONE_MILLION,
    )
    assert cost is not None
    assert cost.cost_usd == pytest.approx(60.0)


@pytest.mark.asyncio
async def test_two_providers_serving_the_same_id_keep_separate_records(db_setup) -> None:
    """Shared ids are priced differently per service, so the key includes it."""

    del db_setup
    await _install_serving_catalog("orcarouter", {"deepseek/deepseek-chat": ModelPrice(0.147, 0.3)})
    await _install_serving_catalog("openrouter", {"deepseek/deepseek-chat": ModelPrice(0.2574, 0.6)})

    for provider in ("orcarouter", "openrouter"):
        await calculated_cost_for_request(provider=provider, model="deepseek/deepseek-chat", usage=ONE_MILLION)
    await get_lookup_coordinator().drain()

    orca_cost, _ = await calculated_cost_for_request(
        provider="orcarouter", model="deepseek/deepseek-chat", usage=ONE_MILLION
    )
    open_cost, _ = await calculated_cost_for_request(
        provider="openrouter", model="deepseek/deepseek-chat", usage=ONE_MILLION
    )

    assert orca_cost is not None and orca_cost.cost_usd == pytest.approx(0.447)
    assert open_cost is not None and open_cost.cost_usd == pytest.approx(0.8574)
    assert len(await _records()) == 2


@pytest.mark.asyncio
async def test_a_priced_model_without_token_usage_reports_no_cost(db_setup) -> None:
    """Missing usage is missing usage, not an unresolved price."""

    del db_setup
    await _install_serving_catalog("orcarouter", {"vendor/model-x": ModelPrice(2.0, 4.0)})
    await calculated_cost_for_request(provider="orcarouter", model="vendor/model-x", usage=ONE_MILLION)
    await get_lookup_coordinator().drain()

    cost, status = await calculated_cost_for_request(provider="orcarouter", model="vendor/model-x", usage=None)

    assert cost is None
    assert status is ExternalPriceStatus.RESOLVED


@pytest.mark.asyncio
async def test_every_catalog_source_failing_still_bounds_future_lookups(db_setup) -> None:
    """An outage must not let traffic re-dispatch a lookup on every request."""

    del db_setup

    class _FailingLoader(_CountingLoader):
        async def __call__(self, _provider: str) -> ServingContext | None:
            self.calls += 1
            raise RuntimeError("catalog unreachable")

    loader = _FailingLoader(None)
    register_serving_context_loader("orcarouter", loader)

    await calculated_cost_for_request(provider="orcarouter", model="vendor/model-x", usage=ONE_MILLION)
    await get_lookup_coordinator().drain()

    record = (await _records())[0]
    assert record.status == ExternalPriceStatus.UNRESOLVED.value
    assert record.next_retry_at is not None

    for _ in range(5):
        await calculated_cost_for_request(provider="orcarouter", model="vendor/model-x", usage=ONE_MILLION)
    await get_lookup_coordinator().drain()
    assert loader.calls == 1


@pytest.mark.asyncio
async def test_an_outage_preserves_the_last_good_rate_and_advances_backoff(db_setup) -> None:
    del db_setup
    async with SessionLocal() as session:
        store = ExternalModelPriceStore(session)
        await store.record_resolved(
            provider="orcarouter",
            incoming_model="vendor/model-x",
            catalog_model="vendor/model-x",
            catalog_source="orcarouter",
            price=ModelPrice(2.0, 4.0),
            resolution_step="exact",
        )
        record = await store.get("orcarouter", "vendor/model-x")
        assert record is not None
        await store.record_price_unparseable(
            provider="orcarouter",
            incoming_model="vendor/model-x",
            record=record,
            catalog_model="vendor/model-x",
            catalog_source="orcarouter",
            detail="temporary unreadable price",
        )

    async with SessionLocal() as session:
        row = (await session.execute(select(ExternalModelPrice))).scalar_one()
        row.next_retry_at = utcnow() - timedelta(seconds=1)
        await session.commit()

    class _FailingLoader(_CountingLoader):
        async def __call__(self, _provider: str) -> ServingContext | None:
            self.calls += 1
            raise RuntimeError("catalog unreachable")

    loader = _FailingLoader(None)
    register_serving_context_loader("orcarouter", loader)
    await calculated_cost_for_request(provider="orcarouter", model="vendor/model-x", usage=ONE_MILLION)
    await get_lookup_coordinator().drain()

    record = (await _records())[0]
    assert record.status == ExternalPriceStatus.RESOLVED.value
    assert record.catalog_model == "vendor/model-x"
    assert record.catalog_source == "orcarouter"
    assert record.input_per_1m == pytest.approx(2.0)
    assert record.output_per_1m == pytest.approx(4.0)
    assert record.attempt_count == 2
    assert record.next_retry_at is not None and record.next_retry_at > utcnow()
    assert loader.calls == 1


@pytest.mark.asyncio
async def test_an_unreadable_reference_cannot_relabel_a_preserved_serving_rate(db_setup, monkeypatch) -> None:
    del db_setup
    async with SessionLocal() as session:
        store = ExternalModelPriceStore(session)
        await store.record_resolved(
            provider="orcarouter",
            incoming_model="vendor/model-x",
            catalog_model="vendor/model-x",
            catalog_source="orcarouter",
            price=ModelPrice(2.0, 4.0),
            resolution_step="exact",
        )
        record = await store.get("orcarouter", "vendor/model-x")
        assert record is not None
        await store.record_price_unparseable(
            provider="orcarouter",
            incoming_model="vendor/model-x",
            record=record,
            catalog_model="vendor/model-x",
            catalog_source="orcarouter",
            detail="temporary unreadable serving price",
        )

    async with SessionLocal() as session:
        row = (await session.execute(select(ExternalModelPrice))).scalar_one()
        row.next_retry_at = utcnow() - timedelta(seconds=1)
        await session.commit()

    reference = Catalog.from_entries(
        "openrouter",
        [
            CatalogEntry(
                model_id="vendor/model-x",
                price=None,
                unpriced_reason=UnpricedReason.UNPARSEABLE,
            )
        ],
    )

    async def _reference() -> Catalog:
        return reference

    monkeypatch.setattr(pricing_service, "_load_reference_catalog", _reference)

    async def _failing_loader(_provider: str) -> ServingContext | None:
        raise RuntimeError("serving catalog unavailable")

    register_serving_context_loader("orcarouter", _failing_loader)
    await calculated_cost_for_request(provider="orcarouter", model="vendor/model-x", usage=ONE_MILLION)
    await get_lookup_coordinator().drain()

    record = (await _records())[0]
    assert record.status == ExternalPriceStatus.RESOLVED.value
    assert record.input_per_1m == pytest.approx(2.0)
    assert record.output_per_1m == pytest.approx(4.0)
    assert record.catalog_model == "vendor/model-x"
    assert record.catalog_source == "orcarouter"


@pytest.mark.asyncio
async def test_a_reference_owned_rate_survives_a_reference_outage(db_setup) -> None:
    del db_setup
    async with SessionLocal() as session:
        store = ExternalModelPriceStore(session)
        await store.record_resolved(
            provider="orcarouter",
            incoming_model="vendor/reference-priced",
            catalog_model="vendor/reference-priced",
            catalog_source="openrouter",
            price=ModelPrice(2.0, 4.0),
            resolution_step="exact",
        )
        record = await store.get("orcarouter", "vendor/reference-priced")
        assert record is not None
        await store.record_price_unparseable(
            provider="orcarouter",
            incoming_model="vendor/reference-priced",
            record=record,
            catalog_model="vendor/reference-priced",
            catalog_source="openrouter",
            detail="reference price temporarily unreadable",
        )

    async with SessionLocal() as session:
        row = (await session.execute(select(ExternalModelPrice))).scalar_one()
        row.next_retry_at = utcnow() - timedelta(seconds=1)
        await session.commit()

    await _install_serving_catalog("orcarouter", {"vendor/orca-native": ModelPrice(1.0, 1.0)})
    await calculated_cost_for_request(
        provider="orcarouter",
        model="vendor/reference-priced",
        usage=ONE_MILLION,
    )
    await get_lookup_coordinator().drain()

    record = (await _records())[0]
    assert record.status == ExternalPriceStatus.RESOLVED.value
    assert record.catalog_source == "openrouter"
    assert record.input_per_1m == pytest.approx(2.0)
    assert record.output_per_1m == pytest.approx(4.0)
    assert record.attempt_count == 2
    assert record.next_retry_at is not None and record.next_retry_at > utcnow()


@pytest.mark.asyncio
async def test_an_ambiguous_reference_preserves_a_serving_rate_and_advances_backoff(db_setup, monkeypatch) -> None:
    del db_setup
    async with SessionLocal() as session:
        store = ExternalModelPriceStore(session)
        await store.record_resolved(
            provider="orcarouter",
            incoming_model="model-x",
            catalog_model="vendor/model-x",
            catalog_source="orcarouter",
            price=ModelPrice(2.0, 4.0),
            resolution_step="vendor-qualified",
        )
        record = await store.get("orcarouter", "model-x")
        assert record is not None
        await store.record_price_unparseable(
            provider="orcarouter",
            incoming_model="model-x",
            record=record,
            catalog_model="vendor/model-x",
            catalog_source="orcarouter",
            detail="temporary unreadable serving price",
        )

    async with SessionLocal() as session:
        row = (await session.execute(select(ExternalModelPrice))).scalar_one()
        row.next_retry_at = utcnow() - timedelta(seconds=1)
        await session.commit()

    async def _reference() -> Catalog:
        return _catalog(
            "openrouter",
            {
                "first/model-x": ModelPrice(9.0, 9.0),
                "second/model-x": ModelPrice(10.0, 10.0),
            },
        )

    async def _failing_loader(_provider: str) -> ServingContext | None:
        raise RuntimeError("serving catalog unavailable")

    monkeypatch.setattr(pricing_service, "_load_reference_catalog", _reference)
    register_serving_context_loader("orcarouter", _failing_loader)

    await calculated_cost_for_request(provider="orcarouter", model="model-x", usage=ONE_MILLION)
    await get_lookup_coordinator().drain()

    record = (await _records())[0]
    assert record.status == ExternalPriceStatus.RESOLVED.value
    assert record.catalog_model == "vendor/model-x"
    assert record.catalog_source == "orcarouter"
    assert record.input_per_1m == pytest.approx(2.0)
    assert record.output_per_1m == pytest.approx(4.0)
    assert record.attempt_count == 2
    assert record.next_retry_at is not None and record.next_retry_at > utcnow()


@pytest.mark.asyncio
async def test_an_unavailable_serving_catalog_does_not_settle_a_reference_rate(db_setup, monkeypatch) -> None:
    """A source that could not be consulted must not lose ownership of its rate.

    ``deepseek/deepseek-chat`` is listed by both OrcaRouter and OpenRouter at
    different rates. With OrcaRouter's loader failing, adopting OpenRouter's
    number would settle the record ``RESOLVED`` with no retry deadline, so every
    later OrcaRouter request would be priced -- and charged -- at a rate OrcaRouter
    does not charge, forever.
    """

    del db_setup

    async def _reference():
        return _catalog("openrouter", {"deepseek/deepseek-chat": ModelPrice(0.9, 0.9)})

    monkeypatch.setattr(pricing_service, "_load_reference_catalog", _reference)

    async def _failing_loader(_provider: str) -> ServingContext | None:
        raise RuntimeError("orcarouter /models timed out")

    register_serving_context_loader("orcarouter", _failing_loader)

    cost, _status = await calculated_cost_for_request(
        provider="orcarouter",
        model="deepseek/deepseek-chat",
        usage=ONE_MILLION,
    )
    await get_lookup_coordinator().drain()

    assert cost is None
    record = (await _records())[0]
    assert record.status == ExternalPriceStatus.UNRESOLVED.value
    assert record.input_per_1m is None, "the reference must not own a serving provider's id"
    assert record.next_retry_at is not None, "the record must stay retryable until the source answers"

    cost, status = await calculated_cost_for_request(
        provider="orcarouter",
        model="deepseek/deepseek-chat",
        usage=ONE_MILLION,
    )
    assert cost is None
    assert status is ExternalPriceStatus.UNRESOLVED


@pytest.mark.asyncio
async def test_a_recovered_serving_catalog_prices_the_id_it_owns(db_setup, monkeypatch) -> None:
    """Withholding the reference rate must heal itself, not strand the record."""

    del db_setup

    async def _reference():
        return _catalog("openrouter", {"deepseek/deepseek-chat": ModelPrice(0.9, 0.9)})

    monkeypatch.setattr(pricing_service, "_load_reference_catalog", _reference)

    async def _failing_loader(_provider: str) -> ServingContext | None:
        raise RuntimeError("orcarouter /models timed out")

    register_serving_context_loader("orcarouter", _failing_loader)
    await calculated_cost_for_request(provider="orcarouter", model="deepseek/deepseek-chat", usage=ONE_MILLION)
    await get_lookup_coordinator().drain()

    await _install_serving_catalog("orcarouter", {"deepseek/deepseek-chat": ModelPrice(0.27, 1.1)})
    async with SessionLocal() as session:
        result = await session.execute(select(ExternalModelPrice))
        row = result.scalar_one()
        row.next_retry_at = utcnow() - timedelta(seconds=1)
        await session.commit()

    await calculated_cost_for_request(provider="orcarouter", model="deepseek/deepseek-chat", usage=ONE_MILLION)
    await get_lookup_coordinator().drain()

    cost, status = await calculated_cost_for_request(
        provider="orcarouter",
        model="deepseek/deepseek-chat",
        usage=ONE_MILLION,
    )
    assert status is ExternalPriceStatus.RESOLVED
    assert cost is not None
    assert cost.cost_usd == pytest.approx(0.27 + 1.1)
    assert cost.catalog_source == "orcarouter"


@pytest.mark.asyncio
async def test_a_priceless_provider_still_settles_from_the_reference(db_setup, monkeypatch) -> None:
    """CLIProxyAPI publishes no rates by design, so the reference is the answer.

    Its empty catalog is not a source failure, and treating it as one would leave
    every CLIProxyAPI id permanently unpriced.
    """

    del db_setup

    async def _reference():
        return _catalog("openrouter", {"anthropic/claude-fable-5": ModelPrice(10.0, 50.0)})

    monkeypatch.setattr(pricing_service, "_load_reference_catalog", _reference)

    async def _loader(_provider: str) -> ServingContext:
        return ServingContext(
            catalog=None,
            aliases={},
            prefixes=(("cc/", True),),
            publishes_price_catalog=False,
        )

    register_serving_context_loader("cliproxy", _loader)

    await calculated_cost_for_request(provider="cliproxy", model="cc/claude-fable-5", usage=ONE_MILLION)
    await get_lookup_coordinator().drain()

    cost, status = await calculated_cost_for_request(
        provider="cliproxy",
        model="cc/claude-fable-5",
        usage=ONE_MILLION,
    )
    assert status is ExternalPriceStatus.RESOLVED
    assert cost is not None
    assert cost.cost_usd == pytest.approx(60.0)


@pytest.mark.asyncio
async def test_an_unavailable_serving_catalog_still_settles_its_own_reference_ids(db_setup, monkeypatch) -> None:
    """For OpenRouter the pricing reference *is* its serving catalog.

    Withholding a rate the provider itself published would strand its own ids
    behind an outage of a source that never owned them.
    """

    del db_setup

    async def _reference():
        return _catalog("openrouter", {"vendor/model-x": ModelPrice(2.0, 4.0)})

    monkeypatch.setattr(pricing_service, "_load_reference_catalog", _reference)

    async def _failing_loader(_provider: str) -> ServingContext | None:
        raise RuntimeError("openrouter /models timed out")

    register_serving_context_loader("openrouter", _failing_loader)

    await calculated_cost_for_request(provider="openrouter", model="vendor/model-x", usage=ONE_MILLION)
    await get_lookup_coordinator().drain()

    cost, status = await calculated_cost_for_request(
        provider="openrouter",
        model="vendor/model-x",
        usage=ONE_MILLION,
    )
    assert status is ExternalPriceStatus.RESOLVED
    assert cost is not None
    assert cost.cost_usd == pytest.approx(6.0)


@pytest.mark.asyncio
async def test_the_store_upsert_is_idempotent_for_the_same_key(db_setup) -> None:
    del db_setup
    async with SessionLocal() as session:
        store = ExternalModelPriceStore(session)
        for _ in range(3):
            await store.record_resolved(
                provider="OrcaRouter",
                incoming_model="Vendor/Model-X",
                catalog_model="vendor/model-x",
                catalog_source="orcarouter",
                price=ModelPrice(2.0, 4.0),
                resolution_step="exact",
            )

    records = await _records()
    assert len(records) == 1
    assert records[0].provider == "orcarouter"
    assert records[0].incoming_model == "vendor/model-x"


@pytest.mark.asyncio
async def test_a_stale_failed_lookup_cannot_replace_a_newer_resolution(db_setup) -> None:
    del db_setup
    async with SessionLocal() as first_session:
        first_store = ExternalModelPriceStore(first_session)
        first_claim = await first_store.claim_lookup("orcarouter", "vendor/race")
    assert first_claim is not None

    async with SessionLocal() as session:
        row = (await session.execute(select(ExternalModelPrice))).scalar_one()
        row.next_retry_at = utcnow() - timedelta(seconds=1)
        await session.commit()

    async with SessionLocal() as second_session:
        second_store = ExternalModelPriceStore(second_session)
        second_claim = await second_store.claim_lookup("orcarouter", "vendor/race")
        assert second_claim is not None
        applied = await second_store.record_resolved(
            provider="orcarouter",
            incoming_model="vendor/race",
            catalog_model="vendor/race",
            catalog_source="orcarouter",
            price=ModelPrice(2.0, 4.0),
            resolution_step="exact",
            claim_token=second_claim.token,
        )
    assert applied is True

    async with SessionLocal() as stale_session:
        stale_applied = await ExternalModelPriceStore(stale_session).record_unresolved(
            provider="orcarouter",
            incoming_model="vendor/race",
            status=ExternalPriceStatus.UNRESOLVED,
            detail="stale timeout",
            claim_token=first_claim.token,
        )
    assert stale_applied is False
    record = (await _records())[0]
    assert record.status == ExternalPriceStatus.RESOLVED.value
    assert record.input_per_1m == pytest.approx(2.0)


@pytest.mark.asyncio
async def test_recording_a_price_clears_prior_failure_state(db_setup) -> None:
    """A model that becomes resolvable must stop carrying retry state."""

    del db_setup
    async with SessionLocal() as session:
        store = ExternalModelPriceStore(session)
        await store.record_unresolved(
            provider="orcarouter",
            incoming_model="vendor/model-x",
            status=ExternalPriceStatus.UNRESOLVED,
            detail="not found",
            previous_attempts=3,
        )
        await store.record_resolved(
            provider="orcarouter",
            incoming_model="vendor/model-x",
            catalog_model="vendor/model-x",
            catalog_source="orcarouter",
            price=ModelPrice(2.0, 4.0),
            resolution_step="exact",
        )
        record = await store.get("orcarouter", "vendor/model-x")

    assert record is not None
    assert record.attempt_count == 0
    assert record.next_retry_at is None
    assert record.retry_due() is False


def test_retry_backoff_widens_then_caps() -> None:
    """Backoff must grow but settle, not recede and not grow without bound."""

    now = utcnow()
    deadlines = [next_retry_at(attempt, now=now) for attempt in range(1, 9)]
    gaps = [deadline - now for deadline in deadlines]

    assert gaps == sorted(gaps)
    assert gaps[0] == timedelta(minutes=5)
    assert gaps[-1] == timedelta(hours=24)
    assert gaps[-1] == gaps[-2], "the schedule must cap rather than grow forever"
