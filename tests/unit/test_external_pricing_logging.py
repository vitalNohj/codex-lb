from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.usage.external_pricing import service as external_pricing_service
from app.core.usage.external_pricing.catalogs import Catalog, CatalogEntry
from app.core.usage.external_pricing.service import CalculatedCost
from app.core.usage.external_pricing.store import LookupClaim, PriceRecord
from app.core.usage.pricing import ModelPrice, UsageTokens
from app.db.models import CostSource, ExternalPriceStatus, RequestLog
from app.modules.proxy import external_pricing_logging
from app.modules.proxy.claude_sidecar_dispatch import extract_billed_cost
from app.modules.proxy.external_pricing_logging import (
    ExternalRequestCost,
    cost_microdollars,
    external_request_cost,
)
from app.modules.request_logs.mappers import to_request_log_entry

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "billed_cost",
    [-0.01, float("nan"), float("inf"), 1e308, 10_000_000_000_000.0],
)
async def test_invalid_billed_cost_falls_back_to_catalog_price(monkeypatch, billed_cost: float) -> None:
    async def _calculated_cost(**_kwargs):
        return CalculatedCost(0.75, "vendor/model", "orcarouter"), ExternalPriceStatus.RESOLVED

    monkeypatch.setattr(external_pricing_logging, "calculated_cost_for_request", _calculated_cost)

    result = await external_request_cost(
        provider="orcarouter",
        model="vendor/model",
        usage=None,
        billed_cost_usd=billed_cost,
    )

    assert result.cost_usd == pytest.approx(0.75)
    assert result.cost_source == CostSource.CATALOG_CALCULATED.value
    assert cost_microdollars(result) == 750_000


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "billed_cost",
    [-0.01, float("nan"), float("inf"), 1e308, 10_000_000_000_000.0],
)
async def test_invalid_billed_cost_without_catalog_price_stays_unknown(monkeypatch, billed_cost: float) -> None:
    async def _no_calculated_cost(**_kwargs):
        return None, ExternalPriceStatus.UNRESOLVED

    monkeypatch.setattr(external_pricing_logging, "calculated_cost_for_request", _no_calculated_cost)

    result = await external_request_cost(
        provider="openrouter",
        model="vendor/unknown",
        usage=None,
        billed_cost_usd=billed_cost,
    )

    assert result.cost_usd is None
    assert result.cost_source is None
    assert result.price_status == ExternalPriceStatus.UNRESOLVED.value
    assert cost_microdollars(result) == 0

    entry = to_request_log_entry(
        include_sensitive_metadata=False,
        log=RequestLog(
            request_id="req-invalid-billed-cost",
            request_kind="normal",
            model="vendor/unknown",
            source="openrouter",
            status="success",
            error_code=None,
            requested_at=datetime.now(timezone.utc),
            input_tokens=1,
            output_tokens=1,
            cached_input_tokens=0,
            cost_usd=result.cost_usd,
            cost_source=result.cost_source,
            price_status=result.price_status,
        ),
    )
    assert entry.cost_usd is None
    assert entry.cost_breakdown.total_usd is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("price", "usage"),
    [
        (
            ModelPrice(1e308, 1e308),
            UsageTokens(input_tokens=1_000_000, output_tokens=1_000_000),
        ),
        pytest.param(
            ModelPrice(1.0, 1.0),
            UsageTokens(input_tokens=-10, output_tokens=20),
            id="negative-input-with-positive-total",
        ),
        pytest.param(
            ModelPrice(1.0, 1.0),
            UsageTokens(input_tokens=20, output_tokens=-10),
            id="negative-output-with-positive-total",
        ),
        pytest.param(
            ModelPrice(1.0, 1.0),
            UsageTokens(input_tokens=20, output_tokens=0, cached_input_tokens=-10),
            id="negative-cached-input-with-positive-total",
        ),
    ],
)
async def test_invalid_calculated_total_stays_unknown_through_logging_and_quota(
    monkeypatch,
    price: ModelPrice,
    usage: UsageTokens,
) -> None:
    now = datetime.now(timezone.utc)
    record = PriceRecord(
        provider="orcarouter",
        incoming_model="gpt-4o-lookalike",
        raw_incoming_model="gpt-4o-lookalike",
        status=ExternalPriceStatus.RESOLVED,
        catalog_model="vendor/gpt-4o-lookalike",
        catalog_source="orcarouter",
        price=price,
        resolution_step="exact",
        detail=None,
        retrieved_at=now,
        updated_at=now,
        attempt_count=1,
        next_retry_at=None,
    )

    async def _read_record(_provider: str, _model: str) -> PriceRecord:
        return record

    monkeypatch.setattr(external_pricing_service, "_read_record", _read_record)

    result = await external_request_cost(
        provider="orcarouter",
        model="gpt-4o-lookalike",
        usage=usage,
        billed_cost_usd=None,
        schedule_lookup=False,
    )

    assert result.cost_usd is None
    assert result.cost_source is None
    assert result.price_status == ExternalPriceStatus.RESOLVED.value
    assert cost_microdollars(result) == 0

    entry = to_request_log_entry(
        include_sensitive_metadata=False,
        log=RequestLog(
            request_id="req-invalid-calculated-total",
            request_kind="normal",
            model="gpt-4o-lookalike",
            source="orcarouter_sidecar",
            status="success",
            error_code=None,
            requested_at=now,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cached_input_tokens=usage.cached_input_tokens,
            cost_usd=result.cost_usd,
            cost_source=result.cost_source,
            price_status=result.price_status,
        ),
    )

    assert entry.cost_usd is None
    assert entry.cost_breakdown.total_usd is None
    assert entry.price_status == ExternalPriceStatus.RESOLVED.value


