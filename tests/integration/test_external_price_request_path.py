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
from app.core.usage.external_pricing.store import ExternalModelPriceStore
from app.core.usage.pricing import ModelPrice
from app.db.models import ApiKeyLimit, CostSource, ExternalPriceStatus, RequestLog
from app.db.session import SessionLocal
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeyCreateData, ApiKeysService, LimitRuleInput
from app.modules.request_logs.repository import RequestLogsRepository

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


async def _create_api_key(name: str, *, limits: list[LimitRuleInput] | None = None):
    async with SessionLocal() as session:
        service = ApiKeysService(ApiKeysRepository(session))
        return await service.create_key(ApiKeyCreateData(name=name, allowed_models=None, limits=limits or []))


async def _limit_values(key_id: str) -> dict[str, int]:
    async with SessionLocal() as session:
        rows = (await session.execute(select(ApiKeyLimit).where(ApiKeyLimit.api_key_id == key_id))).scalars().all()
    return {row.limit_type.value: row.current_value for row in rows}


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
    marked pending rather than unresolved because no lookup has completed yet.
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
    # Pending, not unresolved: no lookup had concluded anything when this row was
    # written, so it is not evidence that the model has no published price.
    assert first.price_status == ExternalPriceStatus.PENDING.value

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

    logs = sorted((log for log in await _sidecar_logs() if log.model == unlisted), key=lambda log: log.id)
    assert logs, "the request must still be served and logged"
    for log in logs:
        assert log.cost_usd is None, "an unresolved model must not borrow another model's rate"
    # The first row predates the lookup, so it is pending. The second is written
    # after the lookup concluded nothing, which is what earns the marker.
    assert logs[0].price_status == ExternalPriceStatus.PENDING.value
    assert logs[-1].price_status == ExternalPriceStatus.UNRESOLVED.value

    # The name matches the retired ``*gpt-4o*`` alias glob, so the read path is
    # where the wrong number used to reappear: the database said NULL while the
    # API returned GPT-4o's rate and the UI therefore never showed ``!!``.
    from app.core.usage.pricing import get_pricing_for_model

    assert get_pricing_for_model(unlisted, None, None) is not None, "this id must still match a glob"

    response = await async_client.get("/api/request-logs")
    assert response.status_code == 200
    entries = [entry for entry in response.json()["requests"] if entry["model"] == unlisted]
    assert entries
    for entry in entries:
        assert entry["costUsd"] is None, "the API must not price an unresolved model from the static table"
        assert entry["costBreakdown"]["totalUsd"] is None
    assert {entry["priceStatus"] for entry in entries} == {ExternalPriceStatus.UNRESOLVED.value}


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
    assert log.price_status == ExternalPriceStatus.PENDING.value


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
    assert calculated, f"expected a calculated row in {json.dumps(entries)[:400]}"
    assert {entry["priceStatus"] for entry in entries} == {ExternalPriceStatus.RESOLVED.value}
    assert not [entry for entry in entries if entry["priceStatus"] == ExternalPriceStatus.UNRESOLVED.value], (
        "a model that resolved must not leave an unresolved row behind"
    )


@pytest.mark.asyncio
async def test_request_log_display_uses_current_durable_price_status(async_client) -> None:
    models = {
        "unresolved": "vendor/display-unresolved",
        "ambiguous": "vendor/display-ambiguous",
        "resolved": "vendor/display-resolved",
        "pending": "vendor/display-pending",
        "missing_input": "vendor/display-missing-input",
        "missing_output": "vendor/display-missing-output",
        "not_token_priced": "vendor/display-router",
        "billed": "vendor/display-billed",
    }
    async with SessionLocal() as session:
        logs = RequestLogsRepository(session)
        for label, model in models.items():
            input_tokens = None if label == "missing_input" else 10
            output_tokens = None if label == "missing_output" else 5
            billed = label == "billed"
            await logs.add_log(
                account_id=None,
                request_id=f"req-display-{label}",
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=1,
                status="success",
                error_code=None,
                source="orcarouter_sidecar",
                cost_usd=0.01 if billed else None,
                cost_source=CostSource.UPSTREAM_BILLED.value if billed else None,
                price_status=ExternalPriceStatus.PENDING.value,
            )

        store = ExternalModelPriceStore(session)
        for label in ("unresolved", "missing_input", "missing_output", "billed"):
            await store.record_unresolved(
                provider="orcarouter",
                incoming_model=models[label],
                status=ExternalPriceStatus.UNRESOLVED,
                detail="no catalog match",
            )
        await store.record_unresolved(
            provider="orcarouter",
            incoming_model=models["ambiguous"],
            status=ExternalPriceStatus.AMBIGUOUS,
            detail="multiple catalog matches",
        )
        await store.record_resolved(
            provider="orcarouter",
            incoming_model=models["resolved"],
            catalog_model=models["resolved"],
            catalog_source="orcarouter",
            price=ModelPrice(input_per_1m=2.0, output_per_1m=4.0),
            resolution_step="exact",
        )
        await store.record_not_token_priced(
            provider="orcarouter",
            incoming_model=models["not_token_priced"],
            catalog_model=models["not_token_priced"],
            catalog_source="orcarouter",
            resolution_step="exact",
            detail="router model",
        )

    response = await async_client.get("/api/request-logs")
    assert response.status_code == 200
    entries = {entry["model"]: entry for entry in response.json()["requests"] if entry["model"] in models.values()}

    assert entries[models["unresolved"]]["priceStatus"] == ExternalPriceStatus.UNRESOLVED.value
    assert entries[models["ambiguous"]]["priceStatus"] == ExternalPriceStatus.AMBIGUOUS.value
    assert entries[models["resolved"]]["priceStatus"] == ExternalPriceStatus.RESOLVED.value
    assert entries[models["pending"]]["priceStatus"] == ExternalPriceStatus.PENDING.value
    assert entries[models["missing_input"]]["inputTokens"] is None
    assert entries[models["missing_input"]]["priceStatus"] == ExternalPriceStatus.UNRESOLVED.value
    assert entries[models["missing_output"]]["outputTokens"] is None
    assert entries[models["missing_output"]]["priceStatus"] == ExternalPriceStatus.UNRESOLVED.value
    assert entries[models["not_token_priced"]]["priceStatus"] == ExternalPriceStatus.NOT_TOKEN_PRICED.value
    assert entries[models["billed"]]["costUsd"] == pytest.approx(0.01)
    assert entries[models["billed"]]["costSource"] == CostSource.UPSTREAM_BILLED.value


