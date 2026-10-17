from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.clients.claude_sidecar import ClaudeSidecarError, ClaudeSidecarUnavailableError
from app.core.types import JsonValue
from app.db.models import AuditLog
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
from app.modules.cliproxy_accounts.oauth_flow import reset_oauth_completion
from app.modules.cliproxy_accounts.refresh_jobs import reset_refresh_jobs
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
    status_error: Exception | None = None
    list_delay_seconds: float = 0.0
    api_key_lists: dict[str, list[dict[str, JsonValue]]] = {}
    management_calls: list[tuple[str, str, Mapping[str, JsonValue] | None]] = []
    management_get_hook: Callable[[], Awaitable[None]] | None = None

    def __init__(self, _config) -> None:
        pass

    async def list_auth_files(self) -> list[dict[str, JsonValue]]:
        if self.list_delay_seconds:
            await asyncio.sleep(self.list_delay_seconds)
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
        for entry in self.files:
            if entry.get("name") == name:
                entry["disabled"] = disabled
        if self.status_error is not None:
            raise self.status_error

    async def management_request(
        self,
        method: str,
        path: str,
        body: Mapping[str, JsonValue] | None,
    ) -> dict[str, JsonValue]:
        self.management_calls.append((method, path, None if body is None else dict(body)))
        hook = type(self).management_get_hook
        if method == "GET" and hook is not None:
            await hook()
        route, _, query = path.partition("?")
        key = route.rsplit("/", 1)[-1]
        if method == "GET":
            return {key: [dict(item) for item in self.api_key_lists.get(key, [])]}
        if method == "PUT":
            raw_items = [] if body is None else body.get("items")
            items = [dict(item) for item in raw_items if isinstance(item, dict)] if isinstance(raw_items, list) else []
            self.api_key_lists[key] = items
            return {"status": "ok"}
        if method == "DELETE":
            index = int(query.removeprefix("index="))
            current = list(self.api_key_lists.get(key, []))
            if 0 <= index < len(current):
                del current[index]
            self.api_key_lists[key] = current
            return {}
        raise AssertionError(method)


def _reset_fake() -> None:
    _FakeClient.error = None
    _FakeClient.field_error = None
    _FakeClient.model_errors = set()
    _FakeClient.field_calls = []
    _FakeClient.status_calls = []
    _FakeClient.status_error = None
    _FakeClient.list_delay_seconds = 0.0
    _FakeClient.api_key_lists = {}
    _FakeClient.management_calls = []
    _FakeClient.management_get_hook = None
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


