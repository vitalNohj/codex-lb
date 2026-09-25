"""OpenAI-compatible listings may publish rates in more than one explicit format."""

from __future__ import annotations

import pytest

from app.core.clients.openai_compat_sidecar import published_pricing
from app.core.usage.external_pricing.catalogs import catalog_from_published_models
from app.core.usage.external_pricing.resolution import ResolutionOutcome, UnpricedReason, resolve_model_price
from app.core.usage.pricing import ModelPrice

pytestmark = pytest.mark.unit


def _catalog(*entries: dict):
    return catalog_from_published_models(
        "openai_compat:test",
        [(entry["id"], *published_pricing(entry)) for entry in entries],
    )


def test_unlid_published_rates_are_read_without_scaling() -> None:
    catalog = _catalog(
        {
            "id": "glm-5.3-flash-uncensored",
            "unlid": {
                "pricing": {
                    "input_usd_per_m": 0.42,
                    "output_usd_per_m": "1.68",
                    "cached_input_usd_per_m": 0.216,
                    "checked_at": "2026-09-10",
                }
            },
        }
    )

    entry = catalog.exact("glm-5.3-flash-uncensored")
    assert entry is not None
    # The persistent external price store has input and output rates only.
    assert entry.price == ModelPrice(input_per_1m=0.42, output_per_1m=1.68)
    result = resolve_model_price("glm-5.3-flash-uncensored", catalogs=[catalog])
    assert result.outcome is ResolutionOutcome.RESOLVED
    assert result.catalog_source == "openai_compat:test"


@pytest.mark.parametrize("bad", ["not-a-number", "NaN", "Infinity", True, {}, 10**400])
def test_unreadable_unlid_rate_is_retryable_not_a_settled_no_price(bad) -> None:
    catalog = _catalog({"id": "unlid/bad", "unlid": {"pricing": {"input_usd_per_m": bad, "output_usd_per_m": 1.68}}})
    entry = catalog.exact("unlid/bad")
    assert entry is not None
    assert entry.price is None
    assert entry.unpriced_reason is UnpricedReason.UNPARSEABLE
    assert resolve_model_price("unlid/bad", catalogs=[catalog]).outcome is ResolutionOutcome.PRICE_UNPARSEABLE


@pytest.mark.parametrize(
    "unlid", [None, {"pricing": None}, {"pricing": {"input_usd_per_m": None, "output_usd_per_m": 1.68}}]
)
def test_declared_absence_of_unlid_rate_settles(unlid) -> None:
    catalog = _catalog({"id": "unlid/not-priced", "unlid": unlid})
    entry = catalog.exact("unlid/not-priced")
    assert entry is not None
    assert entry.price is None
    assert entry.unpriced_reason is UnpricedReason.NO_TOKEN_RATE
    assert resolve_model_price("unlid/not-priced", catalogs=[catalog]).outcome is ResolutionOutcome.NOT_TOKEN_PRICED


def test_partial_unlid_rate_and_malformed_extension_are_unparseable() -> None:
    for payload in (
        {"pricing": {"input_usd_per_m": 0.42}},
        {"pricing": {"input_usd_per_million": 0.42, "output_usd_per_million": 1.68}},
        "unrecognized-shape",
    ):
        entry = _catalog({"id": "unlid/partial", "unlid": payload}).exact("unlid/partial")
        assert entry is not None
        assert entry.price is None
        assert entry.unpriced_reason is UnpricedReason.UNPARSEABLE


def test_top_level_rates_take_precedence_and_null_does_not_mask_unlid() -> None:
    unlid = {"pricing": {"input_usd_per_m": 0.42, "output_usd_per_m": 1.68}}
    catalog = _catalog(
        {"id": "vendor/top", "pricing": {"prompt": "0.000002", "completion": "0.000004"}, "unlid": unlid},
        {"id": "vendor/fallback", "pricing": None, "unlid": unlid},
        {"id": "vendor/malformed", "pricing": {"prompt": "bad", "completion": "0.000004"}, "unlid": unlid},
    )
    assert catalog.exact("vendor/top").price == ModelPrice(input_per_1m=2, output_per_1m=4)
    assert catalog.exact("vendor/fallback").price == ModelPrice(input_per_1m=0.42, output_per_1m=1.68)
    assert catalog.exact("vendor/malformed").unpriced_reason is UnpricedReason.UNPARSEABLE


def test_unpriced_generic_openai_compat_models_keep_their_existing_semantics() -> None:
    catalog = _catalog({"id": "local/unpriced"}, {"id": "local/free", "pricing": {"prompt": 0, "completion": 0}})
    assert catalog.exact("local/unpriced").unpriced_reason is UnpricedReason.NO_TOKEN_RATE
    assert catalog.exact("local/free").price == ModelPrice(input_per_1m=0, output_per_1m=0)


def test_unrecognized_unlid_pricing_fields_are_retryable() -> None:
    entry = _catalog({"id": "unlid/per-request", "unlid": {"pricing": {"image": "0.01"}}}).exact("unlid/per-request")
    assert entry is not None
    assert entry.unpriced_reason is UnpricedReason.UNPARSEABLE
