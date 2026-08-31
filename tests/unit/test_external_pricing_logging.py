from __future__ import annotations

import pytest

from app.core.usage.external_pricing.service import CalculatedCost
from app.db.models import CostSource, ExternalPriceStatus
from app.modules.proxy import external_pricing_logging
from app.modules.proxy.external_pricing_logging import cost_microdollars, external_request_cost

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
