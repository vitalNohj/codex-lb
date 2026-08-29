"""The maintenance command must work as an operator runs it.

``codex-lb model-prices refresh`` runs outside the FastAPI lifespan, so nothing
else builds the shared HTTP client every catalog fetch leases. Without it the pass
either aborted on the pricing reference or reported every catalog unavailable and
changed nothing, which is indistinguishable from a healthy no-op run.
"""

from __future__ import annotations

import asyncio

import pytest
import sqlalchemy.exc as sa_exc

from app import cli
from app.core.clients import http as http_module
from app.core.usage.external_pricing import service as pricing_service
from app.core.usage.external_pricing.catalogs import Catalog, CatalogEntry
from app.core.usage.external_pricing.service import reset_serving_context_loaders
from app.core.usage.external_pricing.store import ExternalModelPriceStore
from app.core.usage.pricing import ModelPrice
from app.db.session import SessionLocal

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _clean_loaders():
    reset_serving_context_loaders()
    yield
    reset_serving_context_loaders()


async def _run_command() -> None:
    """Invoke the command the way an operator does: its own thread, own loop.

    ``cli.main`` owns its event loop via ``asyncio.run``, which is precisely the
    context that left the HTTP client uninitialized in production.
    """

    await asyncio.to_thread(cli.main, ["model-prices", "refresh"])


@pytest.fixture
def _offline_catalogs(monkeypatch):
    """Serve the pricing reference from a fake fetch that needs the HTTP client.

    The fake asserts the lease succeeds rather than skipping it, so the test fails
    for the same reason the real command did when the client was never built.
    """

    fetched: list[str] = []

    async def _fetch_openrouter_catalog(**_kwargs) -> Catalog:
        async with http_module.lease_http_session():
            fetched.append("openrouter")
        return Catalog.from_entries(
            "openrouter",
            [CatalogEntry(model_id="vendor/model-x", price=ModelPrice(input_per_1m=3.0, output_per_1m=6.0))],
        )

    import app.core.usage.external_pricing.maintenance as maintenance_module

    monkeypatch.setattr(maintenance_module, "fetch_openrouter_catalog", _fetch_openrouter_catalog)
    monkeypatch.setattr(pricing_service, "fetch_openrouter_catalog", _fetch_openrouter_catalog)
    return fetched


@pytest.mark.asyncio
async def test_refresh_updates_a_persisted_rate_and_reports_it(
    db_setup,
    capsys,
    _offline_catalogs,
) -> None:
    del db_setup
    async with SessionLocal() as session:
        await ExternalModelPriceStore(session).record_resolved(
            provider="orcarouter",
            incoming_model="vendor/model-x",
            catalog_model="vendor/model-x",
            catalog_source="openrouter",
            price=ModelPrice(input_per_1m=2.0, output_per_1m=4.0),
            resolution_step="exact",
        )

    await _run_command()

    output = capsys.readouterr().out
    assert "External model price maintenance" in output
    assert "Records examined: 1" in output
    assert _offline_catalogs == ["openrouter"], "the pass must reach the pricing reference"

    async with SessionLocal() as session:
        record = await ExternalModelPriceStore(session).get("orcarouter", "vendor/model-x")
    assert record is not None and record.price is not None
    assert record.price.input_per_1m == pytest.approx(3.0)
    assert record.price.output_per_1m == pytest.approx(6.0)


@pytest.mark.asyncio
async def test_refresh_reports_a_missing_table_as_a_diagnosable_error(
    db_setup,
    monkeypatch,
    _offline_catalogs,
) -> None:
    """An unmigrated database must name the fix, not surface a raw SQL error."""

    del db_setup
    del _offline_catalogs

    async def _list_all(_self):
        raise sa_exc.OperationalError("SELECT 1", {}, Exception("no such table: external_model_prices"))

    monkeypatch.setattr(ExternalModelPriceStore, "list_all", _list_all)

    with pytest.raises(SystemExit) as exc_info:
        await _run_command()

    assert "codex-lb-db upgrade" in str(exc_info.value)
