"""An unresolved participating model must contribute no savings figure.

``reference_cost_usd`` resolves through the runtime registry and then the static
``DEFAULT_PRICING_MODELS`` table, whose aliases match by substring. Since an
unresolved external row now stores ``cost_usd = NULL``, a glob-derived reference
became the entire "Saved $X" figure on the provider card: money reported as saved
on a request whose real cost is unknown.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.usage.pricing import ModelPrice, UsageTokens, get_pricing_for_model
from app.core.usage.runtime_pricing import (
    calculate_reference_cost,
    get_reference_pricing_for_model,
    get_runtime_pricing_registry,
)
from app.db.models import ExternalPriceStatus, RequestLog
from app.modules.request_logs.mappers import to_request_log_entry

pytestmark = pytest.mark.unit

# Matches the retired ``*gpt-4o*`` alias glob but is in no catalog.
GLOB_MATCHING_MODEL = "orcarouter/gpt-4o-lookalike"


@pytest.fixture(autouse=True)
def _clear_registry():
    registry = get_runtime_pricing_registry()
    registry.clear()
    yield
    registry.clear()


def test_the_static_table_still_matches_this_id_by_substring() -> None:
    """Guards the premise: this is the number that used to become phantom savings."""

    resolved = get_pricing_for_model(GLOB_MATCHING_MODEL, None, None)
    assert resolved is not None
    canonical, _price = resolved
    assert canonical != GLOB_MATCHING_MODEL


@pytest.mark.parametrize("provider", ["openrouter", "orcarouter", "cliproxy"])
def test_a_participating_provider_gets_no_static_table_reference_price(provider: str) -> None:
    assert get_reference_pricing_for_model(GLOB_MATCHING_MODEL, provider=provider) is None
    assert (
        calculate_reference_cost(
            GLOB_MATCHING_MODEL,
            UsageTokens(input_tokens=1_000_000, output_tokens=1_000_000, cached_input_tokens=0),
            provider=provider,
        )
        is None
    )


@pytest.mark.parametrize("provider", [None, "ollama", "omniroute"])
def test_a_non_participating_path_still_uses_the_static_table(provider: str | None) -> None:
    """Ollama and OmniRoute keep the overlay behavior they always had."""

    price = get_reference_pricing_for_model(GLOB_MATCHING_MODEL, provider=provider)

    assert price is not None
    assert price.input_per_1m == pytest.approx(2.5)


def test_a_participating_provider_still_uses_its_own_published_runtime_price() -> None:
    """PR 24's per-source semantics are untouched: only the glob table is cut."""

    get_runtime_pricing_registry().update_models(
        [("vendor/real-model", ModelPrice(input_per_1m=1.0, output_per_1m=2.0))],
        provider="orcarouter",
    )

    cost = calculate_reference_cost(
        "vendor/real-model",
        UsageTokens(input_tokens=1_000_000, output_tokens=1_000_000, cached_input_tokens=0),
        provider="orcarouter",
    )

    assert cost == pytest.approx(3.0)


def _log(**overrides) -> RequestLog:
    values = {
        "request_id": "req-savings",
        "request_kind": "normal",
        "model": GLOB_MATCHING_MODEL,
        "source": "orcarouter_sidecar",
        "status": "success",
        "error_code": None,
        "requested_at": datetime(2026, 8, 29, tzinfo=timezone.utc),
        "input_tokens": 10,
        "output_tokens": 5,
        "cached_input_tokens": 0,
        "reasoning_tokens": None,
        "cost_usd": None,
    }
    values.update(overrides)
    return RequestLog(**values)


@pytest.mark.parametrize(
    "price_status",
    [
        ExternalPriceStatus.UNRESOLVED.value,
        ExternalPriceStatus.AMBIGUOUS.value,
        ExternalPriceStatus.PENDING.value,
    ],
)
def test_an_unknown_cost_reports_no_savings_rather_than_the_whole_reference(price_status: str) -> None:
    """A NULL cost is unknown spend, not zero spend."""

    entry = to_request_log_entry(_log(price_status=price_status, reference_cost_usd=0.000075))

    assert entry.cost_usd is None
    assert entry.savings_usd is None, "an unknown cost must not read as the full reference saved"


def test_a_resolved_row_still_reports_real_savings() -> None:
    entry = to_request_log_entry(
        _log(
            cost_usd=0.0,
            price_status=ExternalPriceStatus.RESOLVED.value,
            reference_cost_usd=0.016,
        )
    )

    assert entry.savings_usd == pytest.approx(0.016)
