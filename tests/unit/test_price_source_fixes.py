"""Source-backed alias, cache-write, and context-tier pricing regressions."""

from __future__ import annotations

import importlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.core.usage.external_pricing.catalogs import parse_openai_style_catalog
from app.core.usage.external_pricing.resolution import ResolutionOutcome, resolve_model_price
from app.core.usage.pricing import (
    DEFAULT_PRICING_MODELS,
    ModelPrice,
    UsageTokens,
    calculate_cost_breakdown_from_usage,
)
from app.core.usage.pricing_catalog import get_active_prices

pytestmark = pytest.mark.unit


@pytest.fixture
def recorded_catalog():
    # Recorded pricing-only excerpt; no network access in tests.
    payload = json.loads((Path(__file__).parents[1] / "fixtures/openrouter_write_context_pricing.json").read_text())
    return parse_openai_style_catalog(payload, source="openrouter:reference")


@pytest.mark.parametrize("provider", ["cliproxy", "openrouter", "orcarouter", None])
def test_only_cliproxy_peels_account_alias_after_routing_prefix(recorded_catalog, provider):
    result = resolve_model_price(
        "cc/lb0123456789/claude-opus-5-5",
        catalogs=[recorded_catalog],
        prefixes=[("cc/", True)],
        provider=provider,
    )
    if provider != "cliproxy":
        assert result.outcome is ResolutionOutcome.UNRESOLVED
        return
    base = resolve_model_price("claude-opus-5-5", catalogs=[recorded_catalog])
    assert result.outcome is ResolutionOutcome.RESOLVED
    assert result.price == base.price
    assert result.catalog_model == base.catalog_model
    assert result.step == f"prefix+account-alias+{base.step}"


@pytest.mark.parametrize("alias", ["lb012345678/", "lb01234567890/", "lb012345678g/"])
def test_account_alias_requires_picker_rule(recorded_catalog, alias):
    assert (
        resolve_model_price(
            f"cc/{alias}claude-opus-5-5",
            catalogs=[recorded_catalog],
            prefixes=[("cc/", True)],
            provider="cliproxy",
        ).outcome
        is ResolutionOutcome.UNRESOLVED
    )


def test_recorded_openrouter_keeps_both_write_ttls_and_context_tier(recorded_catalog):
    entry = recorded_catalog.exact("anthropic/claude-haiku-5.5")
    assert entry is not None
    price = entry.price
    assert price is not None
    assert price.cache_write_input_per_1m == pytest.approx(0.125)
    assert price.cache_write_input_1h_per_1m == pytest.approx(0.2)
    assert price.long_context_threshold_tokens == 100_000
    assert price.long_context_input_per_1m == pytest.approx(0.5)
    assert price.long_context_cached_input_per_1m == pytest.approx(0.05)
    assert price.long_context_output_per_1m == pytest.approx(2.5)
    assert price.long_context_cache_write_input_per_1m == pytest.approx(0.625)
    assert price.long_context_cache_write_input_1h_per_1m == pytest.approx(1.0)


def test_parser_selects_lowest_override_threshold_not_array_order():
    catalog = parse_openai_style_catalog(
        {
            "data": [
                {
                    "id": "vendor/model",
                    "pricing": {
                        "prompt": "0.000001",
                        "completion": "0.000002",
                        "input_cache_write": "0.00000125",
                        "overrides": [
                            {"min_prompt_tokens": 200_000, "prompt": "0.000003", "completion": "0.000006"},
                            {"min_prompt_tokens": 100_000, "prompt": "0.000002", "completion": "0.000004"},
                        ],
                    },
                }
            ]
        },
        source="openrouter",
    )
    entry = catalog.exact("vendor/model")
    assert entry is not None and entry.price is not None
    assert entry.price.long_context_threshold_tokens == 100_000
    assert entry.price.long_context_input_per_1m == 2
    assert entry.price.long_context_output_per_1m == 4


@pytest.mark.parametrize(
    "model",
    [
        "claude-opus-5-5",
        "claude-sonnet-5-5",
        "claude-haiku-5-5",
        "claude-fable-5-1",
    ],
)
@pytest.mark.parametrize("input_tokens", [100_000, 300_000])
def test_claude_cache_write_cost_is_exactly_unchanged(model, input_tokens):
    price = DEFAULT_PRICING_MODELS[model]
    assert price.cache_write_input_per_1m == 2 * price.input_per_1m
    usage = UsageTokens(input_tokens, 1000, cached_input_tokens=20_000, cache_write_input_tokens=30_000)
    legacy = replace(price, cache_write_input_per_1m=None, long_context_cache_write_input_per_1m=None)
    actual = calculate_cost_breakdown_from_usage(usage, price)
    assert actual == calculate_cost_breakdown_from_usage(usage, legacy)


