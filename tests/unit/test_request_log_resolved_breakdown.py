"""External request totals never acquire an unprovable component split."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.db.models import CostSource, ExternalPriceStatus, RequestLog
from app.modules.request_logs.mappers import to_request_log_entry

pytestmark = pytest.mark.unit

# 800 uncached input + 200 cached input, both at the full input rate, + 500 out.
EXPECTED_INPUT_USD = 800 * 2.0 / 1e6
EXPECTED_CACHED_USD = 200 * 2.0 / 1e6
EXPECTED_OUTPUT_USD = 500 * 4.0 / 1e6
EXPECTED_TOTAL = EXPECTED_INPUT_USD + EXPECTED_CACHED_USD + EXPECTED_OUTPUT_USD


def _log(**overrides) -> RequestLog:
    values = {
        "request_id": "req-breakdown",
        "request_kind": "normal",
        # Matches the retired ``*gpt-4o*`` glob, so a static-table split would be
        # visibly wrong rather than coincidentally right.
        "model": "orcarouter/gpt-4o-lookalike",
        "source": "orcarouter_sidecar",
        "status": "success",
        "error_code": None,
        "requested_at": datetime(2026, 8, 29, tzinfo=timezone.utc),
        "input_tokens": 1_000,
        "output_tokens": 500,
        "cached_input_tokens": 200,
        "reasoning_tokens": None,
        "cost_usd": EXPECTED_TOTAL,
        "cost_source": CostSource.CATALOG_CALCULATED.value,
        "price_status": ExternalPriceStatus.RESOLVED.value,
    }
    values.update(overrides)
    return RequestLog(**values)


def test_a_resolved_external_row_reports_only_its_persisted_total() -> None:
    entry = to_request_log_entry(_log())

    assert entry.cost_usd == pytest.approx(EXPECTED_TOTAL)
    assert entry.cost_breakdown.total_usd == pytest.approx(EXPECTED_TOTAL)
    assert entry.cost_breakdown.input_usd is None
    assert entry.cost_breakdown.cached_input_usd is None
    assert entry.cost_breakdown.output_usd is None


def test_equal_totals_cannot_prove_the_historical_component_rate() -> None:
    entry = to_request_log_entry(
        _log(
            input_tokens=1_000,
            output_tokens=1_000,
            cached_input_tokens=0,
            cost_usd=0.000003,
        )
    )

    assert entry.cost_usd == pytest.approx(0.000003)
    assert entry.cost_breakdown.total_usd == pytest.approx(0.000003)
    assert entry.cost_breakdown.input_usd is None
    assert entry.cost_breakdown.cached_input_usd is None
    assert entry.cost_breakdown.output_usd is None


def test_an_upstream_billed_total_is_never_split_by_a_list_rate() -> None:
    """The billed debit is authoritative and is not reconciled against list price."""

    entry = to_request_log_entry(_log(cost_usd=0.00846, cost_source=CostSource.UPSTREAM_BILLED.value))

    assert entry.cost_usd == pytest.approx(0.00846)
    assert entry.cost_breakdown.input_usd is None
    assert entry.cost_breakdown.output_usd is None


def test_an_unresolved_row_still_reports_nothing_at_all() -> None:
    """The acceptance-critical property is unchanged by restoring the split."""

    entry = to_request_log_entry(
        _log(cost_usd=None, cost_source=None, price_status=ExternalPriceStatus.UNRESOLVED.value)
    )

    assert entry.cost_usd is None
    assert entry.cost_breakdown.total_usd is None
    assert entry.cost_breakdown.input_usd is None


# A row that does not participate in external price resolution but does state its
# own provenance. ``gpt-5.1`` is an exact static-table entry, so the split below
# is the model's real rate, not a substring match on some other model's name.
_STATIC_TOTAL = 0.006025


def _non_participating_log(**overrides):
    values = {
        "model": "gpt-5.1",
        "source": "omniroute_sidecar",
        "input_tokens": 1_000,
        "output_tokens": 500,
        "cached_input_tokens": 200,
        "cost_usd": _STATIC_TOTAL,
        "price_status": None,
    }
    values.update(overrides)
    return _log(**values)


@pytest.mark.parametrize(
    "cost_source",
    [CostSource.UPSTREAM_BILLED.value, CostSource.OPERATOR_CONFIGURED.value],
)
def test_a_non_participating_row_keeps_its_component_split(cost_source: str) -> None:
    """Suppression must not reach rows the external resolver does not own.

    An OmniRoute/Ollama row whose upstream reported a billed amount, and every
    operator-configured model-source row, state a ``cost_source`` without
    participating in external price resolution. They kept showing
    "$0.01 = 800 Input + 200 Cached" before this work and must keep showing it:
    the request-details dialog renders no Cost section at all when every component
    is null.
    """

    entry = to_request_log_entry(_non_participating_log(cost_source=cost_source))

    assert entry.cost_usd == pytest.approx(_STATIC_TOTAL)
    assert entry.cost_breakdown.input_usd is not None
    assert entry.cost_breakdown.cached_input_usd is not None
    assert entry.cost_breakdown.output_usd is not None
    components = (
        entry.cost_breakdown.input_usd + entry.cost_breakdown.cached_input_usd + entry.cost_breakdown.output_usd
    )
    assert components == pytest.approx(entry.cost_breakdown.total_usd)


def test_a_non_participating_row_whose_total_disagrees_shows_no_invented_split() -> None:
    """An upstream debit that does not reconcile with list price stands alone."""

    entry = to_request_log_entry(
        _non_participating_log(cost_usd=0.5, cost_source=CostSource.UPSTREAM_BILLED.value),
    )

    assert entry.cost_usd == pytest.approx(0.5)
    assert entry.cost_breakdown.input_usd is None
    assert entry.cost_breakdown.output_usd is None


def test_a_participating_billed_row_with_no_status_still_avoids_the_static_table() -> None:
    """A participating row can carry a billed amount and no ``price_status``.

    ``external_request_cost`` reports no status when the resolver had no question
    to answer for the id, yet the billed branch still fires, so the row is written
    ``upstream_billed`` with ``price_status`` NULL. Keying participation on the
    status alone let that row fall into the static-table path, where the glob
    aliases answer for ids they have never heard of. The serving integration is
    what settles ownership, not a column that may legitimately be NULL.

    The total below is exactly what the static table computes for these tokens, so
    the fallback reconciles and does produce a split -- which is what makes the
    difference observable rather than hidden behind a mismatch.
    """

    entry = to_request_log_entry(
        _log(
            model="gpt-5.1",
            source="orcarouter_sidecar",
            cost_usd=_STATIC_TOTAL,
            cost_source=CostSource.UPSTREAM_BILLED.value,
            price_status=None,
        )
    )

    assert entry.cost_usd == pytest.approx(_STATIC_TOTAL), "the billed amount stays authoritative"
    assert entry.cost_breakdown.input_usd is None, "no static-table split on a participating row"
    assert entry.cost_breakdown.cached_input_usd is None
    assert entry.cost_breakdown.output_usd is None
