from __future__ import annotations

import pytest

from app.core.clients.claude_sidecar import SidecarModel
from app.core.clients.ollama_sidecar import OllamaSidecarError, OllamaSidecarUnavailableError

pytestmark = pytest.mark.integration


class _FakeOllamaClient:
    error: Exception | None = None
    models = [SidecarModel(id="gpt-oss:120b-cloud", created=123, owned_by="ollama")]

    def __init__(self, _config) -> None:
        pass

    async def list_models(self):
        if self.error is not None:
            raise self.error
        return list(self.models)

    async def list_models_cached(self):
        return await self.list_models()


@pytest.mark.asyncio
async def test_ollama_sidecar_status_reports_disabled_and_missing_api_key(async_client):
    response = await async_client.put(
        "/api/settings",
        json={
            "ollamaSidecarEnabled": False,
            "ollamaSidecarClearApiKey": True,
        },
    )
    assert response.status_code == 200

    response = await async_client.get("/api/ollama-sidecar/status")
    assert response.status_code == 200
    assert response.json()["status"] == "disabled"

    response = await async_client.put(
        "/api/settings",
        json={
            "ollamaSidecarEnabled": True,
            "ollamaSidecarClearApiKey": True,
        },
    )
    assert response.status_code == 200

    response = await async_client.get("/api/ollama-sidecar/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "missing_api_key"
    assert payload["configured"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (OllamaSidecarUnavailableError("connection refused Bearer secret"), "unreachable"),
        (OllamaSidecarError(401, "bad key"), "unauthorized"),
        (OllamaSidecarError(500, "sidecar exploded"), "error"),
    ],
)
async def test_ollama_sidecar_test_connection_records_error_statuses(
    async_client,
    monkeypatch,
    error,
    expected_status,
):
    monkeypatch.setattr("app.modules.ollama_sidecar.service.OllamaSidecarClient", _FakeOllamaClient)
    _FakeOllamaClient.error = error
    response = await async_client.put(
        "/api/settings",
        json={
            "ollamaSidecarEnabled": True,
            "ollamaSidecarApiKey": "ollama-key",
        },
    )
    assert response.status_code == 200

    response = await async_client.post("/api/ollama-sidecar/test")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == expected_status
    assert payload["modelCount"] is None
    assert "secret" not in (payload.get("message") or "")

    status = await async_client.get("/api/ollama-sidecar/status")
    assert status.status_code == 200
    assert status.json()["status"] == expected_status


@pytest.mark.asyncio
async def test_ollama_sidecar_test_connection_records_healthy_and_lists_models(async_client, monkeypatch):
    monkeypatch.setattr("app.modules.ollama_sidecar.service.OllamaSidecarClient", _FakeOllamaClient)
    _FakeOllamaClient.error = None
    _FakeOllamaClient.models = [
        SidecarModel(id="gpt-oss:120b-cloud", created=123, owned_by="ollama"),
        SidecarModel(id="kimi-k2-thinking", created=None, owned_by="ollama"),
    ]
    response = await async_client.put(
        "/api/settings",
        json={
            "ollamaSidecarEnabled": True,
            "ollamaSidecarApiKey": "ollama-key",
        },
    )
    assert response.status_code == 200

    response = await async_client.post("/api/ollama-sidecar/test")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "healthy"
    assert payload["modelCount"] == 2
    assert payload["models"] == [
        {"id": "gpt-oss:120b-cloud", "created": 123, "ownedBy": "ollama"},
        {"id": "kimi-k2-thinking", "created": None, "ownedBy": "ollama"},
    ]

    response = await async_client.get("/api/ollama-sidecar/models")
    assert response.status_code == 200
    assert response.json()["models"] == [
        {"id": "gpt-oss:120b-cloud", "created": 123, "ownedBy": "ollama"},
        {"id": "kimi-k2-thinking", "created": None, "ownedBy": "ollama"},
    ]
