from __future__ import annotations

import json
from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.models import catalog, router
from app.core.models.local import LocalCatalog
from app.core.models.types import ModelPrice
from app.core.openai import model_registry
from app.core.usage import pricing_catalog
from app.core.usage.logs import calculated_cost_from_log
from app.core.usage.pricing import CostItem, UsageTokens, calculate_costs, get_pricing_for_model
from app.db.models import RequestLog
from app.modules.proxy.model_pricing import model_pricing

pytestmark = pytest.mark.unit
BASELINE = json.loads((Path(__file__).parents[1] / "fixtures/model_catalog_compatibility.json").read_text())


@pytest.fixture(autouse=True)
def isolated_sources(monkeypatch):
    monkeypatch.setattr(pricing_catalog, "_prices", None)
    monkeypatch.setattr(pricing_catalog, "_capabilities", None)
    monkeypatch.setattr(router, "_models", None)
    monkeypatch.setattr(model_registry, "_model_registry", model_registry.ModelRegistry())


def test_every_pre_migration_served_price_is_exactly_unchanged():
    for model, expected in BASELINE["prices"].items():
        record = catalog.resolve_model(model)
        assert record.price is not None, model
        assert {key: asdict(record.price)[key] for key in expected} == expected, model


def test_bootstrap_ids_metadata_and_windows_are_unchanged():
    models = model_registry.get_model_registry().get_models_with_fallback()
    assert set(models) == set(BASELINE["bootstrap"])
    for model, expected in BASELINE["bootstrap"].items():
        assert json.loads(json.dumps(asdict(models[model]), default=sorted)) == expected, model
        assert catalog.resolve_model(model).context_window == expected["context_window"]
    for model, bounds in BASELINE["sidecar_bounds"].items():
        record = catalog.resolve_model(model)
        assert record.context_window == bounds["context_window"], model
        assert record.max_output_tokens == bounds["cap"], model


@pytest.mark.parametrize("model", BASELINE["prices"])
@pytest.mark.parametrize("tier", [None, "priority", "fast", "flex", "batch"])
def test_log_cost_matches_published_rates_for_every_served_model(model, tier):
    record = catalog.resolve_model(model)
    assert record.price is not None
    published = model_pricing(record.price)
    rates = {
        "priority": published.priority,
        "fast": published.priority,
        "flex": published.flex,
        "batch": published.batch,
    }.get(tier, published)
    rates = rates or published
    threshold = record.price.long_context_threshold_tokens
    for tokens in (1000, int(threshold) + 1) if threshold else (1000,):
        active = (
            rates.long_context
            if rates.long_context is not None and tokens > rates.long_context.threshold_tokens
            else rates
        )
        log = RequestLog(
            model=model,
            input_tokens=tokens,
            output_tokens=47,
            cached_input_tokens=113,
            cache_write_input_tokens=59,
            service_tier=tier,
        )
        listed = (
            (tokens - 113 - 59) * active.input + 113 * active.cache_read + 59 * active.cache_write + 47 * active.output
        ) / 1_000_000
        logged = calculated_cost_from_log(log)
        assert logged == pytest.approx(listed, abs=1e-14), model
        assert logged is not None
        totals = calculate_costs([CostItem(model, UsageTokens(tokens, 47, 113, 59), tier)])
        assert totals.total_usd_7d == round(logged, 6), model


@pytest.mark.parametrize("model", ["gpt-6.1-sol", "openai/gpt-6.1-sol", "codex/gpt-6.1-sol-2026-10-20"])
def test_native_spellings_share_the_verified_872k_window_and_price(model):
    record = catalog.resolve_model(model)
    assert record.canonical_id == "gpt-6.1-sol"
    assert record.context_window == 872000
    assert record.price == catalog.resolve_model("gpt-6.1-sol").price
    assert record.provenance["context_window"] == "local"


def test_claude_identity_never_borrows_another_releases_capabilities_or_price():
    canonical = catalog.resolve_model("claude-opus-4-6")
    assert catalog.resolve_model("cc/claude-opus-4-6").price == canonical.price
    unknown = catalog.resolve_model("claude-opus-4-6-future")
    assert unknown.price is None
    assert unknown.context_window is None
    assert catalog.resolve_model("cc/cc/claude-opus-4-6").price is None
    assert catalog.resolve_model("cc/cc/claude-opus-4-6").context_window is None


