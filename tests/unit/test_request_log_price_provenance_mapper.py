"""The read path must not resurrect substring-glob pricing.

``add_log`` deliberately stores ``cost_usd = NULL`` with a ``price_status`` when a
participating external integration's model stayed unresolved. The mapper used to
recompute a cost from the static alias table whenever the persisted cost was NULL,
so a model whose *name* happened to match a glob (``*gpt-4o*``, ``*claude-opus-4*``)
came back with another model's rate and never earned the ``!!`` marker.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.usage.pricing import get_pricing_for_model
from app.db.models import CostSource, ExternalPriceStatus, RequestLog
from app.modules.request_logs.mappers import to_request_log_entry

pytestmark = pytest.mark.unit

# Ids that match no catalog but do match a static-table glob. If the table ever
# stops matching them this test would pass vacuously, so that is asserted.
GLOB_MATCHING_MODELS = (
    "orcarouter/gpt-4o-lookalike",
    "openai/gpt-4o-mini-tts",
    "anthropic/claude-opus-4.5",
)


def _log(**overrides) -> RequestLog:
    values = {
        "request_id": "req-1",
        "request_kind": "normal",
        "model": "orcarouter/gpt-4o-lookalike",
        "source": "orcarouter_sidecar",
        "status": "success",
        "error_code": None,
        "requested_at": datetime(2026, 8, 29, tzinfo=timezone.utc),
        "input_tokens": 1_000,
        "output_tokens": 1_000,
        "cached_input_tokens": 0,
        "reasoning_tokens": None,
        "cost_usd": None,
    }
    values.update(overrides)
    return RequestLog(**values)


@pytest.mark.parametrize("model", GLOB_MATCHING_MODELS)
def test_the_static_table_still_matches_these_ids_by_substring(model: str) -> None:
    """Guards the premise: without the fix these ids get another model's rate."""

    resolved = get_pricing_for_model(model, None, None)
    assert resolved is not None
    canonical, _price = resolved
    assert canonical != model


@pytest.mark.parametrize("model", GLOB_MATCHING_MODELS)
@pytest.mark.parametrize(
    "price_status",
    [ExternalPriceStatus.UNRESOLVED.value, ExternalPriceStatus.AMBIGUOUS.value],
)
def test_an_unresolved_external_row_keeps_a_null_cost_through_the_mapper(model: str, price_status: str) -> None:
    entry = to_request_log_entry(_log(model=model, price_status=price_status))

    assert entry.cost_usd is None, "an unresolved model must not borrow a glob-matched rate"
    assert entry.cost_breakdown.total_usd is None
    assert entry.cost_breakdown.input_usd is None
    assert entry.cost_breakdown.output_usd is None
    assert entry.price_status == price_status


def test_a_not_token_priced_row_stays_blank_rather_than_glob_priced() -> None:
    entry = to_request_log_entry(_log(price_status=ExternalPriceStatus.NOT_TOKEN_PRICED.value))

    assert entry.cost_usd is None
    assert entry.cost_breakdown.total_usd is None


def test_a_resolved_external_row_reports_its_persisted_calculated_cost() -> None:
    entry = to_request_log_entry(
        _log(
            cost_usd=0.006,
            cost_source=CostSource.CATALOG_CALCULATED.value,
            price_status=ExternalPriceStatus.RESOLVED.value,
        )
    )

    assert entry.cost_usd == pytest.approx(0.006)
    assert entry.cost_breakdown.total_usd == pytest.approx(0.006)
    assert entry.cost_source == CostSource.CATALOG_CALCULATED.value


def test_an_upstream_billed_row_reports_the_billed_amount_verbatim() -> None:
    entry = to_request_log_entry(
        _log(
            model="anthropic/claude-opus-4.5",
            cost_usd=0.00846,
            cost_source=CostSource.UPSTREAM_BILLED.value,
            price_status=ExternalPriceStatus.RESOLVED.value,
        )
    )

    assert entry.cost_usd == pytest.approx(0.00846)


def test_a_non_participating_row_still_uses_the_static_table() -> None:
    """Ollama, OmniRoute and the main proxy path are untouched by the fix."""

    entry = to_request_log_entry(_log(model="gpt-5.1", source="ollama_sidecar", price_status=None))

    assert entry.cost_usd is not None
    assert entry.cost_usd > 0
    assert entry.cost_breakdown.input_usd is not None