class _FakeManagement:
    """Stub of CLIProxyAPI's management endpoints. Responses may carry tokens; the panel must drop them."""

    calls: list[tuple[object, ...]] = []
    start_payload: dict[str, JsonValue] = {}
    status_script: list[dict[str, JsonValue]] = []
    delete_error: Exception | None = None
    refresh_error: Exception | None = None
    upload_bodies: list[bytes] = []

    def __init__(self, _client: object) -> None:
        del _client

    async def start_oauth(self, path: str) -> dict[str, JsonValue]:
        self.calls.append(("start", path))
        return dict(self.start_payload)

    async def auth_status(self, state: str) -> dict[str, JsonValue]:
        self.calls.append(("status", state))
        script = self.status_script
        if not script:
            return {"status": "wait"}
        payload = script.pop(0) if len(script) > 1 else script[0]
        return dict(payload)

    async def cancel_oauth(self, state: str) -> dict[str, JsonValue]:
        self.calls.append(("cancel", state))
        return {"status": "ok", "cancelled": True, "access_token": _ACCESS_TOKEN}

    async def submit_callback(self, payload: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
        self.calls.append(("callback", dict(payload)))
        return {"status": "ok", "access_token": _ACCESS_TOKEN}

    async def delete_auth_file(self, name: str) -> None:
        self.calls.append(("delete", name, list(_FakeClient.status_calls)))
        if self.delete_error is not None:
            raise self.delete_error

    async def refresh_auth_file(self, name: str, auth_index: str | None) -> dict[str, str]:
        self.calls.append(("refresh", name, auth_index))
        if self.refresh_error is not None:
            raise self.refresh_error
        return {"access_token": _ACCESS_TOKEN, "refresh_token": _REFRESH_TOKEN}

    async def upload_auth_file(self, name: str, data: bytes) -> None:
        self.calls.append(("upload", name))
        self.upload_bodies.append(data)


def _reset_management() -> None:
    _FakeManagement.calls = []
    _FakeManagement.start_payload = {}
    _FakeManagement.status_script = []
    _FakeManagement.delete_error = None
    _FakeManagement.refresh_error = None
    _FakeManagement.upload_bodies = []


def _install_management(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch)
    _reset_management()
    reset_oauth_completion()
    monkeypatch.setattr(
        "app.modules.cliproxy_accounts.service.build_management",
        lambda _client: _FakeManagement(_client),
    )


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
async def test_provider_account_cards_include_non_claude_credentials(async_client):
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

    shown = await async_client.get("/api/accounts")
    assert shown.status_code == 200
    by_id = {account["accountId"]: account for account in shown.json()["accounts"]}
    assert "cliproxy-claude" not in by_id
    assert by_id["cliproxy-xai"]["provider"] == "xai"
    assert by_id["cliproxy-xai"]["synthetic"] is True
    assert by_id["cliproxy-xai"]["readOnly"] is True
    xai_auth = by_id["cliproxy-xai"]["sidecarAuths"][0]
    assert xai_auth["quotaWindows"][0]["percentRemaining"] == 62.5
    assert xai_auth["quotaWindows"][0]["label"] == "week"
    assert xai_auth["prepaidCredits"] == 42
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


async def _audit_rows(action: str) -> list[AuditLog]:
    async with SessionLocal() as session:
        result = await session.execute(select(AuditLog).where(AuditLog.action == action))
        return list(result.scalars().all())


@pytest.mark.asyncio
async def test_patch_fields_updates_weight_priority_and_excluded_models(async_client, monkeypatch):
    _install(monkeypatch)
    _FakeClient.files[0]["excluded_models"] = ["old-model"]
    _FakeClient.files[0]["weight"] = 1
    _FakeClient.files[0]["prefix"] = "acct1"
    await _ready(async_client)
    before = await async_client.get("/api/settings")
    assert before.status_code == 200
    routing_before = before.json()["claudeSidecarModelPrefixes"]

    response = await async_client.patch(
        "/api/cliproxy/accounts/claude-a.json/fields",
        json={
            "weight": 4,
            "priority": -2,
            "excludedModels": ["grok-4"],
        },
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
            "weight": 4,
            "priority": -2,
            "excluded_models": ["grok-4"],
        }
    ]
    assert "prefix" not in _FakeClient.field_calls[0]
    assert _FakeClient.status_calls == []

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
    assert details["changed_fields"] == ["weight", "priority", "excluded_models"]
    assert details["weight"] == 4
    assert details["excluded_models"] == ["grok-4"]
    assert "prefix" not in details
    assert "access_token" not in (audit.details or "")