async def test_live_codex_ceiling_beats_cliproxy_272k_and_local_can_correct_each_field(monkeypatch):
    key = "gpt-catalog-test"
    monkeypatch.setattr(
        router, "_models", {key: router.RouterModel(id=key, context_length=272000, max_completion_tokens=4096)}
    )
    model = replace(
        next(iter(model_registry.get_model_registry().get_models_with_fallback().values())),
        slug=key,
        context_window=272000,
        raw={"max_context_window": 872000, "max_output_tokens": 128000},
    )
    await model_registry.get_model_registry().update({"plus": [model]})
    pricing_catalog.install_prices({key: ModelPrice(2, 18, 0.2)})
    record = catalog.resolve_model(key)
    assert record.context_window == 872000
    assert record.max_output_tokens == 128000
    assert record.provenance["context_window"] == "codex"
    assert record.provenance["price.output_per_1m"] == "external:pricing"
    local = LocalCatalog.model_validate(
        {
            "schema_version": 1,
            "models": {
                key: {
                    "context_window": 800000,
                    "thinking_levels": ["low", "max"],
                    "max_output_tokens": 64000,
                    "input_modalities": ["text", "image"],
                    "price_overrides": {"output_per_1m": 19},
                }
            },
        }
    )
    monkeypatch.setattr(catalog, "load_local_catalog", lambda: local)
    record = catalog.resolve_model(key)
    assert record.context_window == 800000
    assert record.max_output_tokens == 64000
    assert record.thinking_levels == ("low", "max")
    assert record.price == ModelPrice(2, 19, 0.2)
    assert record.provenance["price.input_per_1m"] == "external:pricing"
    assert record.provenance["price.output_per_1m"] == "local"
    assert catalog.resolve_model(key, overrides={key: 900000}).context_window == 872000


def test_migrated_fallback_prices_do_not_pin_external_updates(monkeypatch):
    model = "gpt-6.1-sol"
    monkeypatch.setattr(pricing_catalog, "_prices", {})
    fallback = catalog.load_local_catalog().models[model].fallback_price
    assert fallback is not None
    assert catalog.resolve_model(model).price == fallback
    assert catalog.resolve_model(model).provenance["price.input_per_1m"] == "local:fallback"
    updated = ModelPrice(3, 11, 0.3)
    pricing_catalog.install_prices({model: updated})
    assert catalog.resolve_model(model).price == updated
    assert catalog.resolve_model(model).provenance["price.input_per_1m"] == "external:pricing"


def test_external_prices_are_provider_scoped_and_unknown_never_borrows_native_rate():
    assert catalog.resolve_model("gpt-6.1-sol", provider="openrouter", isolated_price=True).price is None
    price = ModelPrice(9, 90, 0.9, cache_write_input_1h_per_1m=18)
    record = catalog.resolve_model("gpt-6.1-sol", provider="cliproxy", price=price, isolated_price=True)
    assert record.price == price
    assert record.provenance["price.input_per_1m"] == "external:cliproxy"
    assert get_pricing_for_model("gpt-6.1-sol")[1] != price


def test_codex_operator_budget_reports_the_wire_maximums_actual_provenance():
    from app.modules.proxy.api import _to_codex_model_entry

    model = replace(
        next(iter(model_registry.get_model_registry().get_models_with_fallback().values())),
        slug="catalog-provenance",
        raw={"max_context_window": 872000},
    )
    entry = _to_codex_model_entry(model, context_window_overrides={model.slug: 500000})
    assert entry.model_dump()["max_context_window"] == 500000
    assert entry.catalog_provenance["max_context_window"] == "operator"
    assert entry.catalog_provenance["context_window"] == "operator"


def test_subscription_capability_corrections_do_not_replace_another_providers_published_window():
    native = catalog.resolve_model("gpt-6.1-sol")
    assert native.context_window == 872000
    api = catalog.resolve_model(
        "openai/gpt-6.1-sol", provider="openrouter", isolated_price=True, raw={"context_length": 1000000}
    )
    assert api.context_window == 1000000
    assert api.provenance["context_window"] == "external:openrouter"
    claude = catalog.resolve_model(
        "claude-opus-4-6",
        provider="openrouter",
        isolated_price=True,
        raw={"context_length": 200000, "input_modalities": ["text"]},
    )
    assert claude.context_window == 200000
    assert claude.input_modalities == ("text",)


