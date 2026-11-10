from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from aiohttp import web

from app.core.usage import pricing_catalog as catalog
from app.core.usage.model_capabilities import ModelCapabilities

pytestmark = pytest.mark.integration


@asynccontextmanager
async def sources(monkeypatch, *, primary_status=200, secondary_status=200):
    requests = []

    async def primary(request):
        requests.append(request.headers.get("User-Agent"))
        return web.json_response(
            {
                **json.loads((Path(__file__).parents[1] / "fixtures" / "claude_models_dev.json").read_text()),
                "openai": {
                    "models": {
                        "gpt-test": {
                            "modalities": {"output": ["text"]},
                            "cost": {"input": 10, "output": 50, "cache_read": 1},
                        }
                    }
                },
            },
            status=primary_status,
        )

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
