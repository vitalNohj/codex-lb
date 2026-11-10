from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web

from app.core.usage import metadata_scheduler as scheduler_module
from app.core.usage import pricing_catalog as catalog
from app.core.usage.model_capabilities import ModelCapabilities, decode_model_capabilities
from app.core.usage.pricing import ModelPrice

pytestmark = pytest.mark.integration


@asynccontextmanager
async def sources(monkeypatch, *, primary_status=200, secondary_status=200, include_openai_prices=True):
    requests = []

    async def primary(request):
        requests.append(request.headers.get("User-Agent"))
        payload = json.loads((Path(__file__).parents[1] / "fixtures" / "claude_models_dev.json").read_text())
        if include_openai_prices:
            payload["openai"] = {
                "models": {
                    "gpt-test": {
                        "modalities": {"output": ["text"]},
                        "cost": {"input": 10, "output": 50, "cache_read": 1},
                    }
                }
            }
        return web.json_response(payload, status=primary_status)

    async def secondary(request):
        return web.json_response(
            {
                "gpt-test": {
                    "litellm_provider": "openai",
                    "mode": "chat",
                    "input_cost_per_token": 1e-5,
                    "output_cost_per_token": 5e-5,
                    "cache_read_input_token_cost": 1e-6,
                    "input_cost_per_token_flex": 5e-6,
                    "output_cost_per_token_flex": 2.5e-5,
                }
            },
            status=secondary_status,
        )

    app = web.Application()
    app.router.add_get("/models", primary)
    app.router.add_get("/litellm", secondary)
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = runner.addresses[0][1]
        monkeypatch.setattr(catalog, "MODELS_DEV_URL", f"http://127.0.0.1:{port}/models")
        monkeypatch.setattr(catalog, "LITELLM_URL", f"http://127.0.0.1:{port}/litellm")
        yield requests
    finally:
        await runner.cleanup()


@pytest.mark.parametrize("primary_status", [200, 503])
async def test_public_catalog_http_fetch_and_source_fallback(monkeypatch, primary_status):
    async with sources(monkeypatch, primary_status=primary_status) as requests:
        metadata = await catalog.fetch_catalogs()
    assert metadata.prices["gpt-test"].input_per_1m == 10
    assert metadata.prices["gpt-test"].flex_output_per_1m == 25
    assert metadata.capabilities == (
        {"claude-fable-5-2": ModelCapabilities(("text", "image", "pdf"), 1_000_000, 128_000)}
        if primary_status == 200
        else {}
    )
    assert requests == ["codex-lb"]


async def test_all_source_failures_leave_existing_prices_untouched(monkeypatch):
    monkeypatch.setattr(catalog, "_prices", None)
    capabilities = {"claude-fable-5-2": ModelCapabilities(("text", "image", "pdf"), 1_000_000, 128_000)}
    monkeypatch.setattr(catalog, "_capabilities", capabilities)
    before = catalog.get_active_prices()
    async with sources(monkeypatch, primary_status=403, secondary_status=503):
        with pytest.raises(ValueError, match="All pricing sources failed"):
            await catalog.fetch_catalogs()
    assert catalog.get_active_prices() == before
    assert catalog.get_active_model_capabilities() == capabilities


async def test_capability_only_refresh_persists_and_total_failure_keeps_last_good_cache(monkeypatch, tmp_path):
    prices = {"gpt-last-good": ModelPrice(3, 9)}
    capabilities = {"claude-fable-5-2": ModelCapabilities(("text", "image", "pdf"), 1_000_000, 128_000)}
    monkeypatch.setattr(catalog, "_prices", prices)
    monkeypatch.setattr(catalog, "_capabilities", {})
    monkeypatch.setattr(scheduler_module, "get_settings", lambda: SimpleNamespace(data_dir=tmp_path))
    monkeypatch.setattr(
        scheduler_module,
        "get_codex_version_cache",
        lambda: SimpleNamespace(get_version=AsyncMock(return_value="1.2.3")),
    )
    scheduler = scheduler_module.MetadataRefreshScheduler()
    async with sources(monkeypatch, include_openai_prices=False, secondary_status=503) as requests:
        await scheduler._refresh()
    assert requests == ["codex-lb"]
    assert catalog.get_active_prices() == prices
    assert catalog.get_active_model_capabilities() == capabilities
    path = tmp_path / "pricing-cache.json"
    persisted = path.read_text()
    assert catalog.decode_snapshot(json.loads(persisted)) == prices
    assert decode_model_capabilities(json.loads(persisted)) == capabilities

    async with sources(monkeypatch, primary_status=503, secondary_status=503):
        await scheduler._refresh()
    assert catalog.get_active_prices() == prices
    assert catalog.get_active_model_capabilities() == capabilities
    assert path.read_text() == persisted
