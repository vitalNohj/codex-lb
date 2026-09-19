from __future__ import annotations

import pytest

from app.core.clients.claude_sidecar import SidecarModel
from app.core.clients.openai_compat_sidecar import OpenAICompatSidecarError, OpenAICompatSidecarUnavailableError

pytestmark = pytest.mark.integration

ENDPOINT_ID = "2c9b8f3a-1e4d-4b7a-9c11-7a0e4d2b1c0a"
ENDPOINT = {
    "id": ENDPOINT_ID,
    "name": "Vast",
    "enabled": True,
    "baseUrl": "https://openai.vast.ai/demo/v1",
    "modelPrefixes": [],
    "fullModels": ["Qwen/Qwen2.5-7B"],
    "connectTimeoutSeconds": 8,
    "requestTimeoutSeconds": 600,
    "modelsCacheTtlSeconds": 60,
}


class _FakeOpenAICompatClient:
    error: Exception | None = None
    models = [SidecarModel(id="Qwen/Qwen2.5-7B", created=123, owned_by="openai_compat")]

    def __init__(self, _config) -> None:
        pass

    async def list_models(self):
        if self.error is not None:
            raise self.error
        return list(self.models)

    async def list_models_cached(self):
        return await self.list_models()


async def _put_endpoint(async_client, **overrides):
    payload = {**ENDPOINT, **overrides}
    response = await async_client.put("/api/settings", json={"openaiCompatEndpoints": [payload]})
    assert response.status_code == 200, response.text
    return response


@pytest.mark.asyncio
async def test_openai_compat_status_is_never_missing_api_key(async_client):
    await _put_endpoint(async_client, enabled=False)

    response = await async_client.get(f"/api/openai-compat/{ENDPOINT_ID}/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "disabled"
    assert payload["configured"] is True
    assert payload["status"] != "missing_api_key"
    assert "apiKey" not in payload

    await _put_endpoint(async_client, enabled=True)

    response = await async_client.get(f"/api/openai-compat/{ENDPOINT_ID}/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["configured"] is True
    assert payload["status"] != "missing_api_key"
    assert "apiKey" not in payload


@pytest.mark.asyncio
async def test_openai_compat_unknown_endpoint_returns_404(async_client):
    response = await async_client.get("/api/openai-compat/00000000-0000-4000-8000-000000000001/status")
    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (OpenAICompatSidecarUnavailableError("connection refused"), "unreachable"),
        (OpenAICompatSidecarError(401, "bad key"), "unauthorized"),
        (OpenAICompatSidecarError(500, "sidecar exploded"), "error"),
    ],
)
async def test_openai_compat_test_connection_records_error_statuses(
    async_client,
    monkeypatch,
    error,
    expected_status,
):
    monkeypatch.setattr("app.modules.openai_compat.service.OpenAICompatSidecarClient", _FakeOpenAICompatClient)
    _FakeOpenAICompatClient.error = error
    await _put_endpoint(async_client)

    response = await async_client.post(f"/api/openai-compat/{ENDPOINT_ID}/test")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == expected_status
    assert payload["modelCount"] is None
    assert payload["configured"] is True

    status = await async_client.get(f"/api/openai-compat/{ENDPOINT_ID}/status")
    assert status.status_code == 200
    assert status.json()["status"] == expected_status


@pytest.mark.asyncio
async def test_openai_compat_test_connection_records_healthy_without_bumping_version(
    async_client, monkeypatch
):
    monkeypatch.setattr("app.modules.openai_compat.service.OpenAICompatSidecarClient", _FakeOpenAICompatClient)
    _FakeOpenAICompatClient.error = None
    _FakeOpenAICompatClient.models = [
        SidecarModel(id="Qwen/Qwen2.5-7B", created=123, owned_by="openai_compat")
    ]
    settings = await _put_endpoint(async_client, apiKey="vast-key")
    version = settings.json()["version"]

    response = await async_client.post(f"/api/openai-compat/{ENDPOINT_ID}/test")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "healthy"
    assert payload["modelCount"] == 1
    assert payload["models"] == [{"id": "Qwen/Qwen2.5-7B", "created": 123, "ownedBy": "openai_compat"}]
    assert "apiKey" not in payload

    models = await async_client.get(f"/api/openai-compat/{ENDPOINT_ID}/models")
    assert models.status_code == 200
    assert models.json()["models"] == [{"id": "Qwen/Qwen2.5-7B", "created": 123, "ownedBy": "openai_compat"}]

    after = await async_client.get("/api/settings")
    assert after.status_code == 200
    body = after.json()
    assert body["version"] == version
    endpoint = body["openaiCompatEndpoints"][0]
    assert endpoint["apiKeyConfigured"] is True
    assert "apiKey" not in endpoint
    assert "vast-key" not in after.text


@pytest.mark.asyncio
async def test_openai_compat_synthetic_account_uses_operator_name(async_client):
    await _put_endpoint(async_client)

    response = await async_client.get("/api/accounts")
    assert response.status_code == 200
    accounts = response.json()["accounts"]
    account = next(item for item in accounts if item["accountId"] == f"openai-compat-{ENDPOINT_ID}")
    assert account["displayName"] == "Vast"
    assert account["provider"] == "openai_compat"
    assert account["synthetic"] is True
    assert account["readOnly"] is True


@pytest.mark.asyncio
async def test_openai_compat_full_model_conflict_with_openrouter_is_rejected(async_client):
    response = await async_client.put(
        "/api/settings",
        json={
            "openrouterSidecarFullModels": ["z-ai/glm-5.3"],
            "openaiCompatEndpoints": [{**ENDPOINT, "fullModels": ["z-ai/glm-5.3"]}],
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "sidecar_routing_conflict"


@pytest.mark.asyncio
async def test_unrelated_settings_update_preserves_openai_compat_api_key(async_client):
    await _put_endpoint(async_client, apiKey="vast-key")

    response = await async_client.put("/api/settings", json={"dashboardSessionTtlSeconds": 7200})
    assert response.status_code == 200
    endpoint = response.json()["openaiCompatEndpoints"][0]
    assert endpoint["id"] == ENDPOINT_ID
    assert endpoint["apiKeyConfigured"] is True
    assert "apiKey" not in endpoint
    assert "vast-key" not in response.text
