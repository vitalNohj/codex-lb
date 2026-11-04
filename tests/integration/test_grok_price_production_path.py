"""Grok 4.7 ids get a price on GET /v1/models along the path production takes.

PRs 189 and 190 tested the model list against a reference catalog injected as an
object that listed only OpenRouter's ``x-ai/grok-4.7``. Production also has
OrcaRouter enabled, whose catalog lists the same model as ``grok/grok-4.7``.
Here nothing is injected. CLIProxyAPI, OpenRouter and OrcaRouter are served over
loopback HTTP from recorded copies of their real responses, and the registered
pricing loaders, real fetchers and parsers read them. The stored rows are written
with the store calls production made before the fix.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from aiohttp import web
from anyio import to_thread
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.clients.orcarouter_sidecar import _parse_orcarouter_pricing
from app.core.usage.external_pricing import service as pricing_service
from app.core.usage.external_pricing.catalogs import fetch_openrouter_catalog
from app.core.usage.external_pricing.service import get_lookup_coordinator, reset_serving_context_loaders
from app.core.usage.external_pricing.store import ExternalModelPriceStore
from app.core.usage.pricing import ModelPrice
from app.core.utils.time import utcnow
from app.db.migrate import run_upgrade
from app.db.models import ExternalModelPrice, ExternalPriceStatus
from app.db.session import SessionLocal
from app.modules.proxy.external_pricing_sources import register_external_pricing_sources

pytestmark = pytest.mark.integration

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
# Real CLIProxyAPI v8.0.36 listings: plain ``/v1/models`` and the
# ``?client_version=`` form codex-lb reads published limits from.
_CLIPROXY_MODELS = (_FIXTURES / "cliproxy_v8_0_36_models.json").read_bytes()
_CLIPROXY_CLIENT_MODELS = (_FIXTURES / "cliproxy_v8_0_36_codex_client_models.json").read_bytes()
# Entries copied verbatim from https://openrouter.ai/api/v1/models and
# https://api.orcarouter.ai/v1/models on 2026-11-04.
_OPENROUTER_MODELS = (_FIXTURES / "openrouter_grok_models.json").read_bytes()
_ORCAROUTER_MODELS = (_FIXTURES / "orcarouter_grok_models.json").read_bytes()

_UNPRICED_IN_PRODUCTION = (
    "cc/grok-4.7-build-fast",
    "cc/lb5dc882f41e/grok-4.7",
    "cc/lb5dc882f41e/grok-4.7-build-fast",
)
_GROK_47_LISTED = {
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
    "unit": "usd_per_million_tokens",
}


@dataclass
class _Upstreams:
    base_url: str
    requests: list[str]


@pytest_asyncio.fixture
async def upstreams(monkeypatch) -> AsyncIterator[_Upstreams]:
    requests: list[str] = []
    bodies = {
        "/cliproxy/v1/models": _CLIPROXY_MODELS,
        "/openrouter/api/v1/models": _OPENROUTER_MODELS,
        "/orcarouter/v1/models": _ORCAROUTER_MODELS,
    }

    async def handle(request: web.Request) -> web.Response:
        requests.append(request.path_qs)
        if request.path == "/cliproxy/v1/models" and "client_version" in request.query:
            return web.Response(body=_CLIPROXY_CLIENT_MODELS, content_type="application/json")
        return web.Response(body=bodies[request.path], content_type="application/json")

    app = web.Application()
    for path in bodies:
        app.router.add_get(path, handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    base_url = f"http://127.0.0.1:{runner.addresses[0][1]}"

    async def openrouter_reference():
        # The production loader with only the URL moved to loopback: the real
        # fetch and parser run, and a failure is the production ``None``.
        try:
            return await fetch_openrouter_catalog(url=f"{base_url}/openrouter/api/v1/models")
        except Exception:
            return None

    monkeypatch.setattr(pricing_service, "_load_reference_catalog", openrouter_reference)
    reset_serving_context_loaders()
    register_external_pricing_sources()
    try:
        yield _Upstreams(base_url=base_url, requests=requests)
    finally:
        reset_serving_context_loaders()
        await runner.cleanup()


async def _configure_dallas_integrations(async_client, base_url: str) -> None:
    response = await async_client.put(
        "/api/settings",
        json={
            "claudeSidecarEnabled": True,
            "claudeSidecarBaseUrl": f"{base_url}/cliproxy",
            "claudeSidecarApiKey": "local-cliproxy-key",
            "claudeSidecarModelPrefixes": [{"prefix": "cc/", "strip": True}],
            "orcarouterSidecarEnabled": True,
            "orcarouterSidecarBaseUrl": f"{base_url}/orcarouter/v1",
            "orcarouterSidecarApiKey": "local-orcarouter-key",
            "orcarouterSidecarModelPrefixes": [{"prefix": "orca/", "strip": False}],
        },
    )
    assert response.status_code == 200, response.text


async def _seed_rows_as_production_wrote_them() -> None:
    """``cc/grok-4.7`` priced; the others settled unpriced and backed off by PR 190's retries."""

    async with SessionLocal() as session:
        await ExternalModelPriceStore(session).record_resolved(
            provider="cliproxy",
            incoming_model="cc/grok-4.7",
            catalog_model="x-ai/grok-4.7",
            catalog_source="openrouter:reference",
            price=ModelPrice(input_per_1m=2.0, output_per_1m=6.0, cached_input_per_1m=0.5),
            resolution_step="prefix+vendor-qualified",
        )
    for model in _UNPRICED_IN_PRODUCTION:
        async with SessionLocal() as session:
            await ExternalModelPriceStore(session).record_not_token_priced(
                provider="cliproxy",
                incoming_model=model,
                catalog_model=model,
                catalog_source="cliproxy",
                resolution_step="prefix+exact",
                detail="catalog lists the model without a per-token price",
            )
        # PR 190's re-lookups found no rate either and kept the answer with backoff.
        for _ in range(3):
            async with SessionLocal() as session:
                store = ExternalModelPriceStore(session)
                record = await store.get("cliproxy", model)
                assert record is not None
                await store.record_retryable_failure(
                    provider="cliproxy",
                    incoming_model=model,
                    record=record,
                    detail="stored price has no valid replacement",
                    previous_attempts=record.attempt_count,
                )


