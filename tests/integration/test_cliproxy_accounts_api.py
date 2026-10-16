from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.clients.claude_sidecar import ClaudeSidecarError, ClaudeSidecarUnavailableError
from app.core.types import JsonValue
from app.db.session import SessionLocal
from app.modules.claude_sidecar.quota import (
    GrokCreditsQuota,
    GrokCreditWindow,
    GrokTokenRollup,
    SidecarAuthQuota,
    SidecarQuotaSnapshot,
    SidecarRateLimitHold,
    snapshot_to_json,
)
from app.modules.settings.repository import SettingsRepository

pytestmark = pytest.mark.integration

_ACCESS_TOKEN = "cliproxy-test-access-token"
_REFRESH_TOKEN = "cliproxy-test-refresh-token"
_ID_TOKEN = "cliproxy-test-id-token"


class _FakeClient:
    error: Exception | None = None
    model_errors: set[str] = set()
    files: list[dict[str, JsonValue]] = []
    models: dict[str, list[str]] = {}

    def __init__(self, _config) -> None:
        pass

    async def list_auth_files(self) -> list[dict[str, JsonValue]]:
        if self.error is not None:
            raise self.error
        return list(self.files)

    async def list_auth_file_models(self, name: str) -> list[str]:
        if name in self.model_errors:
            raise ClaudeSidecarUnavailableError("connection refused")
        return list(self.models.get(name, []))


def _reset_fake() -> None:
    _FakeClient.error = None
    _FakeClient.model_errors = set()
    _FakeClient.files = [
        {
            "name": "claude-a.json",
            "auth_index": "c1",
            "provider": "claude",
            "type": "claude",
            "email": "claude@example.com",
            "status": "active",
            "disabled": False,
            "unavailable": False,
            "access_token": _ACCESS_TOKEN,
            "refresh_token": _REFRESH_TOKEN,
            "id_token": _ID_TOKEN,
        },
        {
            "name": "anthropic-b.json",
            "auth_index": "c2",
            "account_type": "anthropic",
            "email": "anthropic@example.com",
            "status": "active",
        },
        {
            "name": "grok-a.json",
            "auth_index": "x1",
            "provider": "xai",
            "type": "xai",
            "email": "grok@example.com",
            "status": "active",
            "prefix": "acct2",
            "disabled": False,
            "quota": {"exceeded": True, "next_recover_at": "2026-06-10T23:30:00Z"},
            "access_token": _ACCESS_TOKEN,
        },
    ]
    _FakeClient.models = {
        "claude-a.json": ["claude-opus-5"],
        "anthropic-b.json": ["claude-sonnet-5"],
        "grok-a.json": ["grok-4", "grok-4-fast"],
    }


