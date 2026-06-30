from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.clients.claude_sidecar import ClaudeSidecarError, ClaudeSidecarUnavailableError, SidecarModel
from app.db.models import ClaudeSidecarUsageEvent
from app.db.session import SessionLocal
from app.modules.claude_sidecar.quota import (
    SidecarAuthQuota,
    SidecarModelQuota,
    SidecarQuotaSnapshot,
    snapshot_to_json,
)
from app.modules.settings.repository import SettingsRepository

pytestmark = pytest.mark.integration


class _FakeSidecarClient:
    error: Exception | None = None
    models = [SidecarModel(id="claude-sonnet", created=123, owned_by="anthropic")]
    routing_strategy = "fill-first"
    auth_files = [
        {
            "name": "claude-a@example.com.json",
            "auth_index": "0",
            "provider": "claude",
            "email": "a@example.com",
        },
        {
            "name": "claude-b@example.com.json",
            "auth_index": "1",
            "provider": "claude",
            "email": "b@example.com",
            "priority": 10,
        },
    ]
    strategy_updates: list[str] = []
    priority_updates: list[tuple[str, int]] = []

    def __init__(self, _config) -> None:
        pass

    async def list_models(self):
        if self.error is not None:
            raise self.error
        return list(self.models)

    async def list_models_cached(self):
        return await self.list_models()

    async def get_routing_strategy(self):
        if self.error is not None:
            raise self.error
        return self.routing_strategy

    async def set_routing_strategy(self, value: str):
        if self.error is not None:
            raise self.error
        self.__class__.strategy_updates.append(value)
        self.__class__.routing_strategy = value
        return value

    async def list_auth_files(self):
        if self.error is not None:
            raise self.error
        return list(self.auth_files)

    async def patch_auth_file_priority(self, name: str, priority: int):
        if self.error is not None:
            raise self.error
        self.__class__.priority_updates.append((name, priority))


def _reset_fake_sidecar_client() -> None:
    _FakeSidecarClient.error = None
    _FakeSidecarClient.models = [SidecarModel(id="claude-sonnet", created=123, owned_by="anthropic")]
    _FakeSidecarClient.routing_strategy = "fill-first"
    _FakeSidecarClient.auth_files = [
        {
            "name": "claude-a@example.com.json",
            "auth_index": "0",
            "provider": "claude",
            "email": "a@example.com",
        },
        {
            "name": "claude-b@example.com.json",
            "auth_index": "1",
            "provider": "claude",
            "email": "b@example.com",
            "priority": 10,
        },
    ]
    _FakeSidecarClient.strategy_updates = []
    _FakeSidecarClient.priority_updates = []


@pytest.mark.asyncio
async def test_sidecar_status_reports_disabled_and_missing_api_key(async_client):
    response = await async_client.put(
        "/api/settings",
        json={
            "claudeSidecarEnabled": False,
            "claudeSidecarClearApiKey": True,
        },
    )
    assert response.status_code == 200

    response = await async_client.get("/api/claude-sidecar/status")
    assert response.status_code == 200
    assert response.json()["status"] == "disabled"

    response = await async_client.put(
        "/api/settings",
        json={
            "claudeSidecarEnabled": True,
            "claudeSidecarClearApiKey": True,
        },
    )
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


@pytest.mark.asyncio
async def test_sidecar_quota_endpoint_reports_disabled_then_unknown_then_snapshot(async_client):
    response = await async_client.put(
        "/api/settings",
        json={
            "claudeSidecarEnabled": False,
            "claudeSidecarClearApiKey": True,
            "claudeSidecarClearManagementKey": True,
        },
    )
    assert response.status_code == 200

    response = await async_client.get("/api/claude-sidecar/quota")
    assert response.status_code == 200
    assert response.json()["status"] == "disabled"

    response = await async_client.put(
        "/api/settings",
        json={
            "claudeSidecarEnabled": True,
            "claudeSidecarApiKey": "sidecar-key",
        },
    )
    assert response.status_code == 200

    response = await async_client.get("/api/claude-sidecar/quota")
    assert response.status_code == 200
    assert response.json()["status"] == "not_configured"

    response = await async_client.put(
        "/api/settings",
        json={
            "claudeSidecarManagementKey": "mgmt-key",
            "claudeSidecarAuthPlans": [
                {
                    "authIndex": "0",
                    "email": "claude@example.com",
                    "planType": "custom",
                    "primaryTokenBudget": 100,
                    "secondaryTokenBudget": 700,
                }
            ],
        },
    )
    assert response.status_code == 200

    response = await async_client.get("/api/claude-sidecar/quota")
    assert response.status_code == 200
    assert response.json()["status"] == "unknown"

    checked_at = datetime(2026, 6, 10, 12, 0, 0, tzinfo=timezone.utc)
    snapshot = SidecarQuotaSnapshot(
        checked_at=checked_at,
        status="healthy",
        message=None,
        accounts=(
            SidecarAuthQuota(
                name="claude-1",
                auth_index="0",
                email="claude@example.com",
                status="active",
                status_message=None,
                disabled=False,
                unavailable=False,
                quota_exceeded=True,
                next_recover_at=datetime(2026, 6, 10, 17, 0, 0, tzinfo=timezone.utc),
                model_states=(
                    SidecarModelQuota(
                        model="claude-opus-4",
                        quota_exceeded=True,
                        next_recover_at=datetime(2026, 6, 10, 17, 0, 0, tzinfo=timezone.utc),
                    ),
                ),
                success=4,
                failed=1,
                last_refresh=None,
            ),
        ),
    )
    async with SessionLocal() as session:
        repo = SettingsRepository(session)
        await repo.update(
            claude_sidecar_quota_state_json=snapshot_to_json(snapshot),
            claude_sidecar_quota_checked_at=checked_at.replace(tzinfo=None),
        )
        session.add(
            ClaudeSidecarUsageEvent(
                request_id="quota-claude-usage-1",
                timestamp=datetime.now(timezone.utc) - timedelta(minutes=30),
                auth_index="0",
                source="claude@example.com",
                provider="claude",
                model="claude-sonnet",
                alias="claude",
                endpoint="POST /v1/chat/completions",
                auth_type="oauth",
                total_tokens=25,
                input_tokens=10,
                output_tokens=15,
                reasoning_tokens=0,
                cached_tokens=0,
                failed=False,
            )
        )
        await session.commit()

    response = await async_client.get("/api/claude-sidecar/quota")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "healthy"
    assert payload["checkedAt"] == "2026-06-10T12:00:00Z"
    assert len(payload["accounts"]) == 1
    account = payload["accounts"][0]
    assert account["email"] == "claude@example.com"
    assert account["quotaExceeded"] is True
    assert account["modelsExceeded"] == ["claude-opus-4"]
    assert account["nextRecoverAt"] == "2026-06-10T17:00:00Z"
    assert account["authIndex"] == "0"
    assert account["planType"] == "custom"
    assert account["primaryRemainingPercent"] == 0.0
    assert account["secondaryRemainingPercent"] == pytest.approx(96.428571)
    assert account["primaryUsedTokens"] == 25
    assert account["primaryTokenBudget"] == 100
    assert account["confidence"] == "estimated"