@pytest.mark.asyncio
async def test_patch_fields_unknown_credential_is_404(async_client, monkeypatch):
    _install(monkeypatch)
    await _ready(async_client)

    response = await async_client.patch(
        "/api/cliproxy/accounts/missing.json/fields",
        json={"weight": 2},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert _FakeClient.field_calls == []


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

    _FakeClient.field_error = ClaudeSidecarError(409, "prefix taken upstream")
    conflict = await async_client.patch(
        "/api/cliproxy/accounts/claude-a.json/fields",
        json={"weight": 2},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "conflict"
    assert "prefix taken upstream" in conflict.json()["error"]["message"]


@pytest.mark.asyncio
async def test_patch_status_confirms_only_the_last_enabled_account(async_client, monkeypatch):
    _install(monkeypatch)
    await _ready(async_client)

    other_enabled = await async_client.patch(
        "/api/cliproxy/accounts/claude-a.json/status",
        json={"disabled": True, "confirm": False},
    )
    assert other_enabled.status_code == 200
    assert other_enabled.json() == {"name": "claude-a.json", "disabled": True}
    assert _FakeClient.status_calls == [{"name": "claude-a.json", "disabled": True, "auth_index": "c1"}]

    _FakeClient.status_calls.clear()
    for entry in _FakeClient.files:
        entry["disabled"] = entry["name"] != "claude-a.json"

    refused = await async_client.patch(
        "/api/cliproxy/accounts/claude-a.json/status",
        json={"disabled": True, "confirm": False},
    )
    assert refused.status_code == 400
    assert refused.json()["error"]["code"] == "bad_request"
    assert "last enabled" in refused.json()["error"]["message"]
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

    enabled = await async_client.patch(
        "/api/cliproxy/accounts/claude-a.json/status",
        json={"disabled": False},
    )
    assert enabled.status_code == 200
    assert enabled.json() == {"name": "claude-a.json", "disabled": False}


@pytest.mark.asyncio
async def test_overlapping_unconfirmed_disables_leave_one_account_enabled(async_client, monkeypatch):
    _install(monkeypatch)
    await _ready(async_client)
    for entry in _FakeClient.files:
        if entry["name"] not in {"claude-a.json", "grok-a.json"}:
            entry["disabled"] = True
    _FakeClient.list_delay_seconds = 0.05

    async def disable(name: str):
        return await async_client.patch(
            f"/api/cliproxy/accounts/{name}/status",
            json={"disabled": True, "confirm": False},
        )

    first, second = await asyncio.gather(disable("claude-a.json"), disable("grok-a.json"))
    refused = first if first.status_code == 400 else second
    accepted = second if refused is first else first
    accepted_name = accepted.json()["name"]
    assert accepted.status_code == 200
    assert refused.status_code == 400
    assert "last enabled" in refused.json()["error"]["message"]
    assert _FakeClient.status_calls == [
        {
            "name": accepted_name,
            "disabled": True,
            "auth_index": "c1" if accepted_name == "claude-a.json" else "x1",
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/cliproxy/config"),
        ("POST", "/api/cliproxy/config/preview"),
        ("PUT", "/api/cliproxy/config"),
        ("POST", "/api/cliproxy/config/rollback"),
        ("PATCH", "/api/cliproxy/config/routing/force-model-prefix"),
        ("PATCH", "/api/cliproxy/config/routing/session-affinity"),
    ],
)
async def test_config_editor_endpoints_are_gone(async_client, method, path):
    response = await async_client.request(method, path, json={})
    assert response.status_code == 404


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
                json={"weight": 2},
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


@pytest.mark.asyncio
async def test_oauth_providers_offer_xai_device_login_once(async_client):
    response = await async_client.get("/api/cliproxy/oauth/providers")

    assert response.status_code == 200
    providers = {row["provider"]: row["method"] for row in response.json()["providers"]}
    assert providers["claude"] == "browser"
    assert providers["xai"] == "device"
    assert "anthropic" not in providers
    assert _ACCESS_TOKEN not in response.text


@pytest.mark.asyncio
async def test_oauth_state_machine_pending_then_ok_then_callback_without_tokens(async_client, monkeypatch):
    _install_management(monkeypatch)
    await reset_refresh_jobs()
    await _ready(async_client)
    _FakeManagement.start_payload = {
        "status": "ok",
        "url": "https://auth.example/device",
        "state": "xai-device-state",
        "flow": "device",
        "user_code": "ABCD-1234",
        "expires_in": 120,
        "access_token": _ACCESS_TOKEN,
    }
    _FakeManagement.status_script = [
        {"status": "wait", "access_token": _ACCESS_TOKEN},
        {"status": "ok", "access_token": _ACCESS_TOKEN, "refresh_token": _REFRESH_TOKEN},
    ]

    started = await async_client.post("/api/cliproxy/oauth/xai/authorize")
    assert started.status_code == 200
    assert started.json() == {
        "state": "xai-device-state",
        "provider": "xai",
        "method": "device",
        "authorizationUrl": None,
        "verificationUrl": "https://auth.example/device",
        "userCode": "ABCD-1234",
        "intervalSeconds": 2,
        "expiresInSeconds": 120,
    }
    assert _ACCESS_TOKEN not in started.text
    assert _FakeManagement.calls[0] == ("start", "/v0/management/xai-auth-url")

    pending = await async_client.get("/api/cliproxy/oauth/status", params={"state": "xai-device-state"})
    assert pending.status_code == 200
    assert pending.json() == {"status": "pending", "errorMessage": None}
    assert _ACCESS_TOKEN not in pending.text

    success = await async_client.get("/api/cliproxy/oauth/status", params={"state": "xai-device-state"})
    assert success.status_code == 200
    assert success.json()["status"] == "success"
    assert _ACCESS_TOKEN not in success.text
    assert _REFRESH_TOKEN not in success.text
    audit = await _wait_for_audit_log("cliproxy_oauth_completed")
    assert json.loads(audit.details or "{}") == {"state": "xai-device-state", "provider": "xai"}

    again = await async_client.get("/api/cliproxy/oauth/status", params={"state": "xai-device-state"})
    assert again.status_code == 200
    assert again.json()["status"] == "success"
    matching = [
        row for row in await _audit_rows("cliproxy_oauth_completed") if "xai-device-state" in (row.details or "")
    ]
    assert len(matching) == 1

    _FakeManagement.start_payload = {
        "status": "ok",
        "url": "https://auth.example/claude",
        "state": "browser-state",
        "access_token": _ACCESS_TOKEN,
    }
    browser = await async_client.post("/api/cliproxy/oauth/claude/authorize")
    assert browser.status_code == 200
    assert browser.json()["method"] == "browser"
    assert browser.json()["authorizationUrl"] == "https://auth.example/claude"
    assert browser.json()["verificationUrl"] is None
    secret = "super-secret-auth-code"
    callback = await async_client.post(
        "/api/cliproxy/oauth/callback",
        json={
            "provider": "claude",
            "state": "browser-state",
            "callbackUrl": f"http://127.0.0.1:54545/callback?code={secret}&state=browser-state",
        },
    )
    assert callback.status_code == 200
    assert callback.json() == {"status": "pending", "errorMessage": None}
    assert secret not in callback.text
    assert _ACCESS_TOKEN not in callback.text
    kind, forwarded = _FakeManagement.calls[-1]
    assert kind == "callback"
    assert forwarded == {
        "provider": "anthropic",
        "state": "browser-state",
        "redirect_url": f"http://127.0.0.1:54545/callback?code={secret}&state=browser-state",
    }


@pytest.mark.asyncio
async def test_oauth_status_error_is_redacted_and_cancel_drops_tokens(async_client, monkeypatch):
    _install_management(monkeypatch)
    await _ready(async_client)
    _FakeManagement.start_payload = {
        "status": "ok",
        "url": "https://auth.example/device",
        "state": "xai-error-state",
        "flow": "device",
        "user_code": "WXYZ-9999",
    }
    _FakeManagement.status_script = [{"status": "error", "error": "code=super-secret-auth-code"}]

    started = await async_client.post("/api/cliproxy/oauth/xai/authorize")
    assert started.status_code == 200
    failed = await async_client.get("/api/cliproxy/oauth/status", params={"state": "xai-error-state"})
    assert failed.status_code == 200
    assert failed.json()["status"] == "error"
    assert "super-secret-auth-code" not in failed.text
    assert "code=[redacted]" in failed.json()["errorMessage"]
    completed = [
        row for row in await _audit_rows("cliproxy_oauth_completed") if "xai-error-state" in (row.details or "")
    ]
    assert completed == []

    cancelled = await async_client.delete("/api/cliproxy/oauth/session", params={"state": "xai-error-state"})
    assert cancelled.status_code == 200
    assert cancelled.json() == {"status": "ok", "cancelled": True}
    assert _ACCESS_TOKEN not in cancelled.text
    assert ("cancel", "xai-error-state") in _FakeManagement.calls


@pytest.mark.asyncio
async def test_delete_disables_before_delete_and_writes_one_audit(async_client, monkeypatch):
    _install_management(monkeypatch)
    await _ready(async_client)
    status_audits = len(await _audit_rows("cliproxy_credential_status_updated"))

    refused = await async_client.request(
        "DELETE",
        "/api/cliproxy/accounts/grok-a.json",
        json={"confirm": False},
    )
    assert refused.status_code == 400
    assert _FakeClient.status_calls == []
    assert [call[0] for call in _FakeManagement.calls] == []

    deleted = await async_client.request(
        "DELETE",
        "/api/cliproxy/accounts/grok-a.json",
        json={"confirm": True},
    )
    assert deleted.status_code == 200
    assert deleted.json() == {"name": "grok-a.json", "disabled": True, "deleted": True}
    assert _ACCESS_TOKEN not in deleted.text
    assert _FakeClient.status_calls == [{"name": "grok-a.json", "disabled": True, "auth_index": "x1"}]
    assert _FakeManagement.calls[-1][0] == "delete"
    assert _FakeManagement.calls[-1][1] == "grok-a.json"
    assert _FakeManagement.calls[-1][2] == _FakeClient.status_calls
    audit = await _wait_for_audit_log("cliproxy_credential_deleted")
    assert json.loads(audit.details or "{}") == {
        "credential_name": "grok-a.json",
        "provider": "xai",
        "disabled": True,
        "deleted": True,
    }
    matching = [row for row in await _audit_rows("cliproxy_credential_deleted") if "grok-a.json" in (row.details or "")]
    assert len(matching) == 1
    assert len(await _audit_rows("cliproxy_credential_status_updated")) == status_audits


@pytest.mark.asyncio
async def test_delete_stops_when_disable_fails_and_reports_a_failed_delete(async_client, monkeypatch):
    _install_management(monkeypatch)
    await _ready(async_client)
    _FakeClient.status_error = ClaudeSidecarError(500, "disable failed")

    blocked = await async_client.request(
        "DELETE",
        "/api/cliproxy/accounts/claude-a.json",
        json={"confirm": True},
    )
    assert blocked.status_code == 502
    assert [call[0] for call in _FakeManagement.calls] == []
    assert _FakeClient.status_calls == [{"name": "claude-a.json", "disabled": True, "auth_index": "c1"}]
    deleted_rows = [
        row for row in await _audit_rows("cliproxy_credential_deleted") if "claude-a.json" in (row.details or "")
    ]
    assert deleted_rows == []

    _FakeClient.status_error = None
    _FakeClient.status_calls = []
    _FakeManagement.delete_error = ClaudeSidecarError(500, "access_token=cliproxy-test-access-token")
    failed = await async_client.request(
        "DELETE",
        "/api/cliproxy/accounts/claude-a.json",
        json={"confirm": True},
    )
    assert failed.status_code == 502
    assert failed.json()["error"]["message"].startswith(
        "The credential was turned off, but CLIProxyAPI did not delete it. It stays turned off."
    )
    assert _ACCESS_TOKEN not in failed.text
    assert _FakeManagement.calls[-1][0] == "delete"
    audit = await _wait_for_audit_log("cliproxy_credential_deleted")
    details = json.loads(audit.details or "{}")
    assert details["credential_name"] == "claude-a.json"
    assert details["disabled"] is True
    assert details["deleted"] is False
    assert _ACCESS_TOKEN not in (audit.details or "")
    matching = [
        row for row in await _audit_rows("cliproxy_credential_deleted") if "claude-a.json" in (row.details or "")
    ]
    assert len(matching) == 1


@pytest.mark.asyncio
async def test_refresh_poll_shows_pending_then_ok_without_tokens(async_client, monkeypatch):
    _install_management(monkeypatch)
    await reset_refresh_jobs()
    await _ready(async_client)

    started = await async_client.post("/api/cliproxy/accounts/claude-a.json/refresh")
    assert started.status_code == 200
    assert started.json()["status"] == "pending"
    assert _ACCESS_TOKEN not in started.text

    observed = started.json()
    for _ in range(50):
        if observed["status"] != "pending":
            break
        await asyncio.sleep(0.02)
        polled = await async_client.get("/api/cliproxy/accounts/claude-a.json/refresh")
        assert polled.status_code == 200
        assert _ACCESS_TOKEN not in polled.text
        assert _REFRESH_TOKEN not in polled.text
        observed = polled.json()

    assert observed == {"name": "claude-a.json", "status": "ok", "message": None}
    assert ("refresh", "claude-a.json", "c1") in _FakeManagement.calls
    audit = await _wait_for_audit_log("cliproxy_credential_refreshed")
    assert json.loads(audit.details or "{}") == {
        "credential_name": "claude-a.json",
        "provider": "claude",
        "status": "ok",
    }


@pytest.mark.asyncio
async def test_upload_rejects_unknown_fields_and_forwards_an_existing_prefix(async_client, monkeypatch):
    _install_management(monkeypatch)
    await _ready(async_client)
    secret = "uploaded-access-token"
    rejected = await async_client.post(
        "/api/cliproxy/accounts/upload",
        json={
            "name": "grok-b.json",
            "document": json.dumps({"type": "xai", "access_token": secret, "mystery": True}),
        },
    )
    assert rejected.status_code == 400
    assert "mystery" in rejected.json()["error"]["message"]
    assert _FakeManagement.upload_bodies == []

    accepted = await async_client.post(
        "/api/cliproxy/accounts/upload",
        json={
            "name": "grok-b.json",
            "document": json.dumps({"type": "xai", "access_token": secret, "prefix": "acct8"}),
        },
    )
    assert accepted.status_code == 200
    assert accepted.json() == {"name": "grok-b.json", "provider": "xai", "prefix": "acct8"}
    assert secret not in accepted.text
    uploaded = json.loads(_FakeManagement.upload_bodies[-1])
    assert uploaded["access_token"] == secret
    assert uploaded["prefix"] == "acct8"
    audit = await _wait_for_audit_log("cliproxy_credential_uploaded")
    assert json.loads(audit.details or "{}") == {
        "credential_name": "grok-b.json",
        "provider": "xai",
        "prefix": "acct8",
    }
    assert secret not in (audit.details or "")


@pytest.mark.asyncio
async def test_guest_cannot_sign_in_refresh_upload_or_delete(app_instance, monkeypatch):
    _install_management(monkeypatch)
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
            authorize = await remote_client.post("/api/cliproxy/oauth/xai/authorize")
            refresh = await remote_client.post("/api/cliproxy/accounts/claude-a.json/refresh")
            upload = await remote_client.post(
                "/api/cliproxy/accounts/upload",
                json={"name": "grok-b.json", "document": "{}"},
            )
            delete = await remote_client.request(
                "DELETE",
                "/api/cliproxy/accounts/claude-a.json",
                json={"confirm": True},
            )

    assert authorize.status_code == 403
    assert refresh.status_code == 403
    assert upload.status_code == 403
    assert delete.status_code == 403
    assert _FakeManagement.calls == []
    assert _FakeClient.status_calls == []


@pytest.mark.asyncio
async def test_api_key_accounts_are_edited_without_returning_the_key(async_client, monkeypatch):
    _install(monkeypatch)
    _FakeClient.files.append(
        {
            "id": "runtime-openrouter.json",
            "name": "runtime-openrouter.json",
            "auth_index": "k1",
            "provider": "openai-compatibility",
            "runtime_only": True,
            "status": "active",
        }
    )
    _FakeClient.models["runtime-openrouter.json"] = ["openrouter/auto"]
    _FakeClient.api_key_lists["openai-compatibility"] = [
        {
            "name": "openrouter",
            "base-url": "https://openrouter.ai/api/v1",
            "api-key-entries": [{"api-key": "sk-old"}],
            "models": [{"name": "openai/gpt-4o", "alias": "grok-4"}],
            "prefix": "keep-me",
            "disabled": False,
            "auth-index": "k1",
        }
    ]
    await _ready(async_client)

    listed = await async_client.get("/api/cliproxy/accounts")
    assert listed.status_code == 200
    body = listed.json()
    assert "sk-old" not in listed.text
    assert body["sharedModelIds"] == []
    names = [row["name"] for group in body["providers"] for row in group["credentials"]]
    assert "runtime-openrouter.json" not in names
    account = body["apiKeys"][0]
    assert account["kind"] == "openai-compatibility"
    assert account["name"] == "openrouter"
    assert account["hasApiKey"] is True
    assert account["prefix"] == "keep-me"
    assert account["discoveredModels"] == ["openrouter/auto"]
    assert account["supportsDisable"] is True
    assert account["id"]

    updated = await async_client.patch(
        "/api/cliproxy/api-keys/openai-compatibility/0",
        json={
            "kind": "openai-compatibility",
            "name": "openrouter",
            "baseUrl": "https://openrouter.ai/api/v1",
            "models": ["other-model"],
            "accountId": account["id"],
        },
    )
    assert updated.status_code == 200
    assert "sk-old" not in updated.text
    put = next(call for call in _FakeClient.management_calls if call[0] == "PUT")
    stored = put[2]["items"][0]
    assert stored["prefix"] == "keep-me"
    assert stored["api-key-entries"][0]["api-key"] == "sk-old"
    assert stored["models"] == [{"name": "other-model", "alias": "other-model"}]

    created = await async_client.post(
        "/api/cliproxy/api-keys",
        json={
            "kind": "openai-compatibility",
            "name": "second",
            "baseUrl": "https://example.test/v1",
            "apiKey": "sk-new",
            "models": ["grok-4"],
        },
    )
    assert created.status_code == 200
    assert created.json()["hasApiKey"] is True
    assert "sk-new" not in created.text
    assert created.json()["index"] == 1

    again = await async_client.get("/api/cliproxy/accounts")
    assert "grok-4" in again.json()["sharedModelIds"]

    refused = await async_client.patch(
        "/api/cliproxy/api-keys/claude/0",
        json={
            "kind": "claude",
            "baseUrl": "https://api.anthropic.com",
            "disabled": True,
        },
    )
    assert refused.status_code == 400

    removed = await async_client.request(
        "DELETE",
        "/api/cliproxy/api-keys/openai-compatibility/0",
        json={"confirm": True, "accountId": updated.json()["id"]},
    )
    assert removed.status_code == 200
    assert removed.json()["deleted"] is True
    assert _FakeClient.api_key_lists["openai-compatibility"][0]["name"] == "second"


@pytest.mark.asyncio
async def test_api_key_saves_keep_mappings_spaced_names_and_reject_stale_ids(async_client, monkeypatch):
    _install(monkeypatch)
    _FakeClient.api_key_lists["openai-compatibility"] = [
        {
            "name": "My OpenRouter",
            "base-url": "https://openrouter.ai/api/v1",
            "api-key-entries": [{"api-key": "sk-old"}],
            "models": [{"name": "upstream-model", "alias": "friendly-model"}],
            "prefix": "keep-me",
            "disabled": False,
        },
        {
            "name": "second",
            "base-url": "https://b.example/v1",
            "api-key-entries": [{"api-key": "sk-b"}],
            "models": [{"name": "other", "alias": "other"}],
        },
        {
            "name": "third",
            "base-url": "https://c.example/v1",
            "api-key-entries": [{"api-key": "sk-c"}],
            "models": [{"name": "third-model", "alias": "third-model"}],
        },
    ]
    await _ready(async_client)
    listed = await async_client.get("/api/cliproxy/accounts")
    accounts = listed.json()["apiKeys"]
    first, second, third = accounts

    url_only = await async_client.patch(
        "/api/cliproxy/api-keys/openai-compatibility/0",
        json={
            "kind": "openai-compatibility",
            "baseUrl": "https://openrouter.ai/api/v1",
            "accountId": first["id"],
            "disabled": True,
        },
    )
    assert url_only.status_code == 200
    stored = _FakeClient.api_key_lists["openai-compatibility"][0]
    assert stored["name"] == "My OpenRouter"
    assert stored["models"] == [{"name": "upstream-model", "alias": "friendly-model"}]
    assert stored["prefix"] == "keep-me"
    assert stored["api-key-entries"][0]["api-key"] == "sk-old"
    assert stored["disabled"] is True

    renamed = await async_client.patch(
        "/api/cliproxy/api-keys/openai-compatibility/0",
        json={
            "kind": "openai-compatibility",
            "name": "My OpenRouter",
            "baseUrl": "https://proxy.example/v1",
            "models": ["friendly-model", "added-model"],
            "accountId": url_only.json()["id"],
        },
    )
    assert renamed.status_code == 200
    stored = _FakeClient.api_key_lists["openai-compatibility"][0]
    assert stored["name"] == "My OpenRouter"
    assert stored["base-url"] == "https://proxy.example/v1"
    assert stored["models"] == [
        {"name": "upstream-model", "alias": "friendly-model"},
        {"name": "added-model", "alias": "added-model"},
    ]

    rejected_name = await async_client.patch(
        "/api/cliproxy/api-keys/openai-compatibility/0",
        json={
            "kind": "openai-compatibility",
            "name": "Still Two Words",
            "baseUrl": "https://proxy.example/v1",
            "accountId": renamed.json()["id"],
        },
    )
    assert rejected_name.status_code == 400
    assert _FakeClient.api_key_lists["openai-compatibility"][0]["name"] == "My OpenRouter"

    wrong = await async_client.patch(
        "/api/cliproxy/api-keys/openai-compatibility/1",
        json={
            "kind": "openai-compatibility",
            "baseUrl": "https://hijack.example/v1",
            "accountId": "not-the-account",
        },
    )
    assert wrong.status_code == 409
    assert _FakeClient.api_key_lists["openai-compatibility"][1]["base-url"] == "https://b.example/v1"

    removed = await async_client.request(
        "DELETE",
        "/api/cliproxy/api-keys/openai-compatibility/0",
        json={"confirm": True, "accountId": renamed.json()["id"]},
    )
    assert removed.status_code == 200
    stale = await async_client.patch(
        "/api/cliproxy/api-keys/openai-compatibility/1",
        json={
            "kind": "openai-compatibility",
            "baseUrl": "https://hijack.example/v1",
            "accountId": second["id"],
        },
    )
    assert stale.status_code == 409
    missed = await async_client.request(
        "DELETE",
        "/api/cliproxy/api-keys/openai-compatibility/1",
        json={"confirm": True, "accountId": second["id"]},
    )
    assert missed.status_code == 409
    assert [item["name"] for item in _FakeClient.api_key_lists["openai-compatibility"]] == ["second", "third"]
    assert _FakeClient.api_key_lists["openai-compatibility"][1]["base-url"] == "https://c.example/v1"


@pytest.mark.asyncio
async def test_overlapping_api_key_creates_keep_both_accounts(async_client, monkeypatch):
    _install(monkeypatch)
    await _ready(async_client)
    entered = asyncio.Event()
    release = asyncio.Event()
    paused = {"done": False}

    async def pause_first_get() -> None:
        if paused["done"]:
            return
        paused["done"] = True
        entered.set()
        await release.wait()

    _FakeClient.management_get_hook = pause_first_get

    async def create(name: str) -> None:
        response = await async_client.post(
            "/api/cliproxy/api-keys",
            json={
                "kind": "openai-compatibility",
                "name": name,
                "baseUrl": f"https://{name}.example/v1",
                "apiKey": f"sk-{name}",
                "models": [name],
            },
        )
        assert response.status_code == 200

    first = asyncio.create_task(create("alpha"))
    await asyncio.wait_for(entered.wait(), timeout=5)
    second = asyncio.create_task(create("beta"))
    await asyncio.sleep(0.2)
    assert not second.done()
    release.set()
    await first
    await second

    names = [item["name"] for item in _FakeClient.api_key_lists["openai-compatibility"]]
    assert names == ["alpha", "beta"]
    methods = [call[0] for call in _FakeClient.management_calls if call[0] in {"GET", "PUT"}]
    assert methods == ["GET", "PUT", "GET", "PUT"]


@pytest.mark.asyncio
async def test_discovered_model_is_added_to_the_existing_sidecar_catalog(async_client, monkeypatch):
    _install(monkeypatch)
    await _ready(async_client)

    added = await async_client.post("/api/cliproxy/catalog/models", json={"model": "grok-4"})
    assert added.status_code == 200
    assert added.json()["model"] == "grok-4"
    assert added.json()["fullModels"] == ["grok-4"]

    again = await async_client.post("/api/cliproxy/catalog/models", json={"model": "Grok-4"})
    assert again.status_code == 200
    assert again.json()["fullModels"] == ["grok-4"]

    settings = await async_client.get("/api/settings")
    assert settings.json()["claudeSidecarFullModels"] == ["grok-4"]
