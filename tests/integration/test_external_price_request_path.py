"""End-to-end coverage of external pricing through ``POST /v1/chat/completions``.

These go through the same path a client uses, because the defect this work
replaces was only visible there: the request log showed a confident dollar figure
that looked billed but was produced by substring-matching the model name against a
hand-maintained table.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.core.clients.claude_sidecar import SidecarPrefix
from app.core.clients.orcarouter_sidecar import OrcaRouterSidecarConfig
from app.core.config.settings import get_settings
from app.core.usage.external_pricing import service as pricing_service
from app.core.usage.external_pricing.catalogs import Catalog, CatalogEntry
from app.core.usage.external_pricing.service import (
    ServingContext,
    get_lookup_coordinator,
    register_serving_context_loader,
    reset_serving_context_loaders,
)
from app.core.usage.pricing import ModelPrice
from app.db.models import CostSource, ExternalPriceStatus, RequestLog
from app.db.session import SessionLocal
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeyCreateData, ApiKeysService

pytestmark = pytest.mark.integration

_MODEL = "orcarouter/auto"
# The fake upstream reports 10 prompt / 5 completion tokens on every request.
_INPUT_TOKENS = 10
_OUTPUT_TOKENS = 5


class _FakeOrcaRouterClient:
    def __init__(self, config: OrcaRouterSidecarConfig) -> None:
        self.config = config
        self.billed_cost_usd: float | None = None

    async def list_models_cached(self):
        return []

    async def chat_completion(self, payload):
        usage = {
            "prompt_tokens": _INPUT_TOKENS,
            "completion_tokens": _OUTPUT_TOKENS,
            "total_tokens": _INPUT_TOKENS + _OUTPUT_TOKENS,
        }
        if self.billed_cost_usd is not None:
            usage["cost_usd"] = self.billed_cost_usd
        return {
            "id": "chatcmpl-orcarouter",
            "object": "chat.completion",
            "model": payload["model"],
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
            "usage": usage,
        }

    def stream_chat_completion(self, payload):
        raise AssertionError("these tests do not stream")


@pytest.fixture(autouse=True)
def _clean_pricing_state(monkeypatch):
    reset_serving_context_loaders()

    async def _no_reference():
        return None

    monkeypatch.setattr(pricing_service, "_load_reference_catalog", _no_reference)
    yield
    reset_serving_context_loaders()


@pytest.fixture
async def orcarouter_enabled(monkeypatch):
    monkeypatch.setenv("CODEX_LB_ORCAROUTER_SIDECAR_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def fake_orcarouter(monkeypatch) -> _FakeOrcaRouterClient:
    config = OrcaRouterSidecarConfig(
        enabled=True,
        base_url="https://api.orcarouter.ai/v1",
        api_key="orcarouter-key",
        prefixes=(SidecarPrefix(prefix="orcarouter/", strip=False),),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
        full_models=(_MODEL,),
    )
    client = _FakeOrcaRouterClient(config)

    async def load_config():
        return config

    monkeypatch.setattr("app.modules.proxy.api.load_orcarouter_sidecar_config", load_config)
    monkeypatch.setattr("app.modules.proxy.api.OrcaRouterSidecarClient", lambda _config: client)
    return client


def _install_catalog(entries: dict[str, ModelPrice | None]) -> None:
    async def _loader(_provider: str) -> ServingContext | None:
        return ServingContext(
            catalog=Catalog.from_entries(
                "orcarouter",
                [CatalogEntry(model_id=model_id, price=price) for model_id, price in entries.items()],
            ),
            aliases={},
            prefixes=(("orcarouter/", False),),
        )

    register_serving_context_loader("orcarouter", _loader)


async def _enable_sidecar(async_client) -> None:
    response = await async_client.put(
        "/api/settings",
        json={
            "orcarouterSidecarEnabled": True,
            "orcarouterSidecarApiKey": "orcarouter-key",
            "orcarouterSidecarModelPrefixes": ["orcarouter/"],
            "orcarouterSidecarFullModels": [_MODEL],
            "apiKeyAuthEnabled": True,
        },
    )
    assert response.status_code == 200


async def _create_api_key(name: str):
    async with SessionLocal() as session:
        service = ApiKeysService(ApiKeysRepository(session))
        return await service.create_key(ApiKeyCreateData(name=name, allowed_models=None, limits=[]))


async def _post_chat(async_client, key) -> None:
    response = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}"},
        json={"model": _MODEL, "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 200


async def _sidecar_logs() -> list[RequestLog]:
    async with SessionLocal() as session:
        logs = list((await session.execute(select(RequestLog))).scalars().all())
    return [log for log in logs if log.source == "orcarouter_sidecar"]


@pytest.mark.asyncio
async def test_the_first_request_records_no_cost_and_the_second_records_the_list_price(
    async_client,
    orcarouter_enabled,
    fake_orcarouter,
) -> None:
    """The lookup happens off the request path, so pricing starts on request two.

    Request one reports what is known (nothing) and schedules one lookup. It is
    marked unresolved rather than silently blank, because this model is eligible
    for a price and does not have one yet.
    """

    fake_orcarouter.billed_cost_usd = None
    _install_catalog({_MODEL: ModelPrice(input_per_1m=2.0, output_per_1m=4.0)})
    await _enable_sidecar(async_client)
    key = await _create_api_key("calculated-cost-key")

    await _post_chat(async_client, key)
    await get_lookup_coordinator().drain()

    first = (await _sidecar_logs())[0]
    assert first.cost_usd is None
    assert first.cost_source is None
    assert first.price_status == ExternalPriceStatus.UNRESOLVED.value

    await _post_chat(async_client, key)
    await get_lookup_coordinator().drain()

    second = sorted(await _sidecar_logs(), key=lambda log: log.id)[-1]
    # 10 input tokens at $2/M + 5 output tokens at $4/M.
    assert second.cost_usd == pytest.approx(10 * 2.0 / 1e6 + 5 * 4.0 / 1e6)
    assert second.cost_source == CostSource.CATALOG_CALCULATED.value
    assert second.price_status == ExternalPriceStatus.RESOLVED.value


@pytest.mark.asyncio
async def test_an_upstream_billed_amount_is_stored_verbatim_and_marked_as_billed(
    async_client,
    orcarouter_enabled,
    fake_orcarouter,
) -> None:
    """A calculated list price never overwrites the authoritative debit."""

    fake_orcarouter.billed_cost_usd = 0.00846
    _install_catalog({_MODEL: ModelPrice(input_per_1m=2.0, output_per_1m=4.0)})
    await _enable_sidecar(async_client)
    key = await _create_api_key("billed-cost-key")

    await _post_chat(async_client, key)
    await get_lookup_coordinator().drain()
    await _post_chat(async_client, key)
    await get_lookup_coordinator().drain()

    for log in await _sidecar_logs():
        assert log.cost_usd == pytest.approx(0.00846)
        assert log.cost_source == CostSource.UPSTREAM_BILLED.value


@pytest.mark.asyncio
async def test_an_unresolvable_model_records_no_cost_instead_of_a_glob_derived_one(
    async_client,
    orcarouter_enabled,
    fake_orcarouter,
) -> None:
    """Regression guard for the substring-glob pricing this replaces.

    ``orcarouter/gpt-4o-lookalike`` is in no catalog. The old table matched it with
    ``*gpt-4o*`` and recorded GPT-4o's rate, which is a wrong number rather than a
    missing one. It must now record none, and be marked so the UI can say why.
    """

    fake_orcarouter.billed_cost_usd = None
    unlisted = "orcarouter/gpt-4o-lookalike"
    _install_catalog({_MODEL: ModelPrice(input_per_1m=2.0, output_per_1m=4.0)})
    await _enable_sidecar(async_client)
    await async_client.put("/api/settings", json={"orcarouterSidecarFullModels": [_MODEL, unlisted]})
    key = await _create_api_key("glob-regression-key")

    for _ in range(2):
        response = await async_client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {key.key}"},
            json={"model": unlisted, "messages": [{"role": "user", "content": "hi"}]},
        )
        assert response.status_code == 200
        await get_lookup_coordinator().drain()

    logs = [log for log in await _sidecar_logs() if log.model == unlisted]
    assert logs, "the request must still be served and logged"
    for log in logs:
        assert log.cost_usd is None, "an unresolved model must not borrow another model's rate"
        assert log.price_status == ExternalPriceStatus.UNRESOLVED.value


@pytest.mark.asyncio
async def test_an_unresolved_model_is_still_served_and_still_counted(
    async_client,
    orcarouter_enabled,
    fake_orcarouter,
) -> None:
    """Not knowing a price must not change allow or quota behavior."""

    fake_orcarouter.billed_cost_usd = None
    _install_catalog({"vendor/something-else": ModelPrice(input_per_1m=1.0, output_per_1m=1.0)})
    await _enable_sidecar(async_client)
    key = await _create_api_key("unresolved-serving-key")

    await _post_chat(async_client, key)
    await get_lookup_coordinator().drain()

    log = (await _sidecar_logs())[0]
    assert log.status == "success"
    assert log.input_tokens == _INPUT_TOKENS
    assert log.output_tokens == _OUTPUT_TOKENS
    assert log.cost_usd is None


@pytest.mark.asyncio
async def test_a_free_model_records_a_real_zero_rather_than_no_price(
    async_client,
    orcarouter_enabled,
    fake_orcarouter,
) -> None:
    """Zero is a published price. It must read as $0.00, not as unresolved."""

    fake_orcarouter.billed_cost_usd = None
    _install_catalog({_MODEL: ModelPrice(input_per_1m=0.0, output_per_1m=0.0)})
    await _enable_sidecar(async_client)
    key = await _create_api_key("free-model-key")

    await _post_chat(async_client, key)
    await get_lookup_coordinator().drain()
    await _post_chat(async_client, key)
    await get_lookup_coordinator().drain()

    log = sorted(await _sidecar_logs(), key=lambda entry: entry.id)[-1]
    assert log.cost_usd == pytest.approx(0.0)
    assert log.cost_source == CostSource.CATALOG_CALCULATED.value
    assert log.price_status == ExternalPriceStatus.RESOLVED.value


@pytest.mark.asyncio
async def test_a_resolver_failure_records_no_cost_rather_than_a_static_table_one(
    async_client,
    orcarouter_enabled,
    fake_orcarouter,
    monkeypatch,
) -> None:
    """A pricing failure must not fall through to the substring-glob table.

    Falling through would resurrect exactly the mispricing this resolver replaces,
    and would do it invisibly, since the resulting number looks like any other.
    """

    fake_orcarouter.billed_cost_usd = None

    async def _explode(**_kwargs):
        raise RuntimeError("resolver is down")

    monkeypatch.setattr(
        "app.modules.proxy.external_pricing_logging.calculated_cost_for_request",
        _explode,
    )
    await _enable_sidecar(async_client)
    key = await _create_api_key("resolver-failure-key")

    await _post_chat(async_client, key)

    log = (await _sidecar_logs())[0]
    assert log.status == "success", "a pricing failure must not fail the request"
    assert log.cost_usd is None
    assert log.cost_source is None
    assert log.price_status == ExternalPriceStatus.UNRESOLVED.value


@pytest.mark.asyncio
async def test_the_request_log_api_exposes_cost_provenance(
    async_client,
    orcarouter_enabled,
    fake_orcarouter,
) -> None:
    """The distinction must reach the UI, not stop at the database."""

    fake_orcarouter.billed_cost_usd = None
    _install_catalog({_MODEL: ModelPrice(input_per_1m=2.0, output_per_1m=4.0)})
    await _enable_sidecar(async_client)
    key = await _create_api_key("provenance-api-key")

    await _post_chat(async_client, key)
    await get_lookup_coordinator().drain()
    await _post_chat(async_client, key)
    await get_lookup_coordinator().drain()

    response = await async_client.get("/api/request-logs")
    assert response.status_code == 200
    entries = [entry for entry in response.json()["requests"] if entry["source"] == "orcarouter_sidecar"]
    assert entries

    calculated = [entry for entry in entries if entry["costSource"] == CostSource.CATALOG_CALCULATED.value]
    unresolved = [entry for entry in entries if entry["priceStatus"] == ExternalPriceStatus.UNRESOLVED.value]
    assert calculated, f"expected a calculated row in {json.dumps(entries)[:400]}"
    assert unresolved, "the first, pre-lookup request must be marked unresolved"