@pytest.mark.asyncio
async def test_sidecar_routing_endpoint_reports_disabled_then_not_configured_then_healthy(async_client, monkeypatch):
    monkeypatch.setattr("app.modules.claude_sidecar.service.ClaudeSidecarClient", _FakeSidecarClient)
    _reset_fake_sidecar_client()

    response = await async_client.put(
        "/api/settings",
        json={
            "claudeSidecarEnabled": False,
            "claudeSidecarClearApiKey": True,
            "claudeSidecarClearManagementKey": True,
        },
    )
    assert response.status_code == 200

    response = await async_client.get("/api/claude-sidecar/routing")
    assert response.status_code == 200
    assert response.json()["status"] == "disabled"

    response = await async_client.put(
        "/api/settings",
        json={
            "claudeSidecarEnabled": True,
            "claudeSidecarApiKey": "sidecar-key",
        },
    )
    assert response.status_code == 200

    response = await async_client.get("/api/claude-sidecar/routing")
    assert response.status_code == 200
    assert response.json()["status"] == "not_configured"

    response = await async_client.put(
        "/api/settings",
        json={"claudeSidecarManagementKey": "mgmt-key"},
    )
    assert response.status_code == 200

    response = await async_client.get("/api/claude-sidecar/routing")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "healthy"
    assert payload["strategy"] == "fill_first"
    assert payload["accounts"] == [
        {
            "name": "claude-a@example.com.json",
            "authIndex": "0",
            "email": "a@example.com",
            "priority": 0,
        },
        {
            "name": "claude-b@example.com.json",
            "authIndex": "1",
            "email": "b@example.com",
            "priority": 10,
        },
    ]


@pytest.mark.asyncio
async def test_put_routing_strategy_round_trips(async_client, monkeypatch):
    monkeypatch.setattr("app.modules.claude_sidecar.service.ClaudeSidecarClient", _FakeSidecarClient)
    _reset_fake_sidecar_client()
    response = await async_client.put(
        "/api/settings",
        json={
            "claudeSidecarEnabled": True,
            "claudeSidecarApiKey": "sidecar-key",
            "claudeSidecarManagementKey": "mgmt-key",
        },
    )
    assert response.status_code == 200

    response = await async_client.put(
        "/api/claude-sidecar/routing/strategy",
        json={"strategy": "round_robin"},
    )

    assert response.status_code == 200
    assert _FakeSidecarClient.strategy_updates == ["round-robin"]
    assert response.json()["strategy"] == "round_robin"


@pytest.mark.asyncio
async def test_put_routing_strategy_rejects_invalid(async_client, monkeypatch):
    monkeypatch.setattr("app.modules.claude_sidecar.service.ClaudeSidecarClient", _FakeSidecarClient)
    _reset_fake_sidecar_client()
    response = await async_client.put(
        "/api/settings",
        json={
            "claudeSidecarEnabled": True,
            "claudeSidecarApiKey": "sidecar-key",
            "claudeSidecarManagementKey": "mgmt-key",
        },
    )
    assert response.status_code == 200

    response = await async_client.put(
        "/api/claude-sidecar/routing/strategy",
        json={"strategy": "bogus"},
    )

    assert response.status_code == 422
    assert _FakeSidecarClient.strategy_updates == []


@pytest.mark.asyncio
async def test_put_routing_priority_round_trips(async_client, monkeypatch):
    monkeypatch.setattr("app.modules.claude_sidecar.service.ClaudeSidecarClient", _FakeSidecarClient)
    _reset_fake_sidecar_client()
    response = await async_client.put(
        "/api/settings",
        json={
            "claudeSidecarEnabled": True,
            "claudeSidecarApiKey": "sidecar-key",
            "claudeSidecarManagementKey": "mgmt-key",
        },
    )
    assert response.status_code == 200

    response = await async_client.put(
        "/api/claude-sidecar/routing/priority",
        json={"name": "claude-a@example.com.json", "priority": 100},
    )

    assert response.status_code == 200
    assert _FakeSidecarClient.priority_updates == [("claude-a@example.com.json", 100)]
    assert response.json()["status"] == "healthy"