@pytest.mark.parametrize(
    "cost_usd",
    [
        pytest.param(1e308, id="scaled-non-finite"),
        pytest.param(10_000_000_000_000.0, id="scaled-outside-signed-64-bit-range"),
    ],
)
def test_unrepresentable_cost_accrues_no_quota(cost_usd: float) -> None:
    cost = ExternalRequestCost(
        cost_usd=cost_usd,
        cost_source=CostSource.UPSTREAM_BILLED.value,
        price_status=ExternalPriceStatus.RESOLVED.value,
    )

    assert cost_microdollars(cost) == 0


@pytest.mark.asyncio
async def test_valid_alternate_billed_field_drives_log_and_quota(monkeypatch) -> None:
    async def _no_calculated_cost(**_kwargs):
        return None, ExternalPriceStatus.UNRESOLVED

    monkeypatch.setattr(external_pricing_logging, "calculated_cost_for_request", _no_calculated_cost)
    billed_cost = extract_billed_cost({"usage": {"cost": -1, "cost_usd": 0.01}})

    result = await external_request_cost(
        provider="openrouter",
        model="vendor/model",
        usage=None,
        billed_cost_usd=billed_cost,
    )
    entry = to_request_log_entry(
        include_sensitive_metadata=False,
        log=RequestLog(
            request_id="req-valid-alternate-billed-cost",
            request_kind="normal",
            model="vendor/model",
            source="openrouter",
            status="success",
            error_code=None,
            requested_at=datetime.now(timezone.utc),
            input_tokens=None,
            output_tokens=None,
            cached_input_tokens=None,
            cost_usd=result.cost_usd,
            cost_source=result.cost_source,
            price_status=result.price_status,
        ),
    )

    assert entry.cost_usd == pytest.approx(0.01)
    assert entry.cost_source == CostSource.UPSTREAM_BILLED.value
    assert cost_microdollars(result) == 10_000


@pytest.mark.asyncio
async def test_store_read_failure_suppresses_lookup_submission(monkeypatch: pytest.MonkeyPatch) -> None:
    submissions: list[tuple[str, str]] = []

    class _FailingSessionContext:
        async def __aenter__(self) -> object:
            raise RuntimeError("database unavailable")

        async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

    async def _submit(key: tuple[str, str], factory: object) -> None:
        submissions.append(key)

    monkeypatch.setattr(external_pricing_service, "get_background_session", _FailingSessionContext)
    monkeypatch.setattr(external_pricing_service.get_lookup_coordinator(), "submit", _submit)

    for _ in range(3):
        calculated, status = await external_pricing_service.calculated_cost_for_request(
            provider="orcarouter",
            model="vendor/model-x",
            usage=UsageTokens(input_tokens=10, output_tokens=5),
        )
        assert calculated is None
        assert status is ExternalPriceStatus.PENDING

    assert submissions == []


