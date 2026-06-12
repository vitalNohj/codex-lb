from __future__ import annotations

import pytest

from app.core.clients.claude_sidecar import SidecarModel
from app.core.clients.omniroute_sidecar import OmniRouteSidecarError, OmniRouteSidecarUnavailableError

pytestmark = pytest.mark.integration


class _FakeOmniRouteClient:
    error: Exception | None = None
    models = [SidecarModel(id="omniroute/test-chat", created=123, owned_by="omniroute")]

    def __init__(self, _config) -> None:
        pass

    async def list_models(self):
        if self.error is not None:
            raise self.error
        return list(self.models)

    async def list_models_cached(self):
        return await self.list_models()


@pytest.mark.asyncio
async def test_omniroute_sidecar_status_reports_disabled_and_missing_api_key(async_client):
    response = await async_client.put(
        "/api/settings",
        json={
            "omnirouteSidecarEnabled": False,
            "omnirouteSidecarClearApiKey": True,
        },
    )
    assert response.status_code == 200

    response = await async_client.get("/api/omniroute-sidecar/status")
    assert response.status_code == 200
    assert response.json()["status"] == "disabled"

    response = await async_client.put(
        "/api/settings",
        json={
            "omnirouteSidecarEnabled": True,
            "omnirouteSidecarClearApiKey": True,
        },
    )
    assert response.status_code == 200

    response = await async_client.get("/api/omniroute-sidecar/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "missing_api_key"
    assert payload["configured"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (OmniRouteSidecarUnavailableError("connection refused"), "unreachable"),
        (OmniRouteSidecarError(401, "bad key"), "unauthorized"),
        (OmniRouteSidecarError(500, "sidecar exploded"), "error"),
    ],
)
async def test_omniroute_sidecar_test_connection_records_error_statuses(
    async_client,
    monkeypatch,
    error,
    expected_status,
):
    monkeypatch.setattr("app.modules.omniroute_sidecar.service.OmniRouteSidecarClient", _FakeOmniRouteClient)
    _FakeOmniRouteClient.error = error
    response = await async_client.put(
        "/api/settings",
        json={
            "omnirouteSidecarEnabled": True,
            "omnirouteSidecarApiKey": "omniroute-key",
        },
    )
    assert response.status_code == 200

    response = await async_client.post("/api/omniroute-sidecar/test")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == expected_status
    assert payload["modelCount"] is None

    status = await async_client.get("/api/omniroute-sidecar/status")
    assert status.status_code == 200
    assert status.json()["status"] == expected_status


@pytest.mark.asyncio
async def test_omniroute_sidecar_test_connection_records_healthy_and_lists_models(async_client, monkeypatch):
    monkeypatch.setattr("app.modules.omniroute_sidecar.service.OmniRouteSidecarClient", _FakeOmniRouteClient)
    _FakeOmniRouteClient.error = None
    _FakeOmniRouteClient.models = [SidecarModel(id="omniroute/test-chat", created=123, owned_by="omniroute")]
    response = await async_client.put(
        "/api/settings",
        json={
            "omnirouteSidecarEnabled": True,
            "omnirouteSidecarApiKey": "omniroute-key",
        },
    )
    assert response.status_code == 200

    response = await async_client.post("/api/omniroute-sidecar/test")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "healthy"
    assert payload["modelCount"] == 1
    assert payload["models"] == [{"id": "omniroute/test-chat", "created": 123, "ownedBy": "omniroute"}]

    response = await async_client.get("/api/omniroute-sidecar/models")
    assert response.status_code == 200
    assert response.json()["models"] == [{"id": "omniroute/test-chat", "created": 123, "ownedBy": "omniroute"}]
