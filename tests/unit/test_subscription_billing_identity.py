"""A reported cost is only spend if the provider bills per request.

Flat-rate subscription upstreams still emit ``usage.cost``. The value is ``0``
because there is no per-request debit to report, not because the request was
free. Recorded as ``upstream_billed`` that zero claims the strongest provenance
the system has, outranks the calculated list price, and reports subscription
traffic as free - the conflation two other projects shipped and had to fix.

The opposite error matters just as much: an OpenRouter ``:free`` model really is
debited nothing, and forcing that honest zero to be discarded would replace a
known billed amount with a list-price estimate.

So the rule is about billing identity, not about the number. These tests pin
both directions.
"""

from __future__ import annotations

import pytest

from app.core.usage.external_pricing.providers import (
    EXTERNAL_PRICED_PROVIDERS,
    PER_REQUEST_BILLED_PROVIDERS,
    reports_per_request_billed_cost,
)
from app.core.usage.external_pricing.service import CalculatedCost
from app.db.models import CostSource, ExternalPriceStatus
from app.modules.proxy import external_pricing_logging
from app.modules.proxy.external_pricing_logging import cost_microdollars, external_request_cost

pytestmark = pytest.mark.unit


def _install_catalog_price(monkeypatch, cost: CalculatedCost | None) -> None:
    async def _calculated_cost(**_kwargs):
        if cost is None:
            return None, ExternalPriceStatus.UNRESOLVED
        return cost, ExternalPriceStatus.RESOLVED

    monkeypatch.setattr(external_pricing_logging, "calculated_cost_for_request", _calculated_cost)


@pytest.mark.asyncio
async def test_a_subscription_zero_does_not_become_billed_spend(monkeypatch) -> None:
    """The reported zero is discarded and the list-price estimate is kept."""

    _install_catalog_price(monkeypatch, CalculatedCost(2.8, "z-ai/glm-5.3", "openrouter:reference"))

    result = await external_request_cost(
        provider="cliproxy",
        model="glm-5.3",
        usage=None,
        billed_cost_usd=0.0,
    )

    assert result.cost_usd == pytest.approx(2.8)
    assert result.cost_source == CostSource.CATALOG_CALCULATED.value, (
        "a subscription provider's reported cost must never be recorded as actual spend"
    )
    assert result.price_status == ExternalPriceStatus.RESOLVED.value


@pytest.mark.asyncio
async def test_a_subscription_nonzero_report_is_also_not_billed_spend(monkeypatch) -> None:
    """The rule is the provider's billing identity, not the value it reported.

    A subscription upstream that reports some non-zero figure is describing
    something other than this request's debit - an underlying vendor rate, a
    quota unit - and that is not spend either.
    """

    _install_catalog_price(monkeypatch, CalculatedCost(2.8, "z-ai/glm-5.3", "openrouter:reference"))

    result = await external_request_cost(
        provider="cliproxy",
        model="glm-5.3",
        usage=None,
        billed_cost_usd=0.004,
    )

    assert result.cost_usd == pytest.approx(2.8)
    assert result.cost_source == CostSource.CATALOG_CALCULATED.value


@pytest.mark.asyncio
async def test_a_subscription_request_with_no_resolved_price_stays_unknown(monkeypatch) -> None:
    """Discarding the zero must leave unknown, never a fabricated free row."""

    _install_catalog_price(monkeypatch, None)

    result = await external_request_cost(
        provider="cliproxy",
        model="hy3-preview",
        usage=None,
        billed_cost_usd=0.0,
    )

    assert result.cost_usd is None
    assert result.cost_source is None
    assert result.price_status == ExternalPriceStatus.UNRESOLVED.value
    # An unknown price charges a cost limit nothing rather than some other
    # model's rate, and the quota and the log row agree because they are the
    # same answer.
    assert cost_microdollars(result) == 0


@pytest.mark.asyncio
async def test_a_per_request_provider_keeps_an_honest_zero(monkeypatch) -> None:
    """An OpenRouter ``:free`` model is debited nothing, and that is spend of $0.

    Forcing this to fall through to the catalog price would replace a known
    billed amount with an estimate, which is the mirror-image error.
    """

    _install_catalog_price(monkeypatch, CalculatedCost(2.8, "z-ai/glm-5.3:free", "openrouter:reference"))

    result = await external_request_cost(
        provider="openrouter",
        model="z-ai/glm-5.3:free",
        usage=None,
        billed_cost_usd=0.0,
    )

    assert result.cost_usd == pytest.approx(0.0)
    assert result.cost_source == CostSource.UPSTREAM_BILLED.value
    assert cost_microdollars(result) == 0


@pytest.mark.asyncio
async def test_a_per_request_provider_still_prefers_its_billed_amount(monkeypatch) -> None:
    """Billed spend continues to outrank the calculated list price."""

    _install_catalog_price(monkeypatch, CalculatedCost(2.8, "deepseek/deepseek-chat", "openrouter:reference"))

    result = await external_request_cost(
        provider="orcarouter",
        model="deepseek/deepseek-chat",
        usage=None,
        billed_cost_usd=1.37,
    )

    assert result.cost_usd == pytest.approx(1.37)
    assert result.cost_source == CostSource.UPSTREAM_BILLED.value


def test_per_request_billed_providers_are_a_subset_of_externally_priced_ones() -> None:
    """The two sets are edited independently; a stray key would be silent.

    A provider named here but not externally priced would never reach this code,
    so its presence would be a claim nothing enforces.
    """

    assert PER_REQUEST_BILLED_PROVIDERS <= EXTERNAL_PRICED_PROVIDERS


def test_the_billing_identity_predicate_normalizes_like_the_provider_keys() -> None:
    assert reports_per_request_billed_cost("OpenRouter")
    assert reports_per_request_billed_cost("  orcarouter  ")
    assert not reports_per_request_billed_cost("cliproxy")
    assert not reports_per_request_billed_cost(None)
    assert not reports_per_request_billed_cost("")
