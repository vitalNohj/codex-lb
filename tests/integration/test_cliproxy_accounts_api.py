from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.clients.claude_sidecar import ClaudeSidecarError, ClaudeSidecarUnavailableError
from app.core.types import JsonValue
from app.db.models import AuditLog, CliproxyCredentialPrefix
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
from app.modules.cliproxy_accounts.prefix_lock import cliproxy_prefix_write_lock
from app.modules.settings.repository import SettingsRepository

pytestmark = pytest.mark.integration

_ACCESS_TOKEN = "cliproxy-test-access-token"
_REFRESH_TOKEN = "cliproxy-test-refresh-token"
_ID_TOKEN = "cliproxy-test-id-token"


class _FakeClient:
    error: Exception | None = None
    field_error: Exception | None = None
    model_errors: set[str] = set()
    files: list[dict[str, JsonValue]] = []
    models: dict[str, list[str]] = {}
    field_calls: list[dict[str, JsonValue]] = []
    status_calls: list[dict[str, JsonValue]] = []

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

    async def patch_auth_file_fields(self, name: str, fields: Mapping[str, JsonValue]) -> None:
        if self.field_error is not None:
            raise self.field_error
        self.field_calls.append({"name": name, **dict(fields)})

    async def patch_auth_file_status(self, name: str, *, disabled: bool, auth_index: str | None = None) -> None:
        payload: dict[str, JsonValue] = {"name": name, "disabled": disabled}
        if auth_index:
            payload["auth_index"] = auth_index
        self.status_calls.append(payload)


def _reset_fake() -> None:
    _FakeClient.error = None
    _FakeClient.field_error = None
    _FakeClient.model_errors = set()
    _FakeClient.field_calls = []
    _FakeClient.status_calls = []
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


async def _ready(async_client) -> None:
    await _configure(
        async_client,
        claudeSidecarEnabled=False,
        claudeSidecarBaseUrl="http://127.0.0.1:8317",
        claudeSidecarManagementKey="mgmt-key",
    )


async def _stored_prefixes() -> dict[str, str]:
    async with SessionLocal() as session:
        rows = (await session.execute(select(CliproxyCredentialPrefix))).scalars().all()
        return {row.credential_name: row.prefix for row in rows}


async def _wait_for_audit_log(action: str, *, attempts: int = 20) -> AuditLog:
    for _ in range(attempts):
        async with SessionLocal() as session:
            result = await session.execute(
                select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.id.desc())
            )
            row = result.scalars().first()
            if row is not None:
                return row
        await asyncio.sleep(0.05)
    raise AssertionError(f"audit log not written for action={action}")