async def _make_seeded_rows_due() -> None:
    """Clear the seeded backoff, as the deploy's migration does, instead of sleeping it out."""

    async with SessionLocal() as session:
        await session.execute(
            update(ExternalModelPrice)
            .where(ExternalModelPrice.incoming_model.in_(_UNPRICED_IN_PRODUCTION))
            .values(attempt_count=0, next_retry_at=None)
        )
        await session.commit()


async def _list_models(async_client) -> dict[str, dict[str, object]]:
    response = await async_client.get("/v1/models")
    assert response.status_code == 200, response.text
    return {entry["id"]: entry for entry in response.json()["data"]}


@pytest.mark.asyncio
async def test_grok_47_ids_list_a_price_with_both_catalogs_enabled(async_client, upstreams):
    await _configure_dallas_integrations(async_client, upstreams.base_url)
    await _seed_rows_as_production_wrote_them()

    await _make_seeded_rows_due()

    # Every list schedules a lookup for each due unpriced row, four at a time.
    # The CLIProxyAPI listing holds ~80 other ids never priced before, so it
    # takes repeated lists to reach the Grok rows, as it does in production.
    # A row whose lookup failed backs off and stops taking a slot.
    listed: dict[str, dict[str, object]] = {}
    for _ in range(40):
        listed = await _list_models(async_client)
        await get_lookup_coordinator().drain()
        if all("pricing" in listed[model] for model in _UNPRICED_IN_PRODUCTION):
            break
    listed = await _list_models(async_client)

    assert any(path.startswith("/orcarouter/v1/models") for path in upstreams.requests)
    assert any(path.startswith("/openrouter/api/v1/models") for path in upstreams.requests)
    for model in _UNPRICED_IN_PRODUCTION:
        assert listed[model].get("pricing") == _GROK_47_LISTED, model
    async with SessionLocal() as session:
        store = ExternalModelPriceStore(session)
        for model in _UNPRICED_IN_PRODUCTION:
            record = await store.get("cliproxy", model)
            assert record is not None
            assert record.status is ExternalPriceStatus.RESOLVED, (model, record.detail)
            assert record.catalog_model == "x-ai/grok-4.7"


def test_orcarouter_grok_47_tier_matches_openrouter_published_price():
    """OrcaRouter's ``tiers`` carry the same 200K tier as OpenRouter's ``overrides``."""

    orcarouter = {entry["id"]: entry for entry in json.loads(_ORCAROUTER_MODELS)["data"]}
    price = _parse_orcarouter_pricing(orcarouter["grok/grok-4.7"]["pricing"])

    assert price == ModelPrice(
        input_per_1m=2.0,
        output_per_1m=6.0,
        cached_input_per_1m=0.5,
        long_context_threshold_tokens=200_000.0,
        long_context_input_per_1m=4.0,
        long_context_output_per_1m=12.0,
        long_context_cached_input_per_1m=1.0,
    )