def _install(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_fake()
    monkeypatch.setattr("app.modules.cliproxy_accounts.service.ClaudeSidecarClient", _FakeClient)


async def _configure(async_client, **payload) -> None:
    response = await async_client.put("/api/settings", json=payload)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_inventory_requires_management_key_then_lists_mixed_providers(async_client, monkeypatch):
    _install(monkeypatch)
    await _configure(
        async_client,
        claudeSidecarEnabled=False,
        claudeSidecarClearApiKey=True,
        claudeSidecarClearManagementKey=True,
    )

    missing = await async_client.get("/api/cliproxy/accounts")
    assert missing.status_code == 200
    assert missing.json()["status"] == "not_configured"
    assert missing.json()["providers"] == []

    await _configure(
        async_client,
        claudeSidecarEnabled=False,
        claudeSidecarBaseUrl="http://127.0.0.1:8317",
        claudeSidecarManagementKey="mgmt-key",
    )

    response = await async_client.get("/api/cliproxy/accounts")
    assert response.status_code == 200
    body = response.text
    assert _ACCESS_TOKEN not in body
    assert _REFRESH_TOKEN not in body
    assert _ID_TOKEN not in body
    payload = response.json()
    assert payload["status"] == "healthy"
    by_provider = {group["provider"]: group["credentials"] for group in payload["providers"]}
    assert set(by_provider) == {"claude", "xai"}
    claude = {row["email"]: row for row in by_provider["claude"]}
    assert set(claude) == {"claude@example.com", "anthropic@example.com"}
    assert claude["claude@example.com"]["models"] == ["claude-opus-5"]
    assert claude["claude@example.com"]["health"] == "active"
    assert claude["claude@example.com"]["prefix"] is None
    xai = by_provider["xai"][0]
    assert xai["email"] == "grok@example.com"
    assert xai["models"] == ["grok-4", "grok-4-fast"]
    assert xai["health"] == "quota_exceeded"
    assert xai["prefix"] == "acct2"
    assert xai["provider"] == "xai"


@pytest.mark.asyncio
async def test_inventory_provider_filter_and_models_error(async_client, monkeypatch):
    _install(monkeypatch)
    _FakeClient.model_errors = {"grok-a.json"}
    await _configure(
        async_client,
        claudeSidecarEnabled=False,
        claudeSidecarBaseUrl="http://127.0.0.1:8317",
        claudeSidecarManagementKey="mgmt-key",
    )

    response = await async_client.get("/api/cliproxy/accounts", params={"provider": "xai"})
    assert response.status_code == 200
    payload = response.json()
    assert [group["provider"] for group in payload["providers"]] == ["xai"]
    credential = payload["providers"][0]["credentials"][0]
    assert credential["models"] == []
    assert credential["modelsError"]
    assert _ACCESS_TOKEN not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (ClaudeSidecarUnavailableError("connection refused"), "unreachable"),
        (ClaudeSidecarError(401, "bad key"), "unauthorized"),
        (ClaudeSidecarError(500, "sidecar exploded"), "error"),
    ],
)
async def test_inventory_maps_management_errors(async_client, monkeypatch, error, expected_status):
    _install(monkeypatch)
    _FakeClient.error = error
    await _configure(
        async_client,
        claudeSidecarEnabled=True,
        claudeSidecarApiKey="sidecar-key",
        claudeSidecarManagementKey="mgmt-key",
    )

    response = await async_client.get("/api/cliproxy/accounts")
    assert response.status_code == 200
    assert response.json()["status"] == expected_status
    assert response.json()["providers"] == []


@pytest.mark.asyncio
async def test_provider_account_cards_stay_off_until_the_pool_switch(async_client, monkeypatch):
    now = datetime(2026, 10, 16, 8, 0, tzinfo=timezone.utc)
    snapshot = SidecarQuotaSnapshot(
        checked_at=now,
        status="healthy",
        message=None,
        accounts=(
            SidecarAuthQuota(
                name="claude.json",
                auth_index="c1",
                email="claude@example.com",
                provider="claude",
                status="active",
                status_message=None,
                disabled=False,
                unavailable=False,
                quota_exceeded=False,
                next_recover_at=None,
                model_states=(),
                success=1,
                failed=0,
                last_refresh=None,
            ),
            SidecarAuthQuota(
                name="grok.json",
                auth_index="x1",
                email="grok@example.com",
                provider="xai",
                status="active",
                status_message=None,
                disabled=False,
                unavailable=False,
                quota_exceeded=False,
                next_recover_at=None,
                model_states=(),
                success=1,
                failed=0,
                last_refresh=None,
                grok_credits=GrokCreditsQuota(
                    windows=(
                        GrokCreditWindow(
                            id="credits",
                            label="week",
                            kind="weekly",
                            percent_used=37.5,
                            percent_remaining=62.5,
                            resets_at=now + timedelta(days=6),
                        ),
                    ),
                    prepaid_credits=42,
                    refreshed_at=now,
                    token_rollup=GrokTokenRollup(total_tokens=1200, request_count=3, window_start=now),
                ),
            ),
        ),
    )
    async with SessionLocal() as session:
        await SettingsRepository(session).update(claude_sidecar_quota_state_json=snapshot_to_json(snapshot))
        await session.commit()

    hidden = await async_client.get("/api/accounts")
    assert hidden.status_code == 200
    hidden_ids = {account["accountId"] for account in hidden.json()["accounts"]}
    assert "cliproxy-claude" not in hidden_ids
    assert "cliproxy-xai" not in hidden_ids

    monkeypatch.setattr("app.modules.accounts.service.cliproxy_account_pool_enabled", lambda: True)
    shown = await async_client.get("/api/accounts")
    assert shown.status_code == 200
    by_id = {account["accountId"]: account for account in shown.json()["accounts"]}
    assert by_id["cliproxy-xai"]["provider"] == "xai"
    assert by_id["cliproxy-xai"]["synthetic"] is True
    assert by_id["cliproxy-xai"]["readOnly"] is True
    xai_auth = by_id["cliproxy-xai"]["sidecarAuths"][0]
    assert xai_auth["quotaWindows"][0]["percentRemaining"] == 62.5
    assert xai_auth["quotaWindows"][0]["label"] == "week"
    assert xai_auth["prepaidCredits"] == 42
    assert by_id["cliproxy-claude"]["provider"] == "claude"
    assert by_id["cliproxy-claude"]["sidecarAuths"][0]["quotaWindows"] == []
    assert "claude-sidecar" in by_id


