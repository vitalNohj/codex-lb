from __future__ import annotations

import json
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
    disabled_updates: list[tuple[str, bool]] = []
    excluded_models_updates: list[tuple[str, list[str]]] = []

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

    async def patch_auth_file_disabled(self, name: str, disabled: bool):
        if self.error is not None:
            raise self.error
        self.__class__.disabled_updates.append((name, disabled))

    async def patch_auth_file_excluded_models(self, name: str, excluded_models: list[str]):
        if self.error is not None:
            raise self.error
        self.__class__.excluded_models_updates.append((name, list(excluded_models)))


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
            "disabled": True,
        },
    ]
    _FakeSidecarClient.strategy_updates = []
    _FakeSidecarClient.priority_updates = []
    _FakeSidecarClient.disabled_updates = []
    _FakeSidecarClient.excluded_models_updates = []


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
            "paused": False,
            "excludedModels": [],
            "excludedModelsState": "unreadable",
        },
        {
            "name": "claude-b@example.com.json",
            "authIndex": "1",
            "email": "b@example.com",
            "priority": 10,
            "paused": True,
            "excludedModels": [],
            "excludedModelsState": "unreadable",
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
async def test_get_routing_maps_weighted_round_robin(async_client, monkeypatch):
    monkeypatch.setattr("app.modules.claude_sidecar.service.ClaudeSidecarClient", _FakeSidecarClient)
    _reset_fake_sidecar_client()
    _FakeSidecarClient.routing_strategy = "weighted-round-robin"
    response = await async_client.put(
        "/api/settings",
        json={
            "claudeSidecarEnabled": True,
            "claudeSidecarApiKey": "sidecar-key",
            "claudeSidecarManagementKey": "mgmt-key",
        },
    )
    assert response.status_code == 200

    response = await async_client.get("/api/claude-sidecar/routing")

    assert response.status_code == 200
    assert response.json()["strategy"] == "weighted_round_robin"


@pytest.mark.asyncio
async def test_put_routing_strategy_weighted_round_robin_round_trips(async_client, monkeypatch):
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
        json={"strategy": "weighted_round_robin"},
    )

    assert response.status_code == 200
    assert _FakeSidecarClient.strategy_updates == ["weighted-round-robin"]
    assert response.json()["strategy"] == "weighted_round_robin"


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


@pytest.mark.asyncio
async def test_put_routing_paused_round_trips(async_client, monkeypatch):
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
        "/api/claude-sidecar/routing/paused",
        json={"name": "claude-a@example.com.json", "paused": True},
    )

    assert response.status_code == 200
    assert _FakeSidecarClient.disabled_updates == [("claude-a@example.com.json", True)]
    assert response.json()["status"] == "healthy"

    response = await async_client.put(
        "/api/claude-sidecar/routing/paused",
        json={"name": "claude-a@example.com.json", "paused": False},
    )

    assert response.status_code == 200
    assert _FakeSidecarClient.disabled_updates == [
        ("claude-a@example.com.json", True),
        ("claude-a@example.com.json", False),
    ]


