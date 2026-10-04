"""A price this build cannot read is not a price the catalog does not publish.

``parse_openai_style_catalog`` used to represent both facts as ``price=None``, so
an upstream ``pricing`` schema change read as "this model is not token priced":
a settled answer that clears the stored rate and sets no retry deadline. One pass
over a renamed schema would have erased every rate while reporting no changes.
"""

from __future__ import annotations

import pytest

from app.core.usage.external_pricing.catalogs import (
    UNLID_RATE_FORMAT,
    catalog_from_published_models,
    catalog_from_sidecar_models,
    parse_openai_style_catalog,
)
from app.core.usage.external_pricing.resolution import (
    ResolutionOutcome,
    UnpricedReason,
    resolve_model_price,
)
from app.core.usage.pricing import ModelPrice

pytestmark = pytest.mark.unit


def _payload(model_id: str, pricing: object) -> dict:
    return {"data": [{"id": model_id, "pricing": pricing}]}


def test_an_entry_with_no_pricing_block_is_a_settled_not_token_priced_answer() -> None:
    catalog = parse_openai_style_catalog(_payload("vendor/router", None), source="openrouter")

    entry = catalog.exact("vendor/router")
    assert entry is not None
    assert entry.price is None
    assert entry.unpriced_reason is UnpricedReason.NO_TOKEN_RATE

    resolution = resolve_model_price("vendor/router", catalogs=[catalog])
    assert resolution.outcome is ResolutionOutcome.NOT_TOKEN_PRICED


def test_an_entry_priced_only_per_request_is_still_not_token_priced() -> None:
    """Real per-request models publish a pricing block without token rates."""

    catalog = parse_openai_style_catalog(
        _payload("vendor/image-model", {"request": "0.04", "image": "0.08"}),
        source="openrouter",
    )

    entry = catalog.exact("vendor/image-model")
    assert entry is not None
    assert entry.unpriced_reason is UnpricedReason.NO_TOKEN_RATE
    assert resolve_model_price("vendor/image-model", catalogs=[catalog]).outcome is (ResolutionOutcome.NOT_TOKEN_PRICED)


@pytest.mark.parametrize(
    "pricing",
    [
        pytest.param({"prompt": "-1", "completion": "-1", "request": "-1"}, id="negative-sentinel"),
        pytest.param({"prompt": -1, "completion": -1}, id="negative-sentinel-numeric"),
        pytest.param({"prompt": None, "completion": None, "request": "0.04"}, id="explicit-null"),
        pytest.param({"prompt": "", "completion": ""}, id="empty-string"),
        pytest.param({"prompt": "-1", "completion": "0.000002"}, id="one-side-declared-none"),
    ],
)
def test_a_catalog_declared_no_price_is_a_settled_not_token_priced_answer(pricing: object) -> None:
    """A sentinel is the catalog answering, not this build failing to read it.

    ``openrouter/auto`` publishes ``-1`` for prompt and completion to say it has
    no per-token rate. Reading that as a parse failure marks a genuine router
    model ``!!`` and re-looks it up on the backoff schedule forever, instead of
    settling it as ``--`` with no retry state.
    """

    catalog = parse_openai_style_catalog(_payload("openrouter/auto", pricing), source="openrouter")

    entry = catalog.exact("openrouter/auto")
    assert entry is not None
    assert entry.price is None
    assert entry.unpriced_reason is UnpricedReason.NO_TOKEN_RATE

    resolution = resolve_model_price("openrouter/auto", catalogs=[catalog])
    assert resolution.outcome is ResolutionOutcome.NOT_TOKEN_PRICED


@pytest.mark.parametrize(
    "pricing",
    [
        pytest.param({"prompt": "not-a-number", "completion": "0.000002"}, id="unreadable-value"),
        pytest.param({"prompt": {"per_1m": 3.0}, "completion": {"per_1m": 6.0}}, id="restructured-shape"),
        pytest.param({"prompt": "0.000001"}, id="half-a-rate"),
        pytest.param({"prompt_usd_per_1m": "3.0", "completion": "0.000002"}, id="renamed-unit-field"),
        pytest.param({"prompt": "NaN", "completion": "0.000002"}, id="nan"),
        pytest.param({"prompt": "Infinity", "completion": "0.000002"}, id="infinity"),
        pytest.param({"prompt": "1e308", "completion": "0.000002"}, id="scaled-overflow"),
        pytest.param({"prompt": 10**400, "completion": "0.000002"}, id="integer-overflow"),
        pytest.param("temporarily unavailable", id="invalid-scalar"),
        pytest.param(["temporarily unavailable"], id="invalid-list"),
    ],
)
def test_an_entry_whose_declared_token_rates_cannot_be_read_is_unparseable(pricing: object) -> None:
    catalog = parse_openai_style_catalog(_payload("vendor/model-x", pricing), source="openrouter")

    entry = catalog.exact("vendor/model-x")
    assert entry is not None
    assert entry.price is None
    assert entry.unpriced_reason is UnpricedReason.UNPARSEABLE

    resolution = resolve_model_price("vendor/model-x", catalogs=[catalog])
    assert resolution.outcome is ResolutionOutcome.PRICE_UNPARSEABLE
    assert resolution.catalog_model == "vendor/model-x"