def test_new_model_needs_only_one_local_entry(monkeypatch):
    local = LocalCatalog.model_validate(
        {
            "schema_version": 1,
            "models": {
                "brand-new-model": {
                    "provider": "example",
                    "context_window": 123456,
                    "max_output_tokens": 8192,
                    "thinking_levels": ["low", "high"],
                    "input_modalities": ["text"],
                    "price": {"input_per_1m": 3, "output_per_1m": 12},
                }
            },
        }
    )
    monkeypatch.setattr(catalog, "load_local_catalog", lambda: local)
    record = catalog.resolve_model("brand-new-model")
    assert record.context_window == 123456
    assert record.price == ModelPrice(3, 12)
    assert record.provenance["context_window"] == "local"
    assert get_pricing_for_model("brand-new-model") == ("brand-new-model", ModelPrice(3, 12))


def test_offline_cache_restoration_falls_back_to_bundled_snapshot(tmp_path):
    bad = tmp_path / "broken.json"
    bad.write_text("not json")
    router.restore_router_models(bad)
    assert catalog.resolve_model("claude-opus-4-6").context_window == 1000000
    assert router.get_router_models()


async def test_failed_refresh_retains_last_good_model_metadata(monkeypatch, tmp_path):
    previous = dict(router.get_router_models())
    session = AsyncMock()
    session.__aenter__.side_effect = OSError("offline")
    monkeypatch.setattr(router.aiohttp, "ClientSession", lambda **kwargs: session)
    with pytest.raises(OSError, match="offline"):
        await router.refresh_router_models(tmp_path / "catalog.json")
    assert router.get_router_models() == previous


def test_malformed_upstream_snapshot_is_rejected_without_replacing_last_good():
    previous = dict(router.get_router_models())
    with pytest.raises(ValueError):
        router.parse_router_models({"claude": [{"id": "bad", "context_length": -1}]})
    assert router.get_router_models() == previous


def test_full_prices_preserve_long_lived_writes_and_batch():
    price = ModelPrice(
        2,
        10,
        0.2,
        cache_write_input_per_1m=2.5,
        cache_write_input_1h_per_1m=4,
        batch_input_per_1m=1,
        batch_output_per_1m=5,
        batch_cached_input_per_1m=0.1,
    )
    published = model_pricing(price)
    assert published.cache_write == 4
    assert published.cache_write_1h == 4
    assert published.batch is not None
    assert published.batch.input == 1
    assert published.batch.output == 5


async def test_refresh_validates_persists_and_restores_upstream_models(monkeypatch, tmp_path):
    payload = {
        "grok": [
            {
                "id": "grok-new",
                "context_length": 300000,
                "max_completion_tokens": 16000,
                "thinking": {"levels": ["low", "high"]},
            }
        ]
    }

    async def chunks(size):
        yield json.dumps(payload).encode()

    @asynccontextmanager
    async def response(url):
        assert url == router.ROUTER_MODELS_URL
        yield SimpleNamespace(raise_for_status=lambda: None, content=SimpleNamespace(iter_chunked=chunks))

    @asynccontextmanager
    async def session(**kwargs):
        yield SimpleNamespace(get=response)

    monkeypatch.setattr(router.aiohttp, "ClientSession", session)
    path = tmp_path / "models.json"
    await router.refresh_router_models(path)
    assert json.loads(path.read_text()) == payload
    monkeypatch.setattr(router, "_models", None)
    router.restore_router_models(path)
    record = catalog.resolve_model("grok-new")
    assert record.context_window == 300000
    assert record.thinking_levels == ("low", "high")
    assert record.provider == "xai"
    assert record.provenance["context_window"] == "cliproxy"


async def test_provider_local_price_is_used_before_external_lookup(monkeypatch):
    from app.core.usage.external_pricing import service

    local = LocalCatalog.model_validate(
        {
            "schema_version": 1,
            "models": {
                "brand-new": {
                    "aliases": ["brand-latest"],
                    "context_window": 200000,
                    "provider_prices": {"cliproxy": {"input_per_1m": 2, "output_per_1m": 10}},
                }
            },
        }
    )
    monkeypatch.setattr(catalog, "load_local_catalog", lambda: local)
    read = AsyncMock(side_effect=AssertionError("a local correction needs no external lookup"))
    monkeypatch.setattr(service, "_read_record", read)
    cost, status = await service.calculated_cost_for_request(
        provider="cliproxy", model="brand-latest", usage=UsageTokens(1000, 100)
    )
    assert cost is not None
    assert cost.cost_usd == pytest.approx(0.003)
    assert cost.catalog_source == "local"
    read.assert_not_called()
    assert catalog.resolve_model("brand-latest").context_window == 200000
    assert catalog.resolve_model("brand-new", provider="openrouter", isolated_price=True).price is None
