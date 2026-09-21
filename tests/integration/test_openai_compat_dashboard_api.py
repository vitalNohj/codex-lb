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
    monkeypatch.setattr(
        "app.modules.openai_compat.service.get_openai_compat_sidecar_client",
        _FakeOpenAICompatClient,
    )
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
    monkeypatch.setattr(
        "app.modules.openai_compat.service.get_openai_compat_sidecar_client",
        _FakeOpenAICompatClient,
    )
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


@pytest.mark.asyncio
async def test_a_concurrent_endpoint_edit_is_not_reverted_by_a_health_write(async_client, monkeypatch):
    """Two overlapping writers to one shared JSON blob must both survive.

    ``openai_compat_endpoints_json`` holds every endpoint's *configuration* as
    well as its health, so recording a test result used to rewrite the whole blob
    from a stale read - silently reverting whatever landed in between. Reported on
    https://github.com/vitalNohj/codex-lb/pull/59, and reachable with no unusual
    timing: each dashboard endpoint card has its own Test button, and an operator
    save is an independent request.

    The interfering write is injected between this caller's read and its write,
    which is exactly the window the compare-and-set closes.
    """

    import json as _json

    from sqlalchemy import select as _select

    from app.db.models import DashboardSettings as _DashboardSettings
    from app.db.session import SessionLocal as _SessionLocal
    from app.modules.settings import repository as settings_repository_module

    monkeypatch.setattr(
        "app.modules.openai_compat.service.get_openai_compat_sidecar_client",
        _FakeOpenAICompatClient,
    )
    _FakeOpenAICompatClient.error = None
    await _put_endpoint(async_client, apiKey="vast-key")

    races: list[int] = []
    original = settings_repository_module.SettingsRepository.update_operational_json_column_if_unchanged

    async def _racing_write(self, column, *, expected, value):
        if not races:
            races.append(1)
            # Another writer commits a CONFIGURATION change to the same blob
            # between this caller's read and its write.
            async with _SessionLocal() as other:
                row = (await other.execute(_select(_DashboardSettings))).scalar_one()
                blob = _json.loads(row.openai_compat_endpoints_json or "[]")
                blob[0]["name"] = "Renamed By Operator"
                row.openai_compat_endpoints_json = _json.dumps(blob, separators=(",", ":"))
                await other.commit()
        return await original(self, column, expected=expected, value=value)

    monkeypatch.setattr(
        settings_repository_module.SettingsRepository,
        "update_operational_json_column_if_unchanged",
        _racing_write,
    )

    response = await async_client.post(f"/api/openai-compat/{ENDPOINT_ID}/test")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    assert races == [1], "the racing write must have been triggered"

    after = await async_client.get("/api/settings")
    assert after.status_code == 200
    endpoint = after.json()["openaiCompatEndpoints"][0]
    # BOTH survive: the retry re-applied this health result on top of the
    # operator's committed rename instead of overwriting it with a stale read.
    assert endpoint["name"] == "Renamed By Operator"
    status = await async_client.get(f"/api/openai-compat/{ENDPOINT_ID}/status")
    assert status.status_code == 200
    assert status.json()["status"] == "healthy"


@pytest.mark.asyncio
async def test_two_endpoints_tested_in_sequence_both_keep_their_health(async_client, monkeypatch):
    """Recording one endpoint's health must not erase another's.

    Both live in the same JSON blob, so a whole-blob write from a read taken
    before the other endpoint's result would drop it.
    """

    other_id = "3d0c9e4b-2f5e-4c8b-8d22-8b1f5e3c2d1b"
    payload = [
        {**ENDPOINT, "apiKey": "vast-key"},
        {
            **ENDPOINT,
            "id": other_id,
            "name": "vLLM",
            "baseUrl": "https://vllm.internal/v1",
            "fullModels": ["meta/llama-3.1-8b"],
            "apiKey": "vllm-key",
        },
    ]
    response = await async_client.put("/api/settings", json={"openaiCompatEndpoints": payload})
    assert response.status_code == 200, response.text

    monkeypatch.setattr(
        "app.modules.openai_compat.service.get_openai_compat_sidecar_client",
        _FakeOpenAICompatClient,
    )

    _FakeOpenAICompatClient.error = OpenAICompatSidecarError(401, "bad key")
    first = await async_client.post(f"/api/openai-compat/{ENDPOINT_ID}/test")
    assert first.status_code == 200
    assert first.json()["status"] == "unauthorized"

    _FakeOpenAICompatClient.error = None
    second = await async_client.post(f"/api/openai-compat/{other_id}/test")
    assert second.status_code == 200
    assert second.json()["status"] == "healthy"

    # The first endpoint's recorded failure is still there.
    first_status = await async_client.get(f"/api/openai-compat/{ENDPOINT_ID}/status")
    assert first_status.status_code == 200
    assert first_status.json()["status"] == "unauthorized"
    second_status = await async_client.get(f"/api/openai-compat/{other_id}/status")
    assert second_status.status_code == 200
    assert second_status.json()["status"] == "healthy"
