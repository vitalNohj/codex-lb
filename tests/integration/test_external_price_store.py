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
from app.core.usage.external_pricing.catalogs import Catalog, CatalogEntry
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
