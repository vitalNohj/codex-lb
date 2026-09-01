from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.usage.external_pricing import service as external_pricing_service
from app.core.usage.external_pricing.service import CalculatedCost
from app.core.usage.external_pricing.store import PriceRecord
from app.core.usage.pricing import ModelPrice, UsageTokens
from app.db.models import CostSource, ExternalPriceStatus, RequestLog
from app.modules.proxy import external_pricing_logging
from app.modules.proxy.external_pricing_logging import cost_microdollars, external_request_cost
from app.modules.request_logs.mappers import to_request_log_entry

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
@pytest.mark.parametrize("billed_cost", [-0.01, float("nan"), float("inf")])
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
@pytest.mark.parametrize("billed_cost", [-0.01, float("nan"), float("inf")])
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("price", "usage"),
    [
        (
            ModelPrice(1e308, 1e308),
            UsageTokens(input_tokens=1_000_000, output_tokens=1_000_000),
        ),
        (ModelPrice(1.0, 1.0), UsageTokens(input_tokens=0, output_tokens=-1)),
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
