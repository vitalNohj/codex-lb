from __future__ import annotations

import pytest

from app.core.clients.claude_sidecar import SidecarModel
from app.core.clients.orcarouter_sidecar import OrcaRouterSidecarError, OrcaRouterSidecarUnavailableError

pytestmark = pytest.mark.integration


class _FakeOrcaRouterClient:
    error: Exception | None = None
    models = [SidecarModel(id="orcarouter/auto", created=123, owned_by="deepseek")]

    def __init__(self, _config) -> None:
        pass

    async def list_models(self):
        if self.error is not None:
            raise self.error
        return list(self.models)

    async def list_models_cached(self):
        return await self.list_models()


@pytest.mark.asyncio
async def test_orcarouter_sidecar_status_reports_disabled_and_missing_api_key(async_client):
    response = await async_client.put(
        "/api/settings",
        json={
            "orcarouterSidecarEnabled": False,
            "orcarouterSidecarClearApiKey": True,
        },
    )
    assert response.status_code == 200

    response = await async_client.get("/api/orcarouter-sidecar/status")
    assert response.status_code == 200
    assert response.json()["status"] == "disabled"

    response = await async_client.put(
        "/api/settings",
        json={
            "orcarouterSidecarEnabled": True,
            "orcarouterSidecarClearApiKey": True,
        },
    )
    assert response.status_code == 200

    response = await async_client.get("/api/orcarouter-sidecar/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "missing_api_key"
    assert payload["configured"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (OrcaRouterSidecarUnavailableError("connection refused"), "unreachable"),
        (OrcaRouterSidecarError(401, "bad key"), "unauthorized"),
        (OrcaRouterSidecarError(500, "sidecar exploded"), "error"),
    ],
)
async def test_orcarouter_sidecar_test_connection_records_error_statuses(
    async_client,
    monkeypatch,
    error,
    expected_status,
):
    monkeypatch.setattr("app.modules.orcarouter_sidecar.service.OrcaRouterSidecarClient", _FakeOrcaRouterClient)
    _FakeOrcaRouterClient.error = error
    response = await async_client.put(
        "/api/settings",
        json={
            "orcarouterSidecarEnabled": True,
            "orcarouterSidecarApiKey": "orcarouter-key",
        },
    )
    assert response.status_code == 200

    response = await async_client.post("/api/orcarouter-sidecar/test")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == expected_status
    assert payload["modelCount"] is None

    status = await async_client.get("/api/orcarouter-sidecar/status")
    assert status.status_code == 200
    assert status.json()["status"] == expected_status


@pytest.mark.asyncio
async def test_orcarouter_sidecar_test_connection_records_healthy_and_lists_models(async_client, monkeypatch):
    monkeypatch.setattr("app.modules.orcarouter_sidecar.service.OrcaRouterSidecarClient", _FakeOrcaRouterClient)
    _FakeOrcaRouterClient.error = None
    _FakeOrcaRouterClient.models = [
        SidecarModel(id="orcarouter/auto", created=123, owned_by="deepseek")
    ]
    response = await async_client.put(
        "/api/settings",
        json={
            "orcarouterSidecarEnabled": True,
            "orcarouterSidecarApiKey": "orcarouter-key",
        },
    )
    assert response.status_code == 200

    response = await async_client.post("/api/orcarouter-sidecar/test")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "healthy"
    assert payload["modelCount"] == 1
    assert payload["models"] == [{"id": "orcarouter/auto", "created": 123, "ownedBy": "deepseek"}]

    response = await async_client.get("/api/orcarouter-sidecar/models")
    assert response.status_code == 200
    assert response.json()["models"] == [{"id": "orcarouter/auto", "created": 123, "ownedBy": "deepseek"}]


# Not a real credential: a synthetic string shaped like an OrcaRouter key so the
# assertion below proves the sanitizer removed it.
_FAKE_ORCAROUTER_KEY = "sk-orca-NOTAREALKEY000000000"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "upstream_message",
    [
        "Unauthorized for Authorization: Bearer {key}",
        "rejected header bearer {key}",
        'upstream echoed {{"authorization":"Bearer {key}"}}',
        "BEARER  {key}!",
        "Invalid API key: {key}",
    ],
)
async def test_orcarouter_test_connection_never_persists_the_bearer_token(
    async_client,
    monkeypatch,
    upstream_message,
):
    """An upstream that echoes the Authorization header must not leak the key.

    ``test_connection`` writes this message to
    ``orcarouter_sidecar_last_health_message`` and the dashboard renders it, so a
    surviving token would be visible to every dashboard viewer and durable in the
    database.
    """

    monkeypatch.setattr("app.modules.orcarouter_sidecar.service.OrcaRouterSidecarClient", _FakeOrcaRouterClient)
    _FakeOrcaRouterClient.error = OrcaRouterSidecarError(401, upstream_message.format(key=_FAKE_ORCAROUTER_KEY))

    response = await async_client.put(
        "/api/settings",
        json={
            "orcarouterSidecarEnabled": True,
            "orcarouterSidecarApiKey": _FAKE_ORCAROUTER_KEY,
        },
    )
    assert response.status_code == 200

    test_payload = (await async_client.post("/api/orcarouter-sidecar/test")).json()
    assert test_payload["status"] == "unauthorized"
    assert _FAKE_ORCAROUTER_KEY not in test_payload["message"]
    assert "[redacted]" in test_payload["message"]

    # The persisted column is replayed by the status endpoint on every load.
    status_payload = (await async_client.get("/api/orcarouter-sidecar/status")).json()
    assert _FAKE_ORCAROUTER_KEY not in status_payload["message"]

    from sqlalchemy import select

    from app.db.models import DashboardSettings
    from app.db.session import SessionLocal

    async with SessionLocal() as session:
        stored = (await session.execute(select(DashboardSettings.orcarouter_sidecar_last_health_message))).scalar_one()
    assert _FAKE_ORCAROUTER_KEY not in str(stored)