@pytest.mark.asyncio
async def test_put_routing_paused_patches_stored_snapshot(async_client, monkeypatch):
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

    checked_at = datetime(2026, 6, 10, 12, 0, 0, tzinfo=timezone.utc)
    snapshot = SidecarQuotaSnapshot(
        checked_at=checked_at,
        status="healthy",
        message=None,
        accounts=(
            SidecarAuthQuota(
                name="claude-a@example.com.json",
                auth_index="0",
                email="a@example.com",
                status="active",
                status_message=None,
                disabled=False,
                unavailable=False,
                quota_exceeded=False,
                next_recover_at=None,
                model_states=(),
                success=0,
                failed=0,
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

    response = await async_client.put(
        "/api/claude-sidecar/routing/paused",
        json={"name": "claude-a@example.com.json", "paused": True},
    )
    assert response.status_code == 200

    # Dashboard reads `paused` from the stored snapshot; it must reflect the
    # change immediately without waiting for the next quota poll.
    response = await async_client.get("/api/claude-sidecar/quota")
    assert response.status_code == 200
    accounts = {acct["name"]: acct for acct in response.json()["accounts"]}
    assert accounts["claude-a@example.com.json"]["paused"] is True


@pytest.mark.asyncio
async def test_put_routing_paused_without_management_key(async_client, monkeypatch):
    monkeypatch.setattr("app.modules.claude_sidecar.service.ClaudeSidecarClient", _FakeSidecarClient)
    _reset_fake_sidecar_client()
    response = await async_client.put(
        "/api/settings",
        json={
            "claudeSidecarEnabled": True,
            "claudeSidecarApiKey": "sidecar-key",
            "claudeSidecarClearManagementKey": True,
        },
    )
    assert response.status_code == 200

    response = await async_client.put(
        "/api/claude-sidecar/routing/paused",
        json={"name": "claude-a@example.com.json", "paused": True},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "not_configured"
    assert _FakeSidecarClient.disabled_updates == []


@pytest.mark.asyncio
@pytest.mark.parametrize("read_fails", [False, True])
async def test_put_routing_excluded_models_round_trips(async_client, monkeypatch, read_fails):
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
        "/api/claude-sidecar/routing/excluded-models",
        json={
            "name": "claude-a@example.com.json",
            "excludedModels": ["claude-demo-*", "claude-other-5*"],
        },
    )

    assert response.status_code == 200
    assert _FakeSidecarClient.excluded_models_updates == [
        ("claude-a@example.com.json", ["claude-demo-*", "claude-other-5*"])
    ]
    assert response.json()["savedAccount"]["excludedModels"] == ["claude-demo-*", "claude-other-5*"]
    assert response.json()["savedAccount"]["excludedModelsState"] == "available"
    if read_fails:
        async def fail_read(self):
            raise ClaudeSidecarUnavailableError("connection refused")
        monkeypatch.setattr(_FakeSidecarClient, "get_routing_strategy", fail_read)
    assert response.json()["status"] == "healthy"

    response = await async_client.put(
        "/api/claude-sidecar/routing/excluded-models",
        json={"name": "claude-a@example.com.json", "excludedModels": []},
    )

    assert response.status_code == 200
    assert _FakeSidecarClient.excluded_models_updates[-1] == ("claude-a@example.com.json", [])
    assert response.json()["status"] == ("unreachable" if read_fails else "healthy")
    assert response.json()["savedAccount"]["excludedModels"] == []
    assert response.json()["savedAccount"]["excludedModelsState"] == "available"


@pytest.mark.asyncio
async def test_put_routing_excluded_models_normalizes_patterns(async_client, monkeypatch):
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
        "/api/claude-sidecar/routing/excluded-models",
        json={
            "name": "claude-a@example.com.json",
            "excludedModels": ["  claude-demo-* ", "CLAUDE-DEMO-*", "", "bad\nvalue"],
        },
    )

    assert response.status_code == 200
    assert _FakeSidecarClient.excluded_models_updates == [
        ("claude-a@example.com.json", ["claude-demo-*"])
    ]


@pytest.mark.asyncio
async def test_get_routing_reports_excluded_models(async_client, monkeypatch):
    monkeypatch.setattr("app.modules.claude_sidecar.service.ClaudeSidecarClient", _FakeSidecarClient)
    _reset_fake_sidecar_client()
    _FakeSidecarClient.auth_files = [
        {
            "name": "claude-a@example.com.json",
            "auth_index": "0",
            "provider": "claude",
            "email": "a@example.com",
            "excluded_models": ["claude-demo-*"],
        },
        {
            "name": "claude-b@example.com.json",
            "auth_index": "1",
            "provider": "claude",
            "email": "b@example.com",
        },
    ]
    response = await async_client.put(
        "/api/settings",
        json={
            "claudeSidecarEnabled": True,
            "claudeSidecarApiKey": "sidecar-key",
            "claudeSidecarManagementKey": "mgmt-key",
        },
    )
    assert response.status_code == 200

    response = await async_client.get("/api/claude-sidecar/routing")

    assert response.status_code == 200
    accounts = {acct["name"]: acct for acct in response.json()["accounts"]}
    assert accounts["claude-a@example.com.json"]["excludedModels"] == ["claude-demo-*"]
    assert accounts["claude-a@example.com.json"]["excludedModelsState"] == "available"
    # b carries neither the field nor a readable auth file: an unreadable list is
    # not an empty one, so the editor must be locked instead of offering an empty
    # list the operator could save back over real exclusions.
    assert accounts["claude-b@example.com.json"]["excludedModels"] == []
    assert accounts["claude-b@example.com.json"]["excludedModelsState"] == "unreadable"


@pytest.mark.asyncio
async def test_get_routing_marks_empty_auth_file_list_available(async_client, monkeypatch, tmp_path):
    monkeypatch.setattr("app.modules.claude_sidecar.service.ClaudeSidecarClient", _FakeSidecarClient)
    monkeypatch.setattr(
        "app.modules.claude_sidecar.excluded_models.default_auth_dir",
        lambda: tmp_path,
    )
    _reset_fake_sidecar_client()
    auth_path = tmp_path / "claude-a@example.com.json"
    auth_path.write_text(json.dumps({"email": "a@example.com"}), encoding="utf-8")
    _FakeSidecarClient.auth_files = [
        {
            "name": "claude-a@example.com.json",
            "auth_index": "0",
            "provider": "claude",
            "email": "a@example.com",
            "path": str(auth_path),
        },
    ]
    response = await async_client.put(
        "/api/settings",
        json={
            "claudeSidecarEnabled": True,
            "claudeSidecarApiKey": "sidecar-key",
            "claudeSidecarManagementKey": "mgmt-key",
        },
    )
    assert response.status_code == 200

    response = await async_client.get("/api/claude-sidecar/routing")

    assert response.status_code == 200
    account = response.json()["accounts"][0]
    assert account["excludedModels"] == []
    assert account["excludedModelsState"] == "available"


@pytest.mark.asyncio
async def test_get_routing_flags_unreadable_auth_file(async_client, monkeypatch, tmp_path):
    monkeypatch.setattr("app.modules.claude_sidecar.service.ClaudeSidecarClient", _FakeSidecarClient)
    monkeypatch.setattr(
        "app.modules.claude_sidecar.excluded_models.default_auth_dir",
        lambda: tmp_path,
    )
    _reset_fake_sidecar_client()
    _FakeSidecarClient.auth_files = [
        {
            "name": "claude-a@example.com.json",
            "auth_index": "0",
            "provider": "claude",
            "email": "a@example.com",
            "path": "/elsewhere/claude-a@example.com.json",
        },
    ]
    response = await async_client.put(
        "/api/settings",
        json={
            "claudeSidecarEnabled": True,
            "claudeSidecarApiKey": "sidecar-key",
            "claudeSidecarManagementKey": "mgmt-key",
        },
    )
    assert response.status_code == 200

    response = await async_client.get("/api/claude-sidecar/routing")

    assert response.status_code == 200
    account = response.json()["accounts"][0]
    assert account["excludedModels"] == []
    assert account["excludedModelsState"] == "unreadable"


@pytest.mark.asyncio
async def test_get_routing_reads_excluded_models_from_auth_file(async_client, monkeypatch, tmp_path):
    monkeypatch.setattr("app.modules.claude_sidecar.service.ClaudeSidecarClient", _FakeSidecarClient)
    monkeypatch.setattr(
        "app.modules.claude_sidecar.excluded_models.default_auth_dir",
        lambda: tmp_path,
    )
    _reset_fake_sidecar_client()
    auth_path = tmp_path / "claude-a@example.com.json"
    auth_path.write_text(
        json.dumps(
            {
                "access_token": "synthetic-access-token",
                "refresh_token": "synthetic-refresh-token",
                "email": "a@example.com",
                "excluded_models": ["claude-demo-*"],
            }
        ),
        encoding="utf-8",
    )
    _FakeSidecarClient.auth_files = [
        {
            "name": "claude-a@example.com.json",
            "auth_index": "0",
            "provider": "claude",
            "email": "a@example.com",
            "path": str(auth_path),
        },
    ]
    response = await async_client.put(
        "/api/settings",
        json={
            "claudeSidecarEnabled": True,
            "claudeSidecarApiKey": "sidecar-key",
            "claudeSidecarManagementKey": "mgmt-key",
        },
    )
    assert response.status_code == 200

    response = await async_client.get("/api/claude-sidecar/routing")

    assert response.status_code == 200
    body = response.text
    account = response.json()["accounts"][0]
    assert account["excludedModels"] == ["claude-demo-*"]
    assert account["excludedModelsState"] == "available"
    assert "synthetic-access-token" not in body
    assert "synthetic-refresh-token" not in body


@pytest.mark.asyncio
@pytest.mark.parametrize("uncertain", [False, True])
async def test_put_routing_excluded_models_patches_stored_snapshot(async_client, monkeypatch, tmp_path, uncertain):
    import asyncio
    from dataclasses import replace
    from app.modules.claude_sidecar.quota_poller import ClaudeSidecarQuotaPoller

    path = tmp_path / "claude-a@example.com.json"
    path.write_text('{"excluded_models": []}')
    monkeypatch.setattr("app.modules.claude_sidecar.excluded_models.default_auth_dir", lambda: tmp_path)

    async def write_exclusions(self, name, patterns):
        import json
        path.write_text(json.dumps({"excluded_models": patterns}))
        if uncertain:
            raise ClaudeSidecarUnavailableError("response lost")
    monkeypatch.setattr(_FakeSidecarClient, "patch_auth_file_excluded_models", write_exclusions)
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

    checked_at = datetime(2026, 6, 10, 12, 0, 0, tzinfo=timezone.utc)
    snapshot = SidecarQuotaSnapshot(
        checked_at=checked_at,
        status="healthy",
        message=None,
        accounts=(
            SidecarAuthQuota(
                name="claude-a@example.com.json",
                auth_index="0",
                email="a@example.com",
                status="active",
                status_message=None,
                disabled=False,
                unavailable=False,
                quota_exceeded=False,
                next_recover_at=None,
                model_states=(),
                success=0,
                failed=0,
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

    snapshot = replace(snapshot, accounts=(replace(snapshot.accounts[0], credential_path=str(path)),))
    entered = asyncio.Event()
    resume = asyncio.Event()
    original_update = SettingsRepository.update_operational

    async def delayed_update(repo, **kwargs):
        if asyncio.current_task() is poll_task:
            entered.set()
            await resume.wait()
        return await original_update(repo, **kwargs)

    monkeypatch.setattr(SettingsRepository, "update_operational", delayed_update)
    poller = ClaudeSidecarQuotaPoller(interval_seconds=60, enabled=True)
    poll_task = asyncio.create_task(poller._persist_snapshot(snapshot))
    await asyncio.wait_for(entered.wait(), timeout=5)
    save_task = asyncio.create_task(async_client.put(
        "/api/claude-sidecar/routing/excluded-models",
        json={"name": path.name, "excludedModels": ["claude-demo-*"]},
    ))
    try:
        await asyncio.sleep(0.05)
        assert not save_task.done()
    finally:
        resume.set()
        await poll_task
    response = await save_task
    assert response.status_code == 200
    assert response.json()["status"] == ("unreachable" if uncertain else "healthy")

    async with SessionLocal() as session:
        stored = await SettingsRepository(session).get_fresh()
        from app.modules.claude_sidecar.quota import snapshot_from_json
        published = snapshot_from_json(stored.claude_sidecar_quota_state_json)
        assert published.accounts[0].excluded_models == (() if uncertain else ("claude-demo-*",))
    response = await async_client.get("/api/claude-sidecar/quota")
    assert response.status_code == 200
    accounts = {acct["name"]: acct for acct in response.json()["accounts"]}
    assert accounts["claude-a@example.com.json"]["excludedModels"] == ["claude-demo-*"]


@pytest.mark.asyncio
async def test_put_routing_excluded_models_without_management_key(async_client, monkeypatch):
    monkeypatch.setattr("app.modules.claude_sidecar.service.ClaudeSidecarClient", _FakeSidecarClient)
    _reset_fake_sidecar_client()
    response = await async_client.put(
        "/api/settings",
        json={
            "claudeSidecarEnabled": True,
            "claudeSidecarApiKey": "sidecar-key",
            "claudeSidecarClearManagementKey": True,
        },
    )
    assert response.status_code == 200

    response = await async_client.put(
        "/api/claude-sidecar/routing/excluded-models",
        json={"name": "claude-a@example.com.json", "excludedModels": ["claude-demo-*"]},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "not_configured"
    assert _FakeSidecarClient.excluded_models_updates == []


@pytest.mark.asyncio
async def test_put_routing_excluded_models_unknown_account(async_client, monkeypatch):
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
    _FakeSidecarClient.error = ClaudeSidecarError(404, "auth file not found")

    response = await async_client.put(
        "/api/claude-sidecar/routing/excluded-models",
        json={"name": "claude-missing.json", "excludedModels": ["claude-demo-*"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "error"
    assert "not found" in (payload["message"] or "")
    assert _FakeSidecarClient.excluded_models_updates == []