@pytest.mark.asyncio
async def test_a_resolved_row_exposes_its_persisted_total_to_the_details_view(
    async_client,
    orcarouter_enabled,
    fake_orcarouter,
) -> None:
    """A resolved external row exposes its persisted total without inventing a split."""

    fake_orcarouter.billed_cost_usd = None
    _install_catalog({_MODEL: ModelPrice(input_per_1m=2.0, output_per_1m=4.0)})
    await _enable_sidecar(async_client)
    key = await _create_api_key("breakdown-api-key")

    await _post_chat(async_client, key)
    await get_lookup_coordinator().drain()
    await _post_chat(async_client, key)
    await get_lookup_coordinator().drain()

    response = await async_client.get("/api/request-logs")
    assert response.status_code == 200
    priced = [
        entry
        for entry in response.json()["requests"]
        if entry["source"] == "orcarouter_sidecar" and entry["costUsd"] is not None
    ]
    assert priced, "expected the resolved row"
    breakdown = priced[0]["costBreakdown"]
    assert breakdown["inputUsd"] is None
    assert breakdown["cachedInputUsd"] is None
    assert breakdown["outputUsd"] is None
    assert breakdown["totalUsd"] == pytest.approx(priced[0]["costUsd"])


@pytest.mark.asyncio
async def test_an_unresolved_row_reports_no_savings_from_the_retired_glob_table(
    async_client,
    orcarouter_enabled,
    fake_orcarouter,
) -> None:
    """Phantom savings regression.

    ``orcarouter/gpt-4o-lookalike`` matches the retired ``*gpt-4o*`` alias, so its
    reference cost used to come from GPT-4o's rate. With the actual cost now NULL,
    the whole reference read as money saved on the provider card.
    """

    from app.core.usage.pricing import get_pricing_for_model

    fake_orcarouter.billed_cost_usd = None
    unlisted = "orcarouter/gpt-4o-lookalike"
    assert get_pricing_for_model(unlisted, None, None) is not None, "this id must still match a glob"

    _install_catalog({_MODEL: ModelPrice(input_per_1m=2.0, output_per_1m=4.0)})
    await _enable_sidecar(async_client)
    await async_client.put("/api/settings", json={"orcarouterSidecarFullModels": [_MODEL, unlisted]})
    key = await _create_api_key("phantom-savings-key")

    for _ in range(2):
        response = await async_client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {key.key}"},
            json={"model": unlisted, "messages": [{"role": "user", "content": "hi"}]},
        )
        assert response.status_code == 200
        await get_lookup_coordinator().drain()

    for log in await _sidecar_logs():
        if log.model != unlisted:
            continue
        assert log.cost_usd is None
        assert log.reference_cost_usd is None, "no glob-derived reference may be persisted"

    response = await async_client.get("/api/request-logs")
    assert response.status_code == 200
    entries = [entry for entry in response.json()["requests"] if entry["model"] == unlisted]
    assert entries
    for entry in entries:
        assert entry["costUsd"] is None
        assert not entry.get("savingsUsd"), "an unknown cost must not report savings"