@pytest.mark.parametrize("input_tokens,write_rate", [(272_000, 2.5), (272_001, 5.0)])
def test_openai_uses_stored_write_rate_and_long_context_boundary(recorded_catalog, input_tokens, write_rate):
    entry = recorded_catalog.exact("openai/gpt-6.1-sol")
    assert entry is not None and entry.price is not None
    usage = UsageTokens(input_tokens, 1000, cache_write_input_tokens=100_000)
    cost = calculate_cost_breakdown_from_usage(usage, entry.price)
    assert cost is not None
    assert cost.cache_write_input_usd == pytest.approx(0.1 * write_rate)
    assert DEFAULT_PRICING_MODELS["gpt-6.1-sol"].cache_write_input_per_1m == 2.5
    # Bundled snapshots predating the new fields must not erase the verified rate.
    assert get_active_prices()["gpt-6.1-sol"].cache_write_input_per_1m == 2.5


@pytest.mark.parametrize("write_rate,expected", [(None, 4.0), (0.0, 0.0), (1.25, 1.25)])
def test_missing_write_rate_falls_back_but_explicit_zero_is_free(write_rate, expected):
    cost = calculate_cost_breakdown_from_usage(
        UsageTokens(1_000_000, 0, cache_write_input_tokens=1_000_000),
        ModelPrice(2.0, 6.0, cache_write_input_per_1m=write_rate),
    )
    assert cost is not None
    assert cost.cache_write_input_usd == expected


@pytest.mark.parametrize(
    "tier,input_tokens,write_rate",
    [
        (None, 100_000, 2.5),
        (None, 300_000, 5.0),
        ("fast", 100_000, 5.0),
        ("flex", 100_000, 1.25),
        ("flex", 300_000, 2.5),
    ],
)
def test_openai_builtin_write_rate_tracks_service_tier(tier, input_tokens, write_rate):
    cost = calculate_cost_breakdown_from_usage(
        UsageTokens(input_tokens, 0, cache_write_input_tokens=50_000),
        DEFAULT_PRICING_MODELS["gpt-6.1-sol"],
        service_tier=tier,
    )
    assert cost is not None
    assert cost.cache_write_input_usd == pytest.approx(0.05 * write_rate)


def test_external_rate_migration_preserves_old_rows_with_null_new_columns(monkeypatch):
    migration = importlib.import_module("app.db.alembic.versions.20261102_000000_external_price_write_context_rates")
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE external_model_prices (id INTEGER PRIMARY KEY, input_per_1m FLOAT)"))
        connection.execute(sa.text("INSERT INTO external_model_prices VALUES (1, 2.0)"))
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        migration.upgrade()  # Startup may encounter an already-added column.
        row = connection.execute(sa.text("SELECT * FROM external_model_prices")).mappings().one()
        assert row["input_per_1m"] == 2.0
        assert row["cache_write_input_per_1m"] is None
        assert row["cache_write_input_1h_per_1m"] is None
        assert row["long_context_threshold_tokens"] is None
        assert row["long_context_cache_write_input_per_1m"] is None
        connection.execute(
            sa.text(
                "UPDATE external_model_prices SET cache_write_input_per_1m = 2.5, "
                "long_context_threshold_tokens = 272000"
            )
        )
        migration.downgrade()
        row = connection.execute(sa.text("SELECT * FROM external_model_prices")).mappings().one()
        assert row["input_per_1m"] == 2.0
        assert row["cache_write_input_per_1m"] == 2.5
        assert row["long_context_threshold_tokens"] == 272_000
        migration.upgrade()
        assert (
            connection.execute(sa.text("SELECT cache_write_input_per_1m FROM external_model_prices")).scalar_one()
            == 2.5
        )
    engine.dispose()


def test_grok_absent_write_rate_is_not_assumed_free(recorded_catalog):
    entry = recorded_catalog.exact("x-ai/grok-4.7")
    assert entry is not None and entry.price is not None
    assert entry.price.cache_write_input_per_1m is None
    assert entry.price.long_context_threshold_tokens == 200_000
    assert entry.price.long_context_input_per_1m == 4
    assert entry.price.long_context_cached_input_per_1m == 1
    assert entry.price.long_context_output_per_1m == 12


@pytest.mark.parametrize(
    "input_tokens,rates",
    [
        (272_000, (1, 0.05, 5, 1.25)),
        (272_001, (2, 0.10, 7.5, 2.5)),
    ],
)
def test_terra_standard_prices(input_tokens, rates):
    price = DEFAULT_PRICING_MODELS["gpt-6.1-terra"]
    cost = calculate_cost_breakdown_from_usage(
        UsageTokens(input_tokens, 1000, cached_input_tokens=100_000, cache_write_input_tokens=100_000), price
    )
    assert cost is not None
    input_rate, cached_rate, output_rate, write_rate = rates
    assert cost.input_usd == pytest.approx((input_tokens - 200_000) / 1e6 * input_rate)
    assert cost.cached_input_usd == pytest.approx(0.1 * cached_rate)
    assert cost.output_usd == pytest.approx(0.001 * output_rate)
    assert cost.cache_write_input_usd == pytest.approx(0.1 * write_rate)
