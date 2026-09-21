"""Concurrency of the per-endpoint catalog refresh behind ``GET /v1/models``.

Reported on https://github.com/vitalNohj/codex-lb/pull/59: ``/v1/models`` awaited
``list_models_cached()`` for each enabled endpoint in sequence. Each endpoint
carries its own ``request_timeout_seconds`` (600 s by default) and operators may
configure up to ``OPENAI_COMPAT_MAX_ENDPOINTS`` of them, so the first request
after cache expiry accumulated every endpoint's timeout in series rather than
waiting for the slowest one.

Measured by observing real overlap between the refreshes, not by reading the code:
a serial loop cannot have two refreshes in flight at once, however it is written.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from app.core.clients.claude_sidecar import SidecarPrefix
from app.core.clients.openai_compat_sidecar import (
    OpenAICompatSidecarConfig,
    OpenAICompatSidecarUnavailableError,
)
from app.db.session import SessionLocal
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeyCreateData, ApiKeysService

pytestmark = pytest.mark.integration

_ENDPOINT_IDS = (
    "2c9b8f3a-1e4d-4b7a-9c11-7a0e4d2b1c0a",
    "3d0c9e4b-2f5e-4c8b-8d22-8b1f5e3c2d1b",
    "4e1daf5c-3061-4d9c-9e33-9c2f6f4d3e2c",
    "5f2ebf6d-4172-4eaf-af44-ad3f7f5e4f3d",
)
_MODELS = tuple(f"vendor/model-{index}" for index in range(len(_ENDPOINT_IDS)))


@dataclass(frozen=True, slots=True)
class _FakeModel:
    id: str
    created: int | None = 123
    owned_by: str | None = "openai_compat"


class _ConcurrencyTrackingClient:
    """Records how many catalog refreshes were ever in flight at the same time."""

    def __init__(self, config: OpenAICompatSidecarConfig, tracker: _Tracker, model_id: str) -> None:
        self.config = config
        self._tracker = tracker
        self._model_id = model_id
        self.refresh_count = 0

    async def list_models_cached(self):
        self.refresh_count += 1
        self._tracker.enter()
        try:
            # One real suspension point, which is all a concurrent gather needs
            # to overlap and a serial loop can never exploit.
            await asyncio.sleep(0.05)
        finally:
            self._tracker.leave()
        return [_FakeModel(self._model_id)]

    async def chat_completion(self, payload):
        raise AssertionError("this test only exercises the catalog path")

    def stream_chat_completion(self, payload):
        raise AssertionError("this test only exercises the catalog path")


class _FailingClient(_ConcurrencyTrackingClient):
    async def list_models_cached(self):
        self.refresh_count += 1
        self._tracker.enter()
        try:
            await asyncio.sleep(0.05)
        finally:
            self._tracker.leave()
        # ``list_models_cached`` swallows provider errors itself; raising the
        # transport error from the *cached* call is the harsher case, and proves
        # one endpoint's failure does not abort the whole fanout.
        raise OpenAICompatSidecarUnavailableError("connection refused")


class _Tracker:
    def __init__(self) -> None:
        self.in_flight = 0
        self.max_in_flight = 0

    def enter(self) -> None:
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)

    def leave(self) -> None:
        self.in_flight -= 1


def _config(endpoint_id: str, index: int) -> OpenAICompatSidecarConfig:
    return OpenAICompatSidecarConfig(
        endpoint_id=endpoint_id,
        name=f"Endpoint {index}",
        enabled=True,
        base_url=f"https://endpoint-{index}.internal/v1",
        api_key=None,
        prefixes=(SidecarPrefix(prefix=f"ep{index}/", strip=True),),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
        full_models=(_MODELS[index],),
    )


@pytest.fixture
def fanout_endpoints(monkeypatch):
    tracker = _Tracker()
    configs = tuple(_config(endpoint_id, index) for index, endpoint_id in enumerate(_ENDPOINT_IDS))
    clients = {
        config.endpoint_id: _ConcurrencyTrackingClient(config, tracker, _MODELS[index])
        for index, config in enumerate(configs)
    }

    async def load_configs():
        return configs

    async def load_claude_disabled():
        return None

    monkeypatch.setattr("app.modules.proxy.api.load_openai_compat_configs", load_configs)
    monkeypatch.setattr("app.modules.proxy.api.load_sidecar_config", load_claude_disabled)
    monkeypatch.setattr(
        "app.modules.proxy.api.get_openai_compat_sidecar_client",
        lambda config: clients[config.endpoint_id],
    )
    return tracker, clients


async def _create_key(name: str):
    async with SessionLocal() as session:
        service = ApiKeysService(ApiKeysRepository(session))
        return await service.create_key(ApiKeyCreateData(name=name, allowed_models=None, limits=[]))


@pytest.mark.asyncio
async def test_endpoint_catalogs_are_refreshed_concurrently(async_client, fanout_endpoints):
    """Every endpoint's refresh overlaps, so latency is the slowest not the sum.

    Fails on the pre-fix serial loop with ``max_in_flight == 1``: a sequential
    ``await`` per endpoint cannot have two refreshes in flight whatever the
    timeouts are.
    """

    tracker, clients = fanout_endpoints
    auth = await async_client.put("/api/settings", json={"apiKeyAuthEnabled": True})
    assert auth.status_code == 200
    key = await _create_key("fanout-key")

    response = await async_client.get("/v1/models", headers={"Authorization": f"Bearer {key.key}"})

    assert response.status_code == 200, response.text
    assert tracker.max_in_flight == len(_ENDPOINT_IDS), (
        f"expected all {len(_ENDPOINT_IDS)} refreshes in flight together, peaked at {tracker.max_in_flight}"
    )
    # Exactly one refresh each: concurrency must not duplicate work.
    assert [client.refresh_count for client in clients.values()] == [1] * len(_ENDPOINT_IDS)


@pytest.mark.asyncio
async def test_every_endpoint_still_appears_in_the_advertised_catalog(async_client, fanout_endpoints):
    """Concurrency must not reorder or drop entries.

    Results stay positionally aligned with the enabled configs, so each
    endpoint's own discovered metadata lands on its own advertised model.
    """

    _tracker, _clients = fanout_endpoints
    auth = await async_client.put("/api/settings", json={"apiKeyAuthEnabled": True})
    assert auth.status_code == 200
    key = await _create_key("fanout-catalog-key")

    response = await async_client.get("/v1/models", headers={"Authorization": f"Bearer {key.key}"})

    assert response.status_code == 200, response.text
    ids = [item["id"] for item in response.json()["data"]]
    for model in _MODELS:
        assert model in ids, f"{model} missing from the advertised catalog"
    # Advertised in configured order, not in whatever order the refreshes landed.
    assert [model for model in ids if model in _MODELS] == list(_MODELS)


@pytest.mark.asyncio
async def test_one_failing_endpoint_does_not_remove_the_others(async_client, fanout_endpoints, monkeypatch):
    """Per-endpoint failure stays isolated, as it was before the gather.

    ``asyncio.gather`` propagates the first exception by default, so a raising
    refresh must not be able to empty the whole catalog.
    """

    tracker, clients = fanout_endpoints
    failing_id = _ENDPOINT_IDS[1]
    failing_config = clients[failing_id].config
    clients[failing_id] = _FailingClient(failing_config, tracker, _MODELS[1])
    monkeypatch.setattr(
        "app.modules.proxy.api.get_openai_compat_sidecar_client",
        lambda config: clients[config.endpoint_id],
    )

    auth = await async_client.put("/api/settings", json={"apiKeyAuthEnabled": True})
    assert auth.status_code == 200
    key = await _create_key("fanout-failure-key")

    response = await async_client.get("/v1/models", headers={"Authorization": f"Bearer {key.key}"})

    assert response.status_code == 200, response.text
    ids = [item["id"] for item in response.json()["data"]]
    # The healthy endpoints are all still advertised. The failing endpoint's
    # configured full model stays advertised too: pinning is the operator's
    # explicit statement that the id is offered, and only its *discovered*
    # metadata is unavailable.
    for index, model in enumerate(_MODELS):
        if index != 1:
            assert model in ids, f"{model} lost because another endpoint failed"


@pytest.fixture
def fanout_endpoints_dashboard(monkeypatch):
    """Same fanout, patched where the dashboard model picker resolves clients."""

    tracker = _Tracker()
    configs = tuple(_config(endpoint_id, index) for index, endpoint_id in enumerate(_ENDPOINT_IDS))
    clients = {
        config.endpoint_id: _ConcurrencyTrackingClient(config, tracker, _MODELS[index])
        for index, config in enumerate(configs)
    }

    async def load_configs():
        return configs

    async def load_claude_disabled():
        return None

    monkeypatch.setattr("app.modules.dashboard.api.load_openai_compat_configs", load_configs)
    monkeypatch.setattr("app.modules.dashboard.api.load_sidecar_config", load_claude_disabled)
    monkeypatch.setattr(
        "app.modules.dashboard.api.get_openai_compat_sidecar_client",
        lambda config: clients[config.endpoint_id],
    )
    return tracker, clients


@pytest.mark.asyncio
async def test_the_dashboard_model_picker_also_refreshes_concurrently(async_client, fanout_endpoints_dashboard):
    """``GET /api/models`` had the same serial fanout as ``/v1/models``.

    Same 600 s-per-endpoint stacking, on the surface an operator stares at while
    it happens. Fails on the pre-fix serial loop with ``max_in_flight == 1``.
    """

    tracker, clients = fanout_endpoints_dashboard

    response = await async_client.get("/api/models")

    assert response.status_code == 200, response.text
    assert tracker.max_in_flight == len(_ENDPOINT_IDS), (
        f"expected all {len(_ENDPOINT_IDS)} refreshes in flight together, peaked at {tracker.max_in_flight}"
    )
    assert [client.refresh_count for client in clients.values()] == [1] * len(_ENDPOINT_IDS)


@pytest.mark.asyncio
async def test_the_dashboard_picker_keeps_the_other_endpoints_when_one_fails(
    async_client, fanout_endpoints_dashboard, monkeypatch
):
    """Per-endpoint isolation must survive the switch to ``gather``.

    The pre-fix code had a per-endpoint ``try``; a bare ``gather`` would have
    dropped every endpoint's models when any one raised.
    """

    tracker, clients = fanout_endpoints_dashboard
    failing_id = _ENDPOINT_IDS[1]
    clients[failing_id] = _FailingClient(clients[failing_id].config, tracker, _MODELS[1])
    monkeypatch.setattr(
        "app.modules.dashboard.api.get_openai_compat_sidecar_client",
        lambda config: clients[config.endpoint_id],
    )

    response = await async_client.get("/api/models")

    assert response.status_code == 200, response.text
    ids = [item["id"] for item in response.json()["models"]]
    for index, model in enumerate(_MODELS):
        if index != 1:
            assert model in ids, f"{model} lost from the picker because another endpoint failed"
    assert _MODELS[1] not in ids
