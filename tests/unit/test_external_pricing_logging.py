from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.usage.external_pricing import service as external_pricing_service
from app.core.usage.external_pricing.service import CalculatedCost
from app.core.usage.external_pricing.store import PriceRecord
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
        RequestLog(
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
        )
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
        RequestLog(
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
        )
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
        RequestLog(
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
        )
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
        assert status is ExternalPriceStatus.UNRESOLVED

    assert submissions == []
