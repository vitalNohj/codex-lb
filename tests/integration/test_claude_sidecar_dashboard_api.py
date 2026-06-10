from __future__ import annotations

import pytest

from app.core.clients.claude_sidecar import ClaudeSidecarError, ClaudeSidecarUnavailableError, SidecarModel

pytestmark = pytest.mark.integration


class _FakeSidecarClient:
    error: Exception | None = None
    models = [SidecarModel(id="claude-sonnet", created=123, owned_by="anthropic")]

    def __init__(self, _config) -> None:
        pass

    async def list_models(self):
        if self.error is not None:
            raise self.error
        return list(self.models)

    async def list_models_cached(self):
        return await self.list_models()


@pytest.mark.asyncio
async def test_sidecar_status_reports_disabled_and_missing_api_key(async_client):
    response = await async_client.get("/api/claude-sidecar/status")
    assert response.status_code == 200
    assert response.json()["status"] == "disabled"

    response = await async_client.put("/api/settings", json={"claudeSidecarEnabled": True})
    assert response.status_code == 200

    response = await async_client.get("/api/claude-sidecar/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "missing_api_key"
    assert payload["configured"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (ClaudeSidecarUnavailableError("connection refused"), "unreachable"),
        (ClaudeSidecarError(401, "bad key"), "unauthorized"),
        (ClaudeSidecarError(500, "sidecar exploded"), "error"),
    ],
)
async def test_sidecar_test_connection_records_error_statuses(async_client, monkeypatch, error, expected_status):
    monkeypatch.setattr("app.modules.claude_sidecar.service.ClaudeSidecarClient", _FakeSidecarClient)
    _FakeSidecarClient.error = error
    response = await async_client.put(
        "/api/settings",
        json={
            "claudeSidecarEnabled": True,
            "claudeSidecarApiKey": "sidecar-key",
        },
    )
    assert response.status_code == 200

    response = await async_client.post("/api/claude-sidecar/test")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == expected_status
    assert payload["modelCount"] is None

    status = await async_client.get("/api/claude-sidecar/status")
    assert status.status_code == 200
    assert status.json()["status"] == expected_status


@pytest.mark.asyncio
async def test_sidecar_test_connection_records_healthy_and_lists_models(async_client, monkeypatch):
    monkeypatch.setattr("app.modules.claude_sidecar.service.ClaudeSidecarClient", _FakeSidecarClient)
    _FakeSidecarClient.error = None
    _FakeSidecarClient.models = [SidecarModel(id="claude-sonnet", created=123, owned_by="anthropic")]
    response = await async_client.put(
        "/api/settings",
        json={
            "claudeSidecarEnabled": True,
            "claudeSidecarApiKey": "sidecar-key",
        },
    )
    assert response.status_code == 200

    response = await async_client.post("/api/claude-sidecar/test")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "healthy"
    assert payload["modelCount"] == 1
    assert payload["models"] == [{"id": "claude-sonnet", "created": 123, "ownedBy": "anthropic"}]

    response = await async_client.get("/api/claude-sidecar/models")
    assert response.status_code == 200
    assert response.json()["models"] == [{"id": "claude-sonnet", "created": 123, "ownedBy": "anthropic"}]
