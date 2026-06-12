from __future__ import annotations

import pytest

from app.core.clients.claude_sidecar import SidecarModel
from app.core.clients.openrouter_sidecar import OpenRouterSidecarError, OpenRouterSidecarUnavailableError

pytestmark = pytest.mark.integration


class _FakeOpenRouterClient:
    error: Exception | None = None
    models = [SidecarModel(id="deepseek/deepseek-chat", created=123, owned_by="deepseek")]

    def __init__(self, _config) -> None:
        pass

    async def list_models(self):
        if self.error is not None:
            raise self.error
        return list(self.models)

    async def list_models_cached(self):
        return await self.list_models()


@pytest.mark.asyncio
async def test_openrouter_sidecar_status_reports_disabled_and_missing_api_key(async_client):
    response = await async_client.put(
        "/api/settings",
        json={
            "openrouterSidecarEnabled": False,
            "openrouterSidecarClearApiKey": True,
        },
    )
    assert response.status_code == 200

    response = await async_client.get("/api/openrouter-sidecar/status")
    assert response.status_code == 200
    assert response.json()["status"] == "disabled"

    response = await async_client.put(
        "/api/settings",
        json={
            "openrouterSidecarEnabled": True,
            "openrouterSidecarClearApiKey": True,
        },
    )
    assert response.status_code == 200

    response = await async_client.get("/api/openrouter-sidecar/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "missing_api_key"
    assert payload["configured"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (OpenRouterSidecarUnavailableError("connection refused"), "unreachable"),
        (OpenRouterSidecarError(401, "bad key"), "unauthorized"),
        (OpenRouterSidecarError(500, "sidecar exploded"), "error"),
    ],
)
async def test_openrouter_sidecar_test_connection_records_error_statuses(
    async_client,
    monkeypatch,
    error,
    expected_status,
):
    monkeypatch.setattr("app.modules.openrouter_sidecar.service.OpenRouterSidecarClient", _FakeOpenRouterClient)
    _FakeOpenRouterClient.error = error
    response = await async_client.put(
        "/api/settings",
        json={
            "openrouterSidecarEnabled": True,
            "openrouterSidecarApiKey": "openrouter-key",
        },
    )
    assert response.status_code == 200

    response = await async_client.post("/api/openrouter-sidecar/test")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == expected_status
    assert payload["modelCount"] is None

    status = await async_client.get("/api/openrouter-sidecar/status")
    assert status.status_code == 200
    assert status.json()["status"] == expected_status


@pytest.mark.asyncio
async def test_openrouter_sidecar_test_connection_records_healthy_and_lists_models(async_client, monkeypatch):
    monkeypatch.setattr("app.modules.openrouter_sidecar.service.OpenRouterSidecarClient", _FakeOpenRouterClient)
    _FakeOpenRouterClient.error = None
    _FakeOpenRouterClient.models = [
        SidecarModel(id="deepseek/deepseek-chat", created=123, owned_by="deepseek")
    ]
    response = await async_client.put(
        "/api/settings",
        json={
            "openrouterSidecarEnabled": True,
            "openrouterSidecarApiKey": "openrouter-key",
        },
    )
    assert response.status_code == 200

    response = await async_client.post("/api/openrouter-sidecar/test")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "healthy"
    assert payload["modelCount"] == 1
    assert payload["models"] == [{"id": "deepseek/deepseek-chat", "created": 123, "ownedBy": "deepseek"}]

    response = await async_client.get("/api/openrouter-sidecar/models")
    assert response.status_code == 200
    assert response.json()["models"] == [{"id": "deepseek/deepseek-chat", "created": 123, "ownedBy": "deepseek"}]