def test_orcarouter_multi_tier_price_keeps_the_first_boundary():
    """A model with several input-size tiers keeps the first one, as ``overrides`` do."""

    orcarouter = {entry["id"]: entry for entry in json.loads(_ORCAROUTER_MODELS)["data"]}
    price = _parse_orcarouter_pricing(orcarouter["qwen/qwen3-max"]["pricing"])

    assert price is not None
    assert price.input_per_1m == pytest.approx(0.359)
    assert price.output_per_1m == pytest.approx(1.434)
    assert price.long_context_threshold_tokens == 32_000.0
    assert price.long_context_input_per_1m == pytest.approx(0.574)
    assert price.long_context_output_per_1m == pytest.approx(2.294)
    assert price.long_context_cached_input_per_1m is None


@pytest.mark.asyncio
async def test_upgrade_makes_backed_off_unpriced_rows_due_and_keeps_the_rest(tmp_path):
    """After deploy the next list re-looks-up the stuck rows instead of waiting out a 24h backoff."""

    db_url = f"sqlite+aiosqlite:///{tmp_path / 'store.db'}"
    await to_thread.run_sync(
        lambda: run_upgrade(db_url, "20261102_000000_external_price_write_context_rates", bootstrap_legacy=True)
    )
    later = utcnow() + timedelta(hours=24)
    rows = [
        # (incoming_model, status, input_per_1m, attempt_count, next_retry_at, lookup_token)
        ("cc/grok-4.7", "resolved", 2.0, 0, None, None),
        ("cc/grok-4.7-build-fast", "not_token_priced", None, 5, later, None),
        ("cc/lb5dc882f41e/grok-4.7", "ambiguous", None, 4, later, None),
        ("cc/lb5dc882f41e/grok-4.7-build-fast", "unresolved", None, 3, later, None),
        ("cc/leased", "pending", None, 0, later, "live-lease"),
        ("cc/stale-rate", "resolved", 1.0, 2, later, None),
    ]
    engine = create_async_engine(db_url)
    try:
        async with engine.begin() as connection:
            for model, status, rate, attempts, retry_at, token in rows:
                await connection.execute(
                    text(
                        "INSERT INTO external_model_prices (provider, incoming_model, raw_incoming_model, status, "
                        "input_per_1m, output_per_1m, attempt_count, next_retry_at, lookup_token) VALUES "
                        "('cliproxy', :model, :model, :status, :rate, :rate, :attempts, :retry_at, :token)"
                    ),
                    {
                        "model": model,
                        "status": status,
                        "rate": rate,
                        "attempts": attempts,
                        "retry_at": retry_at,
                        "token": token,
                    },
                )
    finally:
        await engine.dispose()

    await to_thread.run_sync(lambda: run_upgrade(db_url, "head", bootstrap_legacy=False))

    engine = create_async_engine(db_url)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text("SELECT incoming_model, status, attempt_count, next_retry_at FROM external_model_prices")
            )
            after = {row[0]: (row[1], row[2], row[3] is None) for row in result}
    finally:
        await engine.dispose()
    assert after == {
        "cc/grok-4.7": ("resolved", 0, True),
        "cc/grok-4.7-build-fast": ("not_token_priced", 0, True),
        "cc/lb5dc882f41e/grok-4.7": ("ambiguous", 0, True),
        "cc/lb5dc882f41e/grok-4.7-build-fast": ("unresolved", 0, True),
        "cc/leased": ("pending", 0, False),
        "cc/stale-rate": ("resolved", 2, False),
    }


@pytest.mark.parametrize(
    "tiers",
    [
        "not-a-list",
        [{"max_input_tokens": "200000", "prompt": "0.000002", "completion": "0.000006"}],
        [
            {"max_input_tokens": 0, "prompt": "0.000002", "completion": "0.000006"},
            {"max_input_tokens": 0, "prompt": "0.000004", "completion": "0.000012"},
        ],
        [
            {"max_input_tokens": 200000, "prompt": "0.000002", "completion": "0.000006"},
            {"max_input_tokens": 0, "prompt": "bad", "completion": "0.000012"},
        ],
    ],
)
def test_unreadable_orcarouter_tiers_leave_the_price_unread(tiers):
    pricing = {"prompt": "0.000002", "completion": "0.000006", "tiers": tiers}

    assert _parse_orcarouter_pricing(pricing) is None