@pytest.mark.parametrize(
    "price",
    [
        pytest.param(ModelPrice(float("nan"), 2.0), id="nan-input"),
        pytest.param(ModelPrice(1.0, float("inf")), id="infinite-output"),
        pytest.param(ModelPrice(1.0, 2.0, cached_input_per_1m=float("inf")), id="infinite-cache-read"),
    ],
)
def test_a_non_finite_preparsed_sidecar_rate_is_unparseable(price: ModelPrice) -> None:
    catalog = catalog_from_sidecar_models(
        "orcarouter",
        [("vendor/model-x", price, {"prompt": "0.000001", "completion": "0.000002"})],
    )

    entry = catalog.exact("vendor/model-x")
    assert entry is not None
    assert entry.price is None
    assert entry.unpriced_reason is UnpricedReason.UNPARSEABLE
    assert resolve_model_price("vendor/model-x", catalogs=[catalog]).outcome is ResolutionOutcome.PRICE_UNPARSEABLE


_PRICED = {"prompt": "0.000004", "completion": "0.00002"}


@pytest.mark.parametrize(
    "cache_read",
    [
        pytest.param("not-a-number", id="unreadable-value"),
        pytest.param({"per_token": "0.0000002"}, id="restructured-shape"),
        pytest.param(True, id="boolean"),
        pytest.param("NaN", id="nan"),
        pytest.param("1e308", id="scaled-overflow"),
        pytest.param(10**400, id="integer-overflow"),
    ],
)
def test_an_unreadable_cache_read_rate_makes_the_entry_unparseable(cache_read: object) -> None:
    """Pricing the entry without it would charge cache reads at the input rate.

    For cache-heavy traffic that is a figure many times too high, and a refresh
    would overwrite a stored cache-read rate with it.
    """

    catalog = parse_openai_style_catalog(
        _payload("vendor/model-x", {**_PRICED, "input_cache_read": cache_read}),
        source="openrouter",
    )

    entry = catalog.exact("vendor/model-x")
    assert entry is not None
    assert entry.price is None
    assert entry.unpriced_reason is UnpricedReason.UNPARSEABLE
    assert resolve_model_price("vendor/model-x", catalogs=[catalog]).outcome is ResolutionOutcome.PRICE_UNPARSEABLE


@pytest.mark.parametrize(
    "pricing",
    [
        pytest.param(_PRICED, id="absent"),
        pytest.param({**_PRICED, "input_cache_read": None}, id="explicit-null"),
        pytest.param({**_PRICED, "input_cache_read": ""}, id="empty-string"),
        pytest.param({**_PRICED, "input_cache_read": "-1"}, id="negative-sentinel"),
    ],
)
def test_a_catalog_without_a_cache_read_rate_still_prices_the_model(pricing: object) -> None:
    """No published cache-read rate is an answer: cached input costs the input rate."""

    catalog = parse_openai_style_catalog(_payload("vendor/model-x", pricing), source="openrouter")

    resolution = resolve_model_price("vendor/model-x", catalogs=[catalog])

    assert resolution.outcome is ResolutionOutcome.RESOLVED
    assert resolution.price == ModelPrice(4.0, 20.0)


def test_a_published_cache_read_rate_is_kept() -> None:
    catalog = parse_openai_style_catalog(
        _payload("vendor/model-x", {**_PRICED, "input_cache_read": "0.0000002"}),
        source="openrouter",
    )

    resolution = resolve_model_price("vendor/model-x", catalogs=[catalog])

    assert resolution.price is not None
    assert resolution.price.cached_input_per_1m == pytest.approx(0.2)


def test_a_sidecar_listing_with_an_unreadable_cache_read_rate_is_unparseable() -> None:
    """The sidecar's own parser reads the unreadable field as absent.

    Only the raw block it carries shows that a rate was published.
    """

    catalog = catalog_from_sidecar_models(
        "orcarouter",
        [("vendor/model-x", ModelPrice(4.0, 20.0), {**_PRICED, "input_cache_read": "n/a"})],
    )

    entry = catalog.exact("vendor/model-x")
    assert entry is not None
    assert entry.price is None
    assert entry.unpriced_reason is UnpricedReason.UNPARSEABLE


def test_a_published_rate_block_with_an_unreadable_cache_read_rate_is_unparseable() -> None:
    readable = {"input_usd_per_m": 3.0, "output_usd_per_m": 15.0, "cached_input_usd_per_m": 0.3}
    unreadable = {**readable, "cached_input_usd_per_m": {"usd": 0.3}}

    catalog = catalog_from_published_models(
        "openai_compat:endpoint",
        [("vendor/good", readable, UNLID_RATE_FORMAT), ("vendor/bad", unreadable, UNLID_RATE_FORMAT)],
    )

    good = catalog.exact("vendor/good")
    bad = catalog.exact("vendor/bad")
    assert good is not None and good.price == ModelPrice(3.0, 15.0, cached_input_per_1m=0.3)
    assert bad is not None and bad.price is None
    assert bad.unpriced_reason is UnpricedReason.UNPARSEABLE


def test_a_readable_price_is_unaffected_by_the_distinction() -> None:
    catalog = parse_openai_style_catalog(
        _payload("vendor/priced", {"prompt": "0.000002", "completion": "0.000004"}),
        source="openrouter",
    )

    resolution = resolve_model_price("vendor/priced", catalogs=[catalog])

    assert resolution.outcome is ResolutionOutcome.RESOLVED
    assert resolution.price is not None
    assert resolution.price.input_per_1m == pytest.approx(2.0)
    assert resolution.price.output_per_1m == pytest.approx(4.0)
