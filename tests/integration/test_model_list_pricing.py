"""Discovery prices reconstruct settlement, including cache writes and tiers."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.core.clients.claude_sidecar import ClaudeSidecarClient
from app.core.clients.openrouter_sidecar import OpenRouterSidecarClient
from app.core.usage.external_pricing import calculated_cost_for_request
from app.core.usage.external_pricing.store import ExternalModelPriceStore
from app.core.usage.pricing import ModelPrice, UsageTokens, calculate_cost_from_usage, get_pricing_for_model
from app.db.models import ModelSource, ModelSourceModel
from app.db.session import SessionLocal
from app.modules.model_sources.catalog import source_model_cost_usd
from app.modules.proxy.model_aliasing import resolve_model_alias_pool
from app.modules.settings.model_alias_pools import ModelAliasPool

pytestmark = pytest.mark.integration

_CLAUDE = "cc/claude-haiku-5-5"
_PAID = "z-ai/glm-4.6"
_SAME = "z-ai/glm-test-same-rate"
_FREE = "z-ai/glm-4.5-air:free"
_UNKNOWN = "z-ai/not-priced-yet"
_ALIASES = {
    "team/claude": ModelAliasPool((_CLAUDE,)),
    "team/equal": ModelAliasPool((_PAID, _SAME)),
    "team/different": ModelAliasPool((_PAID, _FREE)),
}
_EXTERNAL = {
    ("cliproxy", _CLAUDE): ModelPrice(
        input_per_1m=0.11,
        output_per_1m=0.55,
        cached_input_per_1m=0.012,
        long_context_threshold_tokens=100_000,
        long_context_input_per_1m=0.51,
        long_context_output_per_1m=2.51,
        long_context_cached_input_per_1m=0.051,
    ),
    ("openrouter", _PAID): ModelPrice(input_per_1m=0.6, output_per_1m=2.2),
    ("openrouter", _SAME): ModelPrice(input_per_1m=0.6, output_per_1m=2.2),
    ("openrouter", _FREE): ModelPrice(input_per_1m=0.0, output_per_1m=0.0),
}


def _listed_cost(pricing, usage: UsageTokens, service_tier: str | None) -> float:
    rates = pricing[service_tier] if service_tier in pricing else pricing
    long = rates.get("long_context")
    if long and usage.input_tokens > long["threshold_tokens"]:
        rates = long
    return (
        max(0, usage.input_tokens - usage.cached_input_tokens - usage.cache_write_input_tokens)
        / 1_000_000
        * rates["input"]
        + usage.cached_input_tokens / 1_000_000 * rates["cache_read"]
        + usage.output_tokens / 1_000_000 * rates["output"]
        + usage.cache_write_input_tokens / 1_000_000 * rates["cache_write"]
    )


@pytest.fixture
async def pricing_catalog(async_client, monkeypatch):
    # Synthetic integrations only; never contact a sidecar or pricing catalog.
    monkeypatch.setattr(ClaudeSidecarClient, "list_models_cached", AsyncMock(return_value=[]))
    monkeypatch.setattr(OpenRouterSidecarClient, "list_models_cached", AsyncMock(return_value=[]))
    settings = await async_client.put(
        "/api/settings",
        json={
            "claudeSidecarEnabled": True,
            "claudeSidecarBaseUrl": "http://127.0.0.1:9",
            "claudeSidecarApiKey": "synthetic-key",
            "claudeSidecarModelPrefixes": [{"prefix": "cc/", "strip": True}],
            "claudeSidecarFullModels": [_CLAUDE],
            "openrouterSidecarEnabled": True,
            "openrouterSidecarApiKey": "synthetic-key",
            "openrouterSidecarModelPrefixes": ["z-ai/"],
            "openrouterSidecarFullModels": [_PAID, _SAME, _FREE, _UNKNOWN],
            "modelAliases": {alias: {"targets": list(pool.targets)} for alias, pool in _ALIASES.items()},
        },
    )
    assert settings.status_code == 200, settings.text
    async with SessionLocal() as session:
        for (provider, model), price in _EXTERNAL.items():
            await ExternalModelPriceStore(session).record_resolved(
                provider=provider,
                incoming_model=model,
                catalog_model=model,
                catalog_source=provider,
                price=price,
                resolution_step="exact",
            )
    return async_client


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/v1/models", "/backend-api/codex/models", "/v1/models?client_version=0.114.0"])
async def test_every_listed_price_reconstructs_request_settlement(pricing_catalog, path, monkeypatch):
    batch_reads = 0
    get_many = ExternalModelPriceStore.get_many

    async def counted(self, keys):
        nonlocal batch_reads
        batch_reads += 1
        return await get_many(self, keys)

    monkeypatch.setattr(ExternalModelPriceStore, "get_many", counted)
    response = await pricing_catalog.get(path)
    assert response.status_code == 200, response.text
    body = response.json()
    # Both Codex arrays share ONE snapshot, not a query per array or model.
    assert batch_reads == 1
    entries = body["data"] + [{**entry, "id": entry["slug"]} for entry in body.get("models", [])]
    by_id = {entry["id"]: entry for entry in entries}
    assert "gpt-5.4" in by_id
    assert "long_context" in by_id["gpt-5.4"]["pricing"]
    if path == "/v1/models":
        assert {_CLAUDE, _PAID, _FREE, _UNKNOWN, *_ALIASES} <= by_id.keys()
        assert "pricing" not in by_id[_UNKNOWN]
        assert "pricing" not in by_id["team/different"]
        assert by_id["team/equal"]["pricing"] == by_id[_PAID]["pricing"]
        assert by_id[_FREE]["pricing"] == {
            "unit": "usd_per_million_tokens",
            "input": 0,
            "output": 0,
            "cache_read": 0,
            "cache_write": 0,
        }
        assert by_id[_CLAUDE]["pricing"]["input"] == 0.11  # external store, NOT the built-in 0.10

    for entry in entries:
        model = entry["id"]
        resolved = resolve_model_alias_pool(model, _ALIASES)
        assert resolved is not None
        targets = resolved.targets
        if model == "team/different":
            continue  # No one price can describe this heterogeneous failover pool.
        standard = entry.get("pricing")
        for target in targets:
            if target == _UNKNOWN:
                cost, _ = await calculated_cost_for_request(
                    provider="openrouter", model=target, usage=UsageTokens(1000, 97, 211, 83), schedule_lookup=False
                )
                assert cost is None
                assert "pricing" not in entry
                continue
            external = next((provider for provider, name in _EXTERNAL if name == target), None)
            if external is None:
                static = get_pricing_for_model(target)
                if static is None:
                    assert "pricing" not in entry
                    continue
            assert standard is not None, model
            assert standard["unit"] == "usd_per_million_tokens"
            for tier in (None, "priority", "flex"):
                rates = standard.get(tier, standard)
                threshold = rates.get("long_context", {}).get("threshold_tokens")
                prompts = (1000,) if threshold is None else (1000, threshold, threshold + 1)
                for input_tokens in prompts:
                    usage = UsageTokens(input_tokens, 97, cached_input_tokens=211, cache_write_input_tokens=83)
                    if external is not None:
                        cost, _ = await calculated_cost_for_request(
                            provider=external, model=target, usage=usage, service_tier=tier, schedule_lookup=False
                        )
                        assert cost is not None
                        charged = cost.cost_usd
                    else:
                        assert static is not None
                        charged = calculate_cost_from_usage(usage, static[1], service_tier=tier)
                    assert _listed_cost(standard, usage, tier) == pytest.approx(charged, abs=1e-14), (model, tier)


@pytest.mark.asyncio
async def test_unreadable_external_store_omits_rates_without_claiming_zero(pricing_catalog, monkeypatch):
    async def unreadable(self, keys):
        raise RuntimeError("synthetic store failure")

    monkeypatch.setattr(ExternalModelPriceStore, "get_many", unreadable)
    response = await pricing_catalog.get("/v1/models")
    assert response.status_code == 200, response.text
    by_id = {entry["id"]: entry for entry in response.json()["data"]}
    assert all("pricing" not in by_id[model] for model in (_CLAUDE, _PAID, _FREE, _UNKNOWN, *_ALIASES))
    assert "pricing" in by_id["gpt-5.4"]


@pytest.mark.asyncio
async def test_model_source_rates_are_the_same_rates_used_to_settle_requests(async_client):
    source = ModelSource(
        id="pricing-source",
        name="local rates",
        kind="openai_compatible",
        base_url="http://127.0.0.1:9/v1",
        is_enabled=True,
        supports_responses=True,
    )
    source.models = [
        ModelSourceModel(
            model="source/paid",
            is_enabled=True,
            input_per_1m=7.0,
            output_per_1m=13.0,
            cached_input_per_1m=0.4,
        ),
        ModelSourceModel(model="source/free", is_enabled=True, input_per_1m=0.0, output_per_1m=0.0),
        ModelSourceModel(model="source/unknown", is_enabled=True),
    ]
    expected = {
        model: source_model_cost_usd(source, model, input_tokens=1000, output_tokens=97, cached_input_tokens=211)
        for model in ("source/paid", "source/free", "source/unknown")
    }
    async with SessionLocal() as session:
        session.add(source)
        await session.commit()
    response = await async_client.get("/v1/models")
    assert response.status_code == 200, response.text
    by_id = {entry["id"]: entry for entry in response.json()["data"]}
    for model, charged in expected.items():
        if charged is None:
            assert "pricing" not in by_id[model]
        else:
            pricing = by_id[model]["pricing"]
            assert pricing["cache_write"] == 0
            assert _listed_cost(pricing, UsageTokens(1000, 97, 211), None) == pytest.approx(charged)