@pytest.mark.asyncio
async def test_resolver_exception_stays_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fail(**_kwargs: object) -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(external_pricing_logging, "calculated_cost_for_request", _fail)

    result = await external_request_cost(
        provider="orcarouter",
        model="vendor/model-x",
        usage=UsageTokens(input_tokens=10, output_tokens=5),
        billed_cost_usd=None,
    )

    assert result.cost_usd is None
    assert result.cost_source is None
    assert result.price_status == ExternalPriceStatus.PENDING.value


@pytest.mark.asyncio
async def test_claim_write_failure_cools_requests_and_recovers(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now()
    original = PriceRecord(
        provider="orcarouter",
        incoming_model="vendor/model-x",
        raw_incoming_model="vendor/model-x",
        status=ExternalPriceStatus.UNRESOLVED,
        catalog_model=None,
        catalog_source=None,
        price=None,
        resolution_step=None,
        detail="not found",
        retrieved_at=now - timedelta(hours=1),
        updated_at=now - timedelta(hours=1),
        attempt_count=3,
        next_retry_at=now - timedelta(seconds=1),
    )
    monotonic_now = [100.0]
    writes_available = [False]
    claim_attempts = 0
    active_claim: str | None = None
    persisted: list[object] = []

    class _SessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

    class _Store:
        def __init__(self, session: object) -> None:
            self.session = session

        async def get(self, provider: str, model: str) -> PriceRecord:
            return original

        async def claim_lookup(self, provider: str, model: str) -> LookupClaim | None:
            nonlocal active_claim, claim_attempts
            claim_attempts += 1
            if not writes_available[0]:
                raise RuntimeError("primary unavailable")
            if active_claim is not None:
                return None
            active_claim = "claim-after-recovery"
            return LookupClaim(token=active_claim, record=original)

    async def _serving_context(provider: str) -> external_pricing_service.ServingContext:
        return external_pricing_service.ServingContext(
            catalog=Catalog.from_entries(
                "orcarouter",
                [CatalogEntry("vendor/model-x", ModelPrice(3.0, 4.0))],
            ),
            aliases={},
            prefixes=(),
        )

    async def _no_reference() -> None:
        return None

    async def _persist(*args: object, **kwargs: object) -> None:
        nonlocal active_claim
        assert kwargs["claim_token"] == active_claim
        persisted.append(args[2])
        active_claim = None

    coordinator = external_pricing_service._LookupCoordinator(
        storage_failure_cooldown_seconds=5.0,
        clock=lambda: monotonic_now[0],
    )
    monkeypatch.setattr(external_pricing_service, "_coordinator", coordinator)
    monkeypatch.setattr(external_pricing_service, "get_background_session", _SessionContext)
    monkeypatch.setattr(external_pricing_service, "ExternalModelPriceStore", _Store)
    monkeypatch.setattr(external_pricing_service, "load_serving_context", _serving_context)
    monkeypatch.setattr(external_pricing_service, "_load_reference_catalog", _no_reference)
    monkeypatch.setattr(external_pricing_service, "_persist_resolution", _persist)

    for _ in range(3):
        calculated, status = await external_pricing_service.calculated_cost_for_request(
            provider="orcarouter",
            model="vendor/model-x",
            usage=UsageTokens(input_tokens=10, output_tokens=5),
        )
        assert calculated is None
        assert status is ExternalPriceStatus.UNRESOLVED
        await coordinator.drain()

    assert claim_attempts == 1
    assert original.attempt_count == 3
    assert original.next_retry_at == now - timedelta(seconds=1)
    assert active_claim is None
    assert persisted == []

    writes_available[0] = True
    monotonic_now[0] += 5.0
    calculated, status = await external_pricing_service.calculated_cost_for_request(
        provider="orcarouter",
        model="vendor/model-x",
        usage=UsageTokens(input_tokens=10, output_tokens=5),
    )
    assert calculated is None
    assert status is ExternalPriceStatus.UNRESOLVED
    await coordinator.drain()

    assert claim_attempts == 2
    assert len(persisted) == 1
    assert active_claim is None


def _resolved_record(price: ModelPrice) -> PriceRecord:
    now = datetime.now(timezone.utc)
    return PriceRecord(
        provider="cliproxy",
        incoming_model="claude-opus-5-5",
        raw_incoming_model="claude-opus-5-5",
        status=ExternalPriceStatus.RESOLVED,
        catalog_model="anthropic/claude-opus-5-5",
        catalog_source="openrouter",
        price=price,
        resolution_step="exact",
        detail=None,
        retrieved_at=now,
        updated_at=now,
        attempt_count=1,
        next_retry_at=None,
    )


@pytest.mark.asyncio
async def test_catalog_cost_carries_its_cache_write_part_at_the_resolved_rate(monkeypatch) -> None:
    # A catalog rate unlike the static table's, so the stored part can only
    # come from the rate that priced the row.
    record = _resolved_record(ModelPrice(input_per_1m=4.0, output_per_1m=20.0, cached_input_per_1m=0.2))

    async def _read_record(_provider: str, _model: str) -> PriceRecord:
        return record

    monkeypatch.setattr(external_pricing_service, "_read_record", _read_record)

    usage = UsageTokens(
        input_tokens=100_000, output_tokens=1_000, cached_input_tokens=60_000, cache_write_input_tokens=30_000
    )
    result = await external_request_cost(
        provider="cliproxy", model="claude-opus-5-5", usage=usage, billed_cost_usd=None, schedule_lookup=False
    )

    assert result.cost_source == CostSource.CATALOG_CALCULATED.value
    assert result.cost_usd == pytest.approx(0.04 + 0.012 + 0.24 + 0.02)
    assert result.cache_write_input_cost_usd == pytest.approx(0.24)

    no_writes = await external_request_cost(
        provider="cliproxy",
        model="claude-opus-5-5",
        usage=UsageTokens(input_tokens=100_000, output_tokens=1_000, cached_input_tokens=60_000),
        billed_cost_usd=None,
        schedule_lookup=False,
    )
    assert no_writes.cache_write_input_cost_usd is None


@pytest.mark.asyncio
async def test_billed_cost_has_no_known_cache_write_part(monkeypatch) -> None:
    async def _calculated_cost(**_kwargs):
        return CalculatedCost(0.75, "vendor/model", "orcarouter", cache_write_input_cost_usd=0.5), (
            ExternalPriceStatus.RESOLVED
        )

    monkeypatch.setattr(external_pricing_logging, "calculated_cost_for_request", _calculated_cost)

    result = await external_request_cost(
        provider="orcarouter", model="vendor/model", usage=None, billed_cost_usd=0.9, schedule_lookup=False
    )

    assert result.cost_source == CostSource.UPSTREAM_BILLED.value
    assert result.cache_write_input_cost_usd is None


def _participating_log(*, cost_source: str, cache_write_input_cost_usd: float | None) -> RequestLog:
    return RequestLog(
        request_id="req-claude-cache-write",
        request_kind="normal",
        model="cc/claude-opus-5-5",
        source="claude_sidecar",
        status="success",
        error_code=None,
        requested_at=datetime.now(timezone.utc),
        input_tokens=100_000,
        output_tokens=1_000,
        cached_input_tokens=60_000,
        cache_write_input_tokens=30_000,
        cost_usd=0.312,
        cache_write_input_cost_usd=cache_write_input_cost_usd,
        cost_source=cost_source,
        price_status=ExternalPriceStatus.RESOLVED.value,
    )


def test_a_catalog_priced_row_shows_its_stored_cache_write_part() -> None:
    entry = to_request_log_entry(
        include_sensitive_metadata=False,
        log=_participating_log(cost_source=CostSource.CATALOG_CALCULATED.value, cache_write_input_cost_usd=0.24),
    )

    assert entry.cache_write_input_tokens == 30_000
    assert entry.cost_breakdown.total_usd == pytest.approx(0.312)
    assert entry.cost_breakdown.cache_write_input_usd == pytest.approx(0.24)
    # The rest of the split was never stored; the static table must not fill it in.
    assert entry.cost_breakdown.input_usd is None
    assert entry.cost_breakdown.cached_input_usd is None
    assert entry.cost_breakdown.output_usd is None


def test_a_billed_row_shows_no_cache_write_part_even_if_one_was_stored() -> None:
    entry = to_request_log_entry(
        include_sensitive_metadata=False,
        log=_participating_log(cost_source=CostSource.UPSTREAM_BILLED.value, cache_write_input_cost_usd=0.24),
    )

    assert entry.cost_breakdown.total_usd == pytest.approx(0.312)
    assert entry.cost_breakdown.cache_write_input_usd is None