@pytest.mark.asyncio
async def test_patch_fields_ok_persists_prefix_without_changing_routing(async_client, monkeypatch):
    _install(monkeypatch)
    _FakeClient.files[0]["excluded_models"] = ["old-model"]
    _FakeClient.files[0]["weight"] = 1
    await _ready(async_client)
    before = await async_client.get("/api/settings")
    assert before.status_code == 200
    routing_before = before.json()["claudeSidecarModelPrefixes"]

    response = await async_client.patch(
        "/api/cliproxy/accounts/claude-a.json/fields",
        json={"prefix": " Acct1 ", "weight": 4, "priority": -2, "excludedModels": ["grok-4"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "claude-a.json"
    assert body["prefix"] == "acct1"
    assert body["weight"] == 4
    assert body["priority"] == -2
    assert body["excludedModels"] == ["grok-4"]
    assert body["excludedModelsState"] == "available"
    assert _FakeClient.field_calls == [
        {
            "name": "claude-a.json",
            "prefix": "acct1",
            "weight": 4,
            "priority": -2,
            "excluded_models": ["grok-4"],
        }
    ]
    assert _FakeClient.status_calls == []
    assert await _stored_prefixes() == {"claude-a.json": "acct1"}

    listed = await async_client.get("/api/cliproxy/accounts")
    assert listed.status_code == 200
    claude = {
        row["email"]: row
        for group in listed.json()["providers"]
        if group["provider"] == "claude"
        for row in group["credentials"]
    }
    assert claude["claude@example.com"]["prefix"] == "acct1"
    assert "cliproxy-test-access-token" not in listed.text

    after = await async_client.get("/api/settings")
    assert after.json()["claudeSidecarModelPrefixes"] == routing_before
    assert after.json()["claudeSidecarEnabled"] is False

    audit = await _wait_for_audit_log("cliproxy_credential_fields_updated")
    details = json.loads(audit.details or "{}")
    assert details["credential_name"] == "claude-a.json"
    assert details["provider"] == "claude"
    assert details["changed_fields"] == ["prefix", "weight", "priority", "excluded_models"]
    assert details["prefix"] == "acct1"
    assert details["weight"] == 4
    assert details["excluded_models"] == ["grok-4"]
    assert "access_token" not in (audit.details or "")


@pytest.mark.asyncio
async def test_patch_fields_unknown_credential_is_404(async_client, monkeypatch):
    _install(monkeypatch)
    await _ready(async_client)

    response = await async_client.patch(
        "/api/cliproxy/accounts/missing.json/fields",
        json={"prefix": "acct4"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert _FakeClient.field_calls == []
    assert await _stored_prefixes() == {}


@pytest.mark.asyncio
async def test_patch_fields_relays_upstream_404_and_conflict(async_client, monkeypatch):
    _install(monkeypatch)
    await _ready(async_client)

    _FakeClient.field_error = ClaudeSidecarError(404, "auth file not found")
    missing = await async_client.patch(
        "/api/cliproxy/accounts/claude-a.json/fields",
        json={"weight": 2},
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
    assert await _stored_prefixes() == {}

    _FakeClient.field_error = ClaudeSidecarError(409, "prefix taken upstream")
    conflict = await async_client.patch(
        "/api/cliproxy/accounts/claude-a.json/fields",
        json={"weight": 2},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "conflict"
    assert "prefix taken upstream" in conflict.json()["error"]["message"]
    assert await _stored_prefixes() == {}


@pytest.mark.asyncio
async def test_patch_fields_rejects_prefix_used_by_another_credential(async_client, monkeypatch):
    _install(monkeypatch)
    await _ready(async_client)

    response = await async_client.patch(
        "/api/cliproxy/accounts/claude-a.json/fields",
        json={"prefix": "acct2"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"
    assert response.json()["error"]["message"] == "Prefix acct2 is already assigned to grok-a.json"
    assert _FakeClient.field_calls == []
    assert await _stored_prefixes() == {}


@pytest.mark.asyncio
async def test_patch_fields_rejects_prefix_that_clashes_with_sidecar_routing(async_client, monkeypatch):
    _install(monkeypatch)
    await _ready(async_client)
    saved = await async_client.put("/api/settings", json={"claudeSidecarModelPrefixes": ["acct1"]})
    assert saved.status_code == 200

    response = await async_client.patch(
        "/api/cliproxy/accounts/claude-a.json/fields",
        json={"prefix": "acct1"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["message"] == "Prefix acct1 clashes with the CLIProxyAPI routing prefix"
    assert _FakeClient.field_calls == []
    assert await _stored_prefixes() == {}


@pytest.mark.asyncio
async def test_patch_fields_keeps_a_stored_prefix_when_the_auth_list_omits_it(async_client, monkeypatch):
    _install(monkeypatch)
    await _ready(async_client)
    first = await async_client.patch(
        "/api/cliproxy/accounts/claude-a.json/fields",
        json={"prefix": "acct1"},
    )
    assert first.status_code == 200
    _FakeClient.field_calls.clear()

    second = await async_client.patch(
        "/api/cliproxy/accounts/grok-a.json/fields",
        json={"prefix": "acct1"},
    )

    assert second.status_code == 409
    assert "already assigned to claude-a.json" in second.json()["error"]["message"]
    assert _FakeClient.field_calls == []
    assert await _stored_prefixes() == {"claude-a.json": "acct1"}


@pytest.mark.asyncio
async def test_patch_status_requires_confirmation_then_disables_and_audits(async_client, monkeypatch):
    _install(monkeypatch)
    await _ready(async_client)

    refused = await async_client.patch(
        "/api/cliproxy/accounts/claude-a.json/status",
        json={"disabled": True, "confirm": False},
    )
    assert refused.status_code == 400
    assert refused.json()["error"]["code"] == "bad_request"
    assert _FakeClient.status_calls == []

    accepted = await async_client.patch(
        "/api/cliproxy/accounts/claude-a.json/status",
        json={"disabled": True, "confirm": True},
    )
    assert accepted.status_code == 200
    assert accepted.json() == {"name": "claude-a.json", "disabled": True}
    assert _FakeClient.status_calls == [{"name": "claude-a.json", "disabled": True, "auth_index": "c1"}]
    assert _FakeClient.field_calls == []

    audit = await _wait_for_audit_log("cliproxy_credential_status_updated")
    assert json.loads(audit.details or "{}") == {
        "credential_name": "claude-a.json",
        "provider": "claude",
        "disabled": True,
    }


@pytest.mark.asyncio
async def test_patch_fields_refuses_to_replace_unreadable_excluded_models(async_client, monkeypatch):
    _install(monkeypatch)
    await _ready(async_client)

    response = await async_client.patch(
        "/api/cliproxy/accounts/claude-a.json/fields",
        json={"excludedModels": []},
    )

    assert response.status_code == 400
    assert "could not be read" in response.json()["error"]["message"]
    assert _FakeClient.field_calls == []


@pytest.mark.asyncio
async def test_prefix_write_lock_keeps_overlapping_holders_in_order(async_client):
    del async_client
    order: list[str] = []

    async def hold(label: str) -> None:
        async with SessionLocal() as session:
            async with cliproxy_prefix_write_lock(session):
                order.append(f"in-{label}")
                await asyncio.sleep(0.05)
                order.append(f"out-{label}")

    await asyncio.gather(hold("a"), hold("b"))

    assert len(order) == 4
    assert order[0].startswith("in-")
    assert order[1] == f"out-{order[0].removeprefix('in-')}"
    assert order[2].startswith("in-")
    assert order[3] == f"out-{order[2].removeprefix('in-')}"


@pytest.mark.asyncio
async def test_prefix_registry_flush_failure_restores_the_upstream_prefix(async_client, monkeypatch):
    _install(monkeypatch)
    await _ready(async_client)
    async with SessionLocal() as session:
        session.add(
            CliproxyCredentialPrefix(
                credential_name="taken.json",
                auth_index=None,
                prefix="acct1",
                updated_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()
    # The in-memory check would reject this before the flush. Skip it so the
    # unique constraint is what fails, which is the race the lock cannot see
    # once the row is already committed.
    monkeypatch.setattr(
        "app.modules.cliproxy_accounts.service.prefix_conflict_message",
        lambda *_args, **_kwargs: None,
    )

    response = await async_client.patch(
        "/api/cliproxy/accounts/claude-a.json/fields",
        json={"prefix": "acct1"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"
    assert [call["prefix"] for call in _FakeClient.field_calls] == ["acct1", ""]
    assert await _stored_prefixes() == {"taken.json": "acct1"}


@pytest.mark.asyncio
async def test_guest_cannot_edit_cliproxy_credential_fields(app_instance, monkeypatch):
    _install(monkeypatch)
    async with app_instance.router.lifespan_context(app_instance):
        local_transport = ASGITransport(app=app_instance, client=("127.0.0.1", 50000))
        async with AsyncClient(transport=local_transport, base_url="http://localhost") as local_client:
            await _ready(local_client)
            current = (await local_client.get("/api/settings")).json()
            current["guestAccessEnabled"] = True
            updated = await local_client.put("/api/settings", json=current)
            assert updated.status_code == 200

        remote_transport = ASGITransport(app=app_instance, client=("203.0.113.20", 50001))
        async with AsyncClient(transport=remote_transport, base_url="http://lb.example") as remote_client:
            listed = await remote_client.get("/api/cliproxy/accounts")
            assert listed.status_code == 200
            assert listed.json()["status"] == "healthy"

            fields = await remote_client.patch(
                "/api/cliproxy/accounts/claude-a.json/fields",
                json={"prefix": "acct1"},
            )
            status = await remote_client.patch(
                "/api/cliproxy/accounts/claude-a.json/status",
                json={"disabled": True, "confirm": True},
            )

    assert fields.status_code == 403
    assert fields.json()["error"]["code"] == "read_only_access"
    assert status.status_code == 403
    assert status.json()["error"]["code"] == "read_only_access"
    assert _FakeClient.field_calls == []
    assert _FakeClient.status_calls == []