@pytest.mark.asyncio
async def test_an_unresolved_model_accrues_no_cost_quota_but_is_still_token_counted(
    async_client,
    orcarouter_enabled,
    fake_orcarouter,
) -> None:
    """A cost limit must never be charged at a retired glob rate.

    ``orcarouter/gpt-4o-lookalike`` matches ``*gpt-4o*``, so reservation
    settlement used to debit GPT-4o's rate against the key's COST_USD limit while
    the request log recorded NULL for the same request -- two owners of one fact
    disagreeing, with the log being what a re-created limit backfills from.
    Token limits are unaffected: the request is served and counted as before.
    """

    from app.core.usage.pricing import get_pricing_for_model

    fake_orcarouter.billed_cost_usd = None
    unlisted = "orcarouter/gpt-4o-lookalike"
    assert get_pricing_for_model(unlisted, None, None) is not None, "this id must still match a glob"

    _install_catalog({_MODEL: ModelPrice(input_per_1m=2.0, output_per_1m=4.0)})
    await _enable_sidecar(async_client)
    await async_client.put("/api/settings", json={"orcarouterSidecarFullModels": [_MODEL, unlisted]})
    key = await _create_api_key(
        "unresolved-quota-key",
        limits=[
            LimitRuleInput(limit_type="cost_usd", limit_window="weekly", max_value=100_000_000),
            LimitRuleInput(limit_type="total_tokens", limit_window="weekly", max_value=1_000_000),
        ],
    )

    for _ in range(2):
        response = await async_client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {key.key}"},
            json={"model": unlisted, "messages": [{"role": "user", "content": "hi"}]},
        )
        assert response.status_code == 200, "an unresolved price must not deny the request"
        await get_lookup_coordinator().drain()

    values = await _limit_values(key.id)
    assert values["cost_usd"] == 0, "an unresolved model must not be charged a glob-derived rate"
    assert values["total_tokens"] == 2 * (_INPUT_TOKENS + _OUTPUT_TOKENS)

    for log in await _sidecar_logs():
        if log.model == unlisted:
            assert log.cost_usd is None


@pytest.mark.asyncio
async def test_reservation_settlement_resolves_no_price_of_its_own(
    async_client,
    orcarouter_enabled,
    fake_orcarouter,
    monkeypatch,
) -> None:
    """One request resolves its cost once, and settlement reuses that answer.

    Settlement resolving again would read the store a second time from inside an
    already-open background session, and a concurrent lookup landing between the
    two reads would charge a quota figure the log row does not carry.
    """

    from app.modules.proxy import orcarouter_sidecar_dispatch

    fake_orcarouter.billed_cost_usd = None
    _install_catalog({_MODEL: ModelPrice(input_per_1m=2_000_000.0, output_per_1m=4_000_000.0)})
    await _enable_sidecar(async_client)

    resolutions: list[str] = []
    original = orcarouter_sidecar_dispatch._orcarouter_request_cost

    async def _counting(model, usage, *, billed_cost_usd=None):
        resolutions.append(model)
        return await original(model, usage, billed_cost_usd=billed_cost_usd)

    monkeypatch.setattr(orcarouter_sidecar_dispatch, "_orcarouter_request_cost", _counting)

    key = await _create_api_key(
        "single-resolution-key",
        limits=[LimitRuleInput(limit_type="cost_usd", limit_window="weekly", max_value=1_000_000_000)],
    )
    await _post_chat(async_client, key)
    await get_lookup_coordinator().drain()
    resolutions.clear()
    await _post_chat(async_client, key)
    await get_lookup_coordinator().drain()

    assert resolutions == [_MODEL], "the quota charge and the log row must share one resolution"

    priced = [log for log in await _sidecar_logs() if log.cost_usd is not None]
    assert priced
    values = await _limit_values(key.id)
    assert values["cost_usd"] == int(priced[-1].cost_usd * 1_000_000)


@pytest.mark.asyncio
async def test_a_resolved_model_charges_the_cost_limit_the_price_it_recorded(
    async_client,
    orcarouter_enabled,
    fake_orcarouter,
) -> None:
    """The quota and the request log must agree on the same number."""

    fake_orcarouter.billed_cost_usd = None
    _install_catalog({_MODEL: ModelPrice(input_per_1m=2_000_000.0, output_per_1m=4_000_000.0)})
    await _enable_sidecar(async_client)
    key = await _create_api_key(
        "resolved-quota-key",
        limits=[LimitRuleInput(limit_type="cost_usd", limit_window="weekly", max_value=1_000_000_000)],
    )

    await _post_chat(async_client, key)
    await get_lookup_coordinator().drain()
    await _post_chat(async_client, key)
    await get_lookup_coordinator().drain()

    priced = [log for log in await _sidecar_logs() if log.cost_usd is not None]
    assert priced, "the second request must be priced from the catalog"
    expected_microdollars = int(priced[0].cost_usd * 1_000_000)
    assert expected_microdollars > 0

    values = await _limit_values(key.id)
    assert values["cost_usd"] == expected_microdollars
