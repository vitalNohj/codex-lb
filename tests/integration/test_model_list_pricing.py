"""Discovery prices reconstruct settlement, including cache writes and tiers."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest

from app.core.clients.claude_sidecar import ClaudeSidecarClient, SidecarModel
from app.core.clients.openrouter_sidecar import OpenRouterSidecarClient
from app.core.usage.external_pricing import calculated_cost_for_request
from app.core.usage.external_pricing import service as pricing_service
from app.core.usage.external_pricing.catalogs import Catalog, CatalogEntry
from app.core.usage.external_pricing.service import (
    ServingContext,
    get_lookup_coordinator,
    known_price_snapshot,
    register_serving_context_loader,
    reset_serving_context_loaders,
)
from app.core.usage.external_pricing.store import ExternalModelPriceStore
from app.core.usage.pricing import ModelPrice, UsageTokens, calculate_cost_from_usage, get_pricing_for_model
from app.core.utils.time import utcnow
from app.db.models import ExternalPriceStatus, ModelSource, ModelSourceModel
from app.db.session import SessionLocal
from app.modules.model_sources.catalog import source_model_cost_usd
from app.modules.model_sources.repository import ModelSourcesRepository
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
        cache_write_input_per_1m=0.1375,
        cache_write_input_1h_per_1m=0.22,
        long_context_threshold_tokens=100_000,
        long_context_input_per_1m=0.51,
        long_context_output_per_1m=2.51,
        long_context_cached_input_per_1m=0.051,
        long_context_cache_write_input_per_1m=0.6375,
        long_context_cache_write_input_1h_per_1m=1.02,
    ),
    ("openrouter", _PAID): ModelPrice(input_per_1m=0.6, output_per_1m=2.2, cache_write_input_per_1m=0.75),
    ("openrouter", _SAME): ModelPrice(input_per_1m=0.6, output_per_1m=2.2, cache_write_input_per_1m=0.75),
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


# Every Grok 4.7 id GET /v1/models serves: the bare id behind the cc/ strip
# prefix, the xAI subscription account alias, and Grok 4.7 Fast in both forms.
_GROK_VARIANTS = (
    "cc/grok-4.7",
    "cc/lb5dc882f41e/grok-4.7",
    "cc/grok-4.7-build-fast",
    "cc/lb5dc882f41e/grok-4.7-build-fast",
)
# OpenRouter's published grok-4.7 rates, including the above-200K tier. No
# catalog lists a grok-4.7-build-fast row.
_GROK_PRICE = ModelPrice(
    input_per_1m=2.0,
    output_per_1m=6.0,
    cached_input_per_1m=0.5,
    long_context_threshold_tokens=200_000,
    long_context_input_per_1m=4.0,
    long_context_output_per_1m=12.0,
    long_context_cached_input_per_1m=1.0,
)


@pytest.mark.asyncio
async def test_grok_build_fast_lists_the_grok_47_price(async_client, monkeypatch):
    """Every served Grok 4.7 id takes the one published price.

    OpenRouter prices ``x-ai/grok-4.7`` and lists no Fast id, and CLIProxyAPI
    publishes no rates. The subscription ids differ by a routing prefix and an
    account alias; build-fast is the same model. A sibling ``-build-fast`` id
    does not inherit the price.
    """

    reset_serving_context_loaders()

    async def reference():
        return Catalog.from_entries(
            "openrouter:reference",
            [CatalogEntry(model_id="x-ai/grok-4.7", price=_GROK_PRICE)],
        )

    async def cliproxy(_provider: str) -> ServingContext:
        return ServingContext(catalog=None, aliases={}, prefixes=(("cc/", True),), publishes_price_catalog=False)

    monkeypatch.setattr(pricing_service, "_load_reference_catalog", reference)
    register_serving_context_loader("cliproxy", cliproxy)
    monkeypatch.setattr(
        ClaudeSidecarClient,
        "list_models_cached",
        AsyncMock(
            return_value=[
                SidecarModel(id="grok-4.7", owned_by="xai"),
                SidecarModel(id="lb5dc882f41e/grok-4.7", owned_by="xai"),
                SidecarModel(id="grok-4.7-build-fast", owned_by="xai"),
                SidecarModel(id="lb5dc882f41e/grok-4.7-build-fast", owned_by="xai"),
                SidecarModel(id="other-build-fast"),
            ]
        ),
    )
    settings = await async_client.put(
        "/api/settings",
        json={
            "claudeSidecarEnabled": True,
            "claudeSidecarBaseUrl": "http://127.0.0.1:9",
            "claudeSidecarApiKey": "synthetic-key",
            "claudeSidecarModelPrefixes": [{"prefix": "cc/", "strip": True}],
        },
    )
    assert settings.status_code == 200, settings.text

    for model in (*_GROK_VARIANTS, "cc/other-build-fast"):
        await calculated_cost_for_request(
            provider="cliproxy", model=model, usage=UsageTokens(1, 1), schedule_lookup=True
        )
    await get_lookup_coordinator().drain()

    response = await async_client.get("/v1/models")
    assert response.status_code == 200, response.text
    by_id = {entry["id"]: entry for entry in response.json()["data"]}
    expected = {
        "input": 2.0,
        "output": 6.0,
        "cache_read": 0.5,
        "cache_write": 4.0,
        "long_context": {
            "threshold_tokens": 200_000,
            "input": 4.0,
            "output": 12.0,
            "cache_read": 1.0,
            "cache_write": 8.0,
        },
    }
    for model in _GROK_VARIANTS:
        listed = by_id[model]["pricing"]
        assert listed["unit"] == "usd_per_million_tokens"
        for key, value in expected.items():
            assert listed[key] == value, model
    assert "pricing" not in by_id["cc/other-build-fast"]
    reset_serving_context_loaders()


@pytest.mark.asyncio
async def test_settled_grok_variants_list_the_grok_47_price(async_client, monkeypatch):
    """A Grok 4.7 id already stored as unpriced is priced again after the alias exists.

    GET /v1/models reads the persisted row and never starts a lookup. Before the
    Fast id was aliased to grok-4.7, each served variant was settled with no
    token rate, and a settled row is not claimed again. The model list therefore
    keeps omitting the price after the code that would resolve it is deployed.
    """

    reset_serving_context_loaders()

    async def reference():
        return Catalog.from_entries(
            "openrouter:reference",
            [CatalogEntry(model_id="x-ai/grok-4.7", price=_GROK_PRICE)],
        )

    async def cliproxy(_provider: str) -> ServingContext:
        return ServingContext(catalog=None, aliases={}, prefixes=(("cc/", True),), publishes_price_catalog=False)

    monkeypatch.setattr(pricing_service, "_load_reference_catalog", reference)
    register_serving_context_loader("cliproxy", cliproxy)
    monkeypatch.setattr(
        ClaudeSidecarClient,
        "list_models_cached",
        AsyncMock(
            return_value=[
                SidecarModel(id="grok-4.7", owned_by="xai"),
                SidecarModel(id="lb5dc882f41e/grok-4.7", owned_by="xai"),
                SidecarModel(id="grok-4.7-build-fast", owned_by="xai"),
                SidecarModel(id="lb5dc882f41e/grok-4.7-build-fast", owned_by="xai"),
            ]
        ),
    )
    settings = await async_client.put(
        "/api/settings",
        json={
            "claudeSidecarEnabled": True,
            "claudeSidecarBaseUrl": "http://127.0.0.1:9",
            "claudeSidecarApiKey": "synthetic-key",
            "claudeSidecarModelPrefixes": [{"prefix": "cc/", "strip": True}],
        },
    )
    assert settings.status_code == 200, settings.text

    async with SessionLocal() as session:
        store = ExternalModelPriceStore(session)
        for model in _GROK_VARIANTS:
            await store.record_not_token_priced(
                provider="cliproxy",
                incoming_model=model,
                catalog_model=model,
                catalog_source="cliproxy",
                resolution_step="prefix+exact",
                detail="catalog lists the model without a per-token price",
            )

    # The list schedules the lookup and answers from the rows that exist now.
    # Draining is what the next list, or the next request, waits for.
    first = await async_client.get("/v1/models")
    assert first.status_code == 200, first.text
    await get_lookup_coordinator().drain()

    response = await async_client.get("/v1/models")
    assert response.status_code == 200, response.text
    by_id = {entry["id"]: entry for entry in response.json()["data"]}
    for model in _GROK_VARIANTS:
        assert "pricing" in by_id[model], model
        assert by_id[model]["pricing"]["input"] == 2.0
        assert by_id[model]["pricing"]["output"] == 6.0
        record_status = by_id[model]["pricing"]["unit"]
        assert record_status == "usd_per_million_tokens"
    async with SessionLocal() as session:
        store = ExternalModelPriceStore(session)
        for model in _GROK_VARIANTS:
            record = await store.get("cliproxy", model)
            assert record is not None and record.status is ExternalPriceStatus.RESOLVED, model
            assert record.price is not None
            assert record.price.input_per_1m == 2.0
    reset_serving_context_loaders()


@pytest.mark.asyncio
async def test_a_listing_skips_unpriced_rows_that_are_not_due_yet(db_setup) -> None:
    """Rows still inside backoff must not take the four lookup slots.

    A stable listing otherwise submits the same first four, the coordinator
    drops everything after them, and an id that can now be priced never runs.
    """

    del db_setup
    async with SessionLocal() as session:
        store = ExternalModelPriceStore(session)
        for index in range(4):
            await store.record_unresolved(
                provider="cliproxy",
                incoming_model=f"backed-off-{index}",
                status=ExternalPriceStatus.UNRESOLVED,
                detail="no catalog entry",
                previous_attempts=1,
            )
        await store.record_not_token_priced(
            provider="cliproxy",
            incoming_model="cc/grok-4.7-build-fast",
            catalog_model="cc/grok-4.7-build-fast",
            catalog_source="cliproxy",
            resolution_step="prefix+exact",
            detail="catalog lists the model without a per-token price",
        )
    submitted: list[str] = []
    original = pricing_service._coordinator.submit

    async def record_submit(key, factory):
        submitted.append(key[1])
        await original(key, factory)

    pricing_service._coordinator.submit = record_submit
    try:
        snapshot = await known_price_snapshot(
            [("cliproxy", f"backed-off-{index}") for index in range(4)] + [("cliproxy", "cc/grok-4.7-build-fast")],
            schedule_unpriced=True,
        )
        await get_lookup_coordinator().drain()
    finally:
        pricing_service._coordinator.submit = original

    assert snapshot is not None
    assert submitted == ["cc/grok-4.7-build-fast"]
    async with SessionLocal() as session:
        store = ExternalModelPriceStore(session)
        for index in range(4):
            record = await store.get("cliproxy", f"backed-off-{index}")
            assert record is not None and record.next_retry_at is not None
            assert record.next_retry_at > utcnow() + timedelta(minutes=4)


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
@pytest.mark.parametrize("path", ["/v1/models", "/backend-api/codex/models", "/v1/models?client_version=0.114.0"])
async def test_source_prices_match_capability_filtered_request_selection(async_client, path):
    model = "source/shared-name"
    sources = []
    for name, responses, streaming, rate in (
        ("a-chat-only", False, True, 1.0),
        ("b-non-streaming", True, False, 3.0),
        ("c-responses-streaming", True, True, 7.0),
    ):
        source = ModelSource(
            id=name,
            name=name,
            kind="openai_compatible",
            base_url="http://127.0.0.1:9/v1",
            is_enabled=True,
            supports_chat_completions=True,
            supports_responses=responses,
        )
        source.models = [
            ModelSourceModel(
                model=model,
                is_enabled=True,
                supports_streaming=streaming,
                input_per_1m=rate,
                output_per_1m=rate * 2,
                cached_input_per_1m=rate / 10,
            )
        ]
        sources.append(source)
    codex = path != "/v1/models"
    async with SessionLocal() as session:
        session.add_all(sources)
        await session.commit()
        repository = ModelSourcesRepository(session)
        selected = (
            await repository.find_responses_source_for_model(model, require_streaming=True)
            if codex
            else await repository.find_chat_source_for_model(model)
        )
        assert selected is not None
        assert selected.id == ("c-responses-streaming" if codex else "a-chat-only")
        charged = source_model_cost_usd(selected, model, input_tokens=1000, output_tokens=97, cached_input_tokens=211)
    response = await async_client.get(path)
    assert response.status_code == 200, response.text
    body = response.json()
    entries = body["data"] + [{**entry, "id": entry["slug"]} for entry in body.get("models", [])]
    matches = [entry for entry in entries if entry["id"] == model]
    assert len(matches) == (2 if codex else 1)
    for entry in matches:
        assert _listed_cost(entry["pricing"], UsageTokens(1000, 97, 211), None) == pytest.approx(charged)


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
