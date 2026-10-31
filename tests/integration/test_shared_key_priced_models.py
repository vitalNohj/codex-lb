"""A shared API key is served only models with a real, nonzero price.

A shared key is handed to someone else, so codex-lb refuses it any model that
is not priced yet, whatever limits the key carries. That covers a model asked
for by name and any model codex-lb itself resolves on the key's behalf (an
alias, an alias-pool failover target, an enforced model). A free model priced
at ``0`` counts as not priced. The model listings leave such models out. A key
that is not shared is served and shown everything, as before.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

import app.core.usage.external_pricing.service as external_pricing_service
from app.core.usage.external_pricing.store import ExternalModelPriceStore
from app.core.usage.pricing import ModelPrice
from app.db.models import ApiKeyUsageReservation, ModelSource, ModelSourceModel
from app.db.session import SessionLocal
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeysService, ApiKeyUnpricedModelError
from app.modules.proxy.api_key_pricing import source_price_check

pytestmark = pytest.mark.integration

_PRICED_MODEL = "gpt-5.4"
_UNPRICED_MODEL = "codex-lb-test-unpriced-model"
_FREE_MODEL = "z-ai/glm-4.5-air:free"
_PAID_SIDECAR_MODEL = "z-ai/glm-4.6"
_UNPRICED_SIDECAR_MODEL = "z-ai/glm-unpriced"
_ALIAS = "team/default"


@pytest.fixture(autouse=True)
def _no_background_price_lookups(monkeypatch):
    """Admission schedules a catalog lookup for a model it has never seen; keep it offline."""

    async def submit(key, factory):
        del key, factory

    monkeypatch.setattr(external_pricing_service._coordinator, "submit", submit)


async def _create_key(async_client, *, name: str, shared: bool, **extra: object) -> tuple[str, str]:
    response = await async_client.post("/api/api-keys/", json={"name": name, "isShared": shared, **extra})
    assert response.status_code == 200, response.text
    payload = response.json()
    return payload["id"], payload["key"]


async def _enforce(key_id: str, model: str):
    async with SessionLocal() as session:
        return await ApiKeysService(ApiKeysRepository(session)).enforce_limits_for_request(key_id, request_model=model)


async def _enable_api_key_auth(async_client) -> None:
    response = await async_client.put("/api/settings", json={"apiKeyAuthEnabled": True})
    assert response.status_code == 200, response.text


async def _configure_openrouter(async_client, *, aliases: dict[str, object] | None = None) -> None:
    settings: dict[str, object] = {
        "openrouterSidecarEnabled": True,
        "openrouterSidecarApiKey": "openrouter-key",
        "openrouterSidecarModelPrefixes": ["z-ai/"],
        "openrouterSidecarFullModels": [_FREE_MODEL, _PAID_SIDECAR_MODEL, _UNPRICED_SIDECAR_MODEL],
    }
    if aliases is not None:
        settings["modelAliases"] = aliases
    response = await async_client.put("/api/settings", json=settings)
    assert response.status_code == 200, response.text


async def _seed_openrouter_prices() -> None:
    async with SessionLocal() as session:
        store = ExternalModelPriceStore(session)
        for model, price in (
            (_FREE_MODEL, ModelPrice(input_per_1m=0.0, output_per_1m=0.0, cached_input_per_1m=0.0)),
            (_PAID_SIDECAR_MODEL, ModelPrice(input_per_1m=0.6, output_per_1m=2.2)),
        ):
            await store.record_resolved(
                provider="openrouter",
                incoming_model=model,
                catalog_model=model,
                catalog_source="openrouter",
                price=price,
                resolution_step="exact",
            )


async def _reservations(key_id: str) -> list[ApiKeyUsageReservation]:
    async with SessionLocal() as session:
        result = await session.execute(
            select(ApiKeyUsageReservation).where(ApiKeyUsageReservation.api_key_id == key_id)
        )
        return list(result.scalars().all())


def _chat_request(model: str) -> dict[str, object]:
    return {"model": model, "messages": [{"role": "user", "content": "hi"}]}


# --- direct: a model asked for by name ----------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "limits",
    [
        pytest.param([], id="no-limits"),
        pytest.param(
            [{"limitType": "total_tokens", "limitWindow": "lifetime", "maxValue": 1_000_000}],
            id="token-limit-only",
        ),
        pytest.param(
            [{"limitType": "cost_usd", "limitWindow": "lifetime", "maxValue": 5_000_000}],
            id="cost-limit",
        ),
    ],
)
async def test_a_shared_key_refuses_an_unpriced_model_whatever_its_limits(async_client, limits):
    key_id, _ = await _create_key(async_client, name=f"shared-{len(limits)}", shared=True, limits=limits)

    with pytest.raises(ApiKeyUnpricedModelError, match="not priced yet"):
        await _enforce(key_id, _UNPRICED_MODEL)

    assert await _reservations(key_id) == []
    # A priced model is still served.
    await _enforce(key_id, _PRICED_MODEL)


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["openrouter/some-model:free", "big-pickle", "codex-auto-review"])
async def test_a_shared_key_refuses_free_and_unlisted_static_models(async_client, model):
    key_id, _ = await _create_key(async_client, name=f"shared-static-{model}", shared=True)

    with pytest.raises(ApiKeyUnpricedModelError):
        await _enforce(key_id, model)


@pytest.mark.asyncio
async def test_a_key_that_is_not_shared_is_served_unpriced_and_free_models(async_client):
    key_id, _ = await _create_key(async_client, name="private", shared=False)

    await _enforce(key_id, _UNPRICED_MODEL)
    await _enforce(key_id, "openrouter/some-model:free")


@pytest.mark.asyncio
async def test_a_price_check_that_fails_refuses_a_shared_key(async_client):
    key_id, _ = await _create_key(async_client, name="shared-lookup-fails", shared=True)

    async def unavailable() -> bool:
        raise RuntimeError("price store unreachable")

    async with SessionLocal() as session:
        service = ApiKeysService(ApiKeysRepository(session))
        with pytest.raises(ApiKeyUnpricedModelError):
            await service.enforce_limits_for_request(
                key_id, request_model=_PRICED_MODEL, model_is_priced=unavailable
            )


@pytest.mark.asyncio
async def test_a_shared_key_is_refused_an_unpriced_model_on_the_proxy(async_client):
    await _enable_api_key_auth(async_client)
    _, key = await _create_key(async_client, name="shared-proxy", shared=True)

    response = await async_client.post(
        "/v1/responses",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": _UNPRICED_MODEL, "input": "hi"},
    )

    assert response.status_code == 403, response.text
    error = response.json()["error"]
    assert error["code"] == "model_not_priced"
    assert _UNPRICED_MODEL in error["message"]
    assert "not priced yet" in error["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize("model", [_FREE_MODEL, _UNPRICED_SIDECAR_MODEL])
async def test_a_shared_key_is_refused_a_free_or_unpriced_sidecar_model(async_client, model):
    await _configure_openrouter(async_client)
    await _seed_openrouter_prices()
    await _enable_api_key_auth(async_client)
    _, key = await _create_key(async_client, name=f"shared-sidecar-{model}", shared=True)

    response = await async_client.post(
        "/v1/chat/completions", headers={"Authorization": f"Bearer {key}"}, json=_chat_request(model)
    )

    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "model_not_priced"


@pytest.mark.asyncio
async def test_a_shared_key_refuses_a_model_source_rated_at_zero(async_client):
    source = ModelSource(id="src-zero", name="zero-rated", kind="openai_compatible", base_url="http://127.0.0.1:9/v1")
    source.models = [
        ModelSourceModel(model="local-zero", is_enabled=True, input_per_1m=0.0, output_per_1m=0.0),
        ModelSourceModel(model="local-paid", is_enabled=True, input_per_1m=0.1, output_per_1m=0.2),
    ]

    key_id, _ = await _create_key(async_client, name="shared-source", shared=True)
    async with SessionLocal() as session:
        service = ApiKeysService(ApiKeysRepository(session))
        with pytest.raises(ApiKeyUnpricedModelError):
            await service.enforce_limits_for_request(
                key_id, request_model="local-zero", model_is_priced=source_price_check(source, "local-zero")
            )
        await service.enforce_limits_for_request(
            key_id, request_model="local-paid", model_is_priced=source_price_check(source, "local-paid")
        )


# --- intrinsic: a model codex-lb resolves on the key's behalf -----------------


@pytest.mark.asyncio
async def test_an_alias_to_a_free_model_is_refused_for_a_shared_key(async_client):
    await _configure_openrouter(async_client, aliases={_ALIAS: {"targets": [_FREE_MODEL]}})
    await _seed_openrouter_prices()
    await _enable_api_key_auth(async_client)
    _, key = await _create_key(async_client, name="shared-alias", shared=True)

    for path, body in (
        ("/v1/chat/completions", _chat_request(_ALIAS)),
        ("/v1/responses", {"model": _ALIAS, "input": "hi"}),
    ):
        response = await async_client.post(path, headers={"Authorization": f"Bearer {key}"}, json=body)
        assert response.status_code == 403, (path, response.text)
        assert response.json()["error"]["code"] == "model_not_priced"


@pytest.mark.asyncio
async def test_an_alias_pool_with_a_free_failover_target_is_refused_for_a_shared_key(async_client):
    await _configure_openrouter(
        async_client,
        aliases={_ALIAS: {"targets": [_PAID_SIDECAR_MODEL, _FREE_MODEL]}},
    )
    await _seed_openrouter_prices()
    await _enable_api_key_auth(async_client)
    _, key = await _create_key(async_client, name="shared-pool", shared=True)

    response = await async_client.post(
        "/v1/chat/completions", headers={"Authorization": f"Bearer {key}"}, json=_chat_request(_ALIAS)
    )

    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "model_not_priced"


@pytest.mark.asyncio
async def test_an_enforced_unpriced_model_is_refused_for_a_shared_key(async_client):
    await _enable_api_key_auth(async_client)
    _, key = await _create_key(
        async_client, name="shared-enforced", shared=True, enforcedModel="openrouter/some-model:free"
    )

    response = await async_client.post(
        "/v1/responses",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": _PRICED_MODEL, "input": "hi"},
    )

    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "model_not_priced"


# --- listings -----------------------------------------------------------------


async def _listed_ids(async_client, key: str) -> tuple[set[str], set[str]]:
    headers = {"Authorization": f"Bearer {key}"}
    v1 = await async_client.get("/v1/models", headers=headers)
    assert v1.status_code == 200, v1.text
    codex = await async_client.get("/backend-api/codex/models", headers=headers)
    assert codex.status_code == 200, codex.text
    codex_ids = {entry["slug"] for entry in codex.json()["models"]} | {item["id"] for item in codex.json()["data"]}
    return {item["id"] for item in v1.json()["data"]}, codex_ids


@pytest.mark.asyncio
async def test_a_shared_key_lists_only_priced_models(async_client, monkeypatch):
    async def no_remote_models(self):
        del self
        return []

    from app.core.clients.openrouter_sidecar import OpenRouterSidecarClient

    monkeypatch.setattr(OpenRouterSidecarClient, "list_models_cached", no_remote_models)
    await _configure_openrouter(
        async_client,
        aliases={
            "team/free": {"targets": [_FREE_MODEL]},
            "team/paid": {"targets": [_PAID_SIDECAR_MODEL]},
        },
    )
    await _seed_openrouter_prices()
    await _enable_api_key_auth(async_client)
    _, shared_key = await _create_key(async_client, name="shared-listing", shared=True)
    _, private_key = await _create_key(async_client, name="private-listing", shared=False)

    private_v1, private_codex = await _listed_ids(async_client, private_key)
    shared_v1, shared_codex = await _listed_ids(async_client, shared_key)

    # The private key is shown everything, as before.
    assert {_FREE_MODEL, _UNPRICED_SIDECAR_MODEL, _PAID_SIDECAR_MODEL, "team/free", "team/paid"} <= private_v1
    # The shared key is shown only what it would be served.
    assert _PAID_SIDECAR_MODEL in shared_v1
    assert "team/paid" in shared_v1
    assert {_FREE_MODEL, _UNPRICED_SIDECAR_MODEL, "team/free"}.isdisjoint(shared_v1)
    assert shared_v1 <= private_v1
    assert "codex-auto-review" not in shared_codex
    assert shared_codex <= private_codex
    assert all(not model.endswith(":free") for model in shared_v1 | shared_codex)