@pytest.mark.asyncio
async def test_inventory_shows_stored_grok_quota_and_an_xai_hold(async_client, monkeypatch):
    _install(monkeypatch)
    await _configure(
        async_client,
        claudeSidecarEnabled=False,
        claudeSidecarBaseUrl="http://127.0.0.1:8317",
        claudeSidecarManagementKey="mgmt-key",
    )
    now = datetime(2026, 10, 16, 8, 0, tzinfo=timezone.utc)
    snapshot = SidecarQuotaSnapshot(
        checked_at=now,
        status="healthy",
        message=None,
        accounts=(
            SidecarAuthQuota(
                name="grok-a.json",
                auth_index="x1",
                email="grok@example.com",
                provider="xai",
                status="active",
                status_message=None,
                disabled=True,
                unavailable=False,
                quota_exceeded=False,
                next_recover_at=None,
                model_states=(),
                success=0,
                failed=0,
                last_refresh=None,
                grok_credits=GrokCreditsQuota(
                    windows=(
                        GrokCreditWindow(
                            id="credits",
                            label="week",
                            kind="weekly",
                            percent_used=37.5,
                            percent_remaining=62.5,
                            resets_at=now + timedelta(days=6),
                        ),
                    ),
                    prepaid_credits=42,
                    refreshed_at=now,
                    token_rollup=GrokTokenRollup(total_tokens=1200, request_count=3),
                ),
            ),
        ),
        rate_limit_holds=(
            SidecarRateLimitHold(
                name="grok-a.json",
                until=now + timedelta(hours=24),
                released=False,
                provider="xai",
                kind="free-usage-exhausted",
            ),
        ),
    )
    async with SessionLocal() as session:
        await SettingsRepository(session).update(claude_sidecar_quota_state_json=snapshot_to_json(snapshot))
        await session.commit()

    response = await async_client.get("/api/cliproxy/accounts")
    assert response.status_code == 200
    by_provider = {group["provider"]: group["credentials"] for group in response.json()["providers"]}
    xai = by_provider["xai"][0]
    assert xai["health"] == "rate_limited"
    assert xai["quotaWindows"][0]["percentRemaining"] == 62.5
    assert xai["prepaidCredits"] == 42
    assert xai["usageTokens"] == 1200
    assert xai["usageRequests"] == 3
    assert by_provider["claude"][0]["health"] == "active"
    assert by_provider["claude"][0]["quotaWindows"] == []
