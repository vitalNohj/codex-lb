"""HTTP contract for GET /v1/quota-feed."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from app.core.auth.dashboard_access import DashboardRole
from app.core.config.settings_cache import get_settings_cache
from app.core.utils.time import utcnow
from app.db.models import Account, AccountStatus, UsageHistory
from app.db.session import SessionLocal
from app.modules.accounts.repository import AccountsRepository
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeyCreateData, ApiKeysService
from app.modules.claude_sidecar.quota import (
    GrokCreditsQuota,
    GrokCreditWindow,
    GrokTokenRollup,
    SidecarAuthQuota,
    SidecarOAuthUsage,
    SidecarOAuthUsageBucket,
    SidecarQuotaSnapshot,
    snapshot_from_json,
    snapshot_to_json,
)
from app.modules.dashboard_auth.service import DASHBOARD_SESSION_COOKIE, get_dashboard_session_store
from app.modules.proxy.load_balancer import _build_states
from app.modules.quota_feed.service import routing_state_for_auth
from app.modules.settings.repository import SettingsRepository
from app.modules.usage.repository import UsageRepository

pytestmark = pytest.mark.integration

_SECRET = "sk-clb-feed-secret-9f3a"
_EMAIL = "leak-email-9f3a@example.com"
_PREPAID = 424242
_TOKENS = 515151
_PRIMARY_RESET = 1_900_000_000
_SECONDARY_RESET = 1_910_000_000
_CLAUDE_RESET = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
_XAI_RESET = datetime(2026, 10, 20, 0, 0, tzinfo=timezone.utc)
_FORBIDDEN_KEYS = {
    "access_token",
    "accessToken",
    "refresh_token",
    "refreshToken",
    "id_token",
    "idToken",
    "token",
    "secret",
    "api_key",
    "apiKey",
    "management_key",
    "managementKey",
    "credential_path",
    "credentialPath",
    "email",
    "password",
    "authorization",
    "prefix",
    "prepaid_credits",
    "prepaidCredits",
    "total_tokens",
    "totalTokens",
}


def _account(account_id: str, *, status: AccountStatus = AccountStatus.ACTIVE) -> Account:
    return Account(
        id=account_id,
        chatgpt_account_id=f"chatgpt-{account_id}",
        email=f"{account_id}@example.com",
        plan_type="plus",
        access_token_encrypted=b"access-token-secret",
        refresh_token_encrypted=b"refresh-token-secret",
        id_token_encrypted=b"id-token-secret",
        last_refresh=utcnow(),
        status=status,
    )


def _usage(account_id: str, window: str, used_percent: float, reset_at: int, window_minutes: int) -> UsageHistory:
    return UsageHistory(
        account_id=account_id,
        recorded_at=utcnow(),
        window=window,
        used_percent=used_percent,
        reset_at=reset_at,
        window_minutes=window_minutes,
    )


def _sidecar_snapshot() -> SidecarQuotaSnapshot:
    claude = SidecarAuthQuota(
        name="claude-secret.json",
        auth_index="claude-idx",
        email=_EMAIL,
        status="ok",
        status_message=_SECRET,
        disabled=False,
        unavailable=False,
        quota_exceeded=False,
        next_recover_at=None,
        model_states=(),
        success=1,
        failed=0,
        last_refresh=None,
        provider="claude",
        prefix="acct1",
        credential_path=f"/tmp/{_SECRET}.json",
        oauth_usage=SidecarOAuthUsage(
            five_hour=SidecarOAuthUsageBucket(remaining_percent=41.0, resets_at=_CLAUDE_RESET),
            seven_day=SidecarOAuthUsageBucket(remaining_percent=88.0, resets_at=_XAI_RESET),
        ),
    )
    xai = SidecarAuthQuota(
        name="grok-secret.json",
        auth_index="xai-idx",
        email=f"xai-{_EMAIL}",
        status="ok",
        status_message=None,
        disabled=False,
        unavailable=False,
        quota_exceeded=False,
        next_recover_at=None,
        model_states=(),
        success=1,
        failed=0,
        last_refresh=None,
        provider="xai",
        prefix="acct2",
        credential_path=f"/tmp/{_SECRET}-xai.json",
        grok_credits=GrokCreditsQuota(
            windows=(
                GrokCreditWindow(
                    id="credits",
                    label="credits",
                    kind="weekly",
                    percent_used=33.0,
                    percent_remaining=67.0,
                    resets_at=_XAI_RESET,
                ),
            ),
            prepaid_credits=_PREPAID,
            token_rollup=GrokTokenRollup(total_tokens=_TOKENS, request_count=2),
        ),
    )
    unknown = SidecarAuthQuota(
        name="kimi-secret.json",
        auth_index="kimi-idx",
        email=None,
        status="ok",
        status_message=None,
        disabled=False,
        unavailable=False,
        quota_exceeded=False,
        next_recover_at=None,
        model_states=(),
        success=0,
        failed=0,
        last_refresh=None,
        provider="kimi",
        prefix="acct3",
        credential_path=f"/tmp/{_SECRET}-kimi.json",
    )
    return SidecarQuotaSnapshot(
        checked_at=datetime(2026, 10, 16, 7, 45, tzinfo=timezone.utc),
        status="healthy",
        message=None,
        accounts=(claude, xai, unknown),
    )


async def _create_key(name: str, account_ids: list[str] | None = None) -> str:
    async with SessionLocal() as session:
        created = await ApiKeysService(ApiKeysRepository(session)).create_key(
            ApiKeyCreateData(name=name, allowed_models=None, assigned_account_ids=account_ids, limits=[])
        )
    return created.key


async def _seed_pool() -> None:
    recorded = utcnow()
    async with SessionLocal() as session:
        session.add_all(
            [
                _account("acc-a"),
                _account("acc-b", status=AccountStatus.PAUSED),
                _account("acc-empty"),
                _usage("acc-a", "primary", 10.0, _PRIMARY_RESET, 300),
                _usage("acc-a", "secondary", 20.0, _SECONDARY_RESET, 10080),
                _usage("acc-b", "primary", 70.0, _PRIMARY_RESET, 300),
            ]
        )
        await session.commit()
    del recorded
    await get_settings_cache().invalidate()
    await get_settings_cache().get()
    async with SessionLocal() as session:
        await SettingsRepository(session).update(claude_sidecar_quota_state_json=snapshot_to_json(_sidecar_snapshot()))
    await get_settings_cache().invalidate()


def _install_dashboard_cookie(client) -> None:
    session_id = get_dashboard_session_store().create(
        password_verified=True,
        totp_verified=True,
        ttl_seconds=3600,
        role=DashboardRole.ADMIN,
    )
    client.cookies.set(DASHBOARD_SESSION_COOKIE, session_id)


def _codex_keys(body: dict[str, Any]) -> set[str]:
    return {row["accountKey"] for row in body["providers"] if row["provider"] == "codex"}


def _row(body: dict[str, Any], account_key: str) -> dict[str, Any]:
    return next(row for row in body["providers"] if row["accountKey"] == account_key)


def _window(body: dict[str, Any], account_key: str, window_id: str) -> dict[str, Any]:
    return next(window for window in _row(body, account_key)["windows"] if window["id"] == window_id)


def _assert_no_secrets(body: dict[str, Any], raw: str) -> None:
    keys: list[str] = []

    def walk(value: object) -> None:
        if isinstance(value, dict):
            keys.extend(value)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(body)
    assert _FORBIDDEN_KEYS.isdisjoint(keys)
    assert _SECRET not in raw
    assert _EMAIL not in raw
    assert str(_PREPAID) not in raw
    assert str(_TOKENS) not in raw
    assert "access-token-secret" not in raw


@pytest.mark.asyncio
async def test_quota_feed_rejects_missing_and_invalid_credentials(async_client) -> None:
    missing = await async_client.get("/v1/quota-feed")
    invalid = await async_client.get("/v1/quota-feed", headers={"Authorization": "Bearer not-a-real-key"})
    _install_dashboard_cookie(async_client)
    invalid_with_cookie = await async_client.get(
        "/v1/quota-feed",
        headers={"Authorization": "Bearer not-a-real-key"},
    )
    models = await async_client.get("/v1/models")
    usage = await async_client.get("/v1/usage")

    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "invalid_api_key"
    assert invalid.status_code == 401
    assert invalid.json()["error"]["message"] == "Invalid API key"
    assert invalid_with_cookie.status_code == 401
    assert "acc-" not in invalid.text
    assert models.status_code == 200
    assert usage.status_code == 401


@pytest.mark.asyncio
async def test_quota_feed_rejects_dashboard_guest(async_client) -> None:
    await _seed_pool()
    async with SessionLocal() as session:
        await SettingsRepository(session).update(guest_access_enabled=True)
    await get_settings_cache().invalidate()
    session_id = get_dashboard_session_store().create(
        password_verified=False,
        totp_verified=False,
        ttl_seconds=3600,
        role=DashboardRole.GUEST,
        guest_verified=True,
    )
    async_client.cookies.set(DASHBOARD_SESSION_COOKIE, session_id)

    response = await async_client.get("/v1/quota-feed")

    assert response.status_code == 401
    assert "acc-a" not in response.text
    assert "claude-idx" not in response.text


@pytest.mark.asyncio
async def test_quota_feed_accepts_proxy_key_and_dashboard_session(async_client) -> None:
    key = await _create_key("feed-open")

    by_key = await async_client.get("/v1/quota-feed", headers={"Authorization": f"Bearer {key}"})
    _install_dashboard_cookie(async_client)
    by_cookie = await async_client.get("/v1/quota-feed")

    assert by_key.status_code == 200
    assert by_cookie.status_code == 200
    assert by_key.json()["schemaVersion"] == 1
    assert by_key.json()["providers"] == []
    assert by_key.headers["cache-control"] == "private, max-age=15"
    assert by_key.headers["vary"] == "Authorization, Cookie"


@pytest.mark.asyncio
async def test_quota_feed_scopes_keys_and_matches_router_inputs(async_client) -> None:
    await _seed_pool()
    key_a = await _create_key("feed-a", ["acc-a"])
    key_b = await _create_key("feed-b", ["acc-b"])
    key_all = await _create_key("feed-all")

    scoped_a = await async_client.get("/v1/quota-feed", headers={"Authorization": f"Bearer {key_a}"})
    scoped_b = await async_client.get("/v1/quota-feed", headers={"Authorization": f"Bearer {key_b}"})
    unscoped = await async_client.get("/v1/quota-feed", headers={"Authorization": f"Bearer {key_all}"})
    _install_dashboard_cookie(async_client)
    dashboard = await async_client.get("/v1/quota-feed")
    claude_quota = await async_client.get("/api/claude-sidecar/quota")

    assert scoped_a.status_code == 200
    assert scoped_b.status_code == 200
    body_a = scoped_a.json()
    body_b = scoped_b.json()
    body_all = unscoped.json()
    assert _codex_keys(body_a) == {"acc-a"}
    assert _codex_keys(body_b) == {"acc-b"}
    assert "acc-b" not in scoped_a.text
    assert "acc-a" not in scoped_b.text
    assert _codex_keys(body_all) == {"acc-a", "acc-b", "acc-empty"}
    assert _codex_keys(dashboard.json()) == {"acc-a", "acc-b", "acc-empty"}

    assert body_a["perProvider"]["codex"]["accountsAvailable"] == 1
    assert body_a["perProvider"]["codex"]["maxHeadroomPercent"] == 80.0
    assert body_b["perProvider"]["codex"]["accountsAvailable"] == 0
    assert body_all["perProvider"]["codex"]["accountsAvailable"] == 2
    assert body_all["perProvider"]["codex"]["maxHeadroomPercent"] == 80.0

    five_hour = _window(body_all, "acc-a", "five_hour")
    seven_day = _window(body_all, "acc-a", "seven_day")
    empty = _window(body_all, "acc-empty", "five_hour")
    assert five_hour["confidence"] == "established"
    assert five_hour["source"] == "codex_usage"
    assert five_hour["percentRemaining"] == 90.0
    assert seven_day["id"] == "seven_day"
    assert seven_day["percentRemaining"] == 80.0
    assert empty["confidence"] == "unknown"
    assert empty["percentRemaining"] is None

    async with SessionLocal() as session:
        accounts = await AccountsRepository(session).list_accounts()
        usage = UsageRepository(session)
        states, _ = _build_states(
            accounts=accounts,
            latest_primary=await usage.latest_by_account(),
            latest_secondary=await usage.latest_by_account(window="secondary"),
            latest_monthly=await usage.latest_by_account(window="monthly"),
            runtime={},
        )
        settings = await SettingsRepository(session).get_or_create()
        raw_snapshot = settings.claude_sidecar_quota_state_json
    by_id = {state.account_id: state for state in states}
    for account_id in ("acc-a", "acc-b", "acc-empty"):
        state = by_id[account_id]
        window = _window(body_all, account_id, "five_hour")
        if state.used_percent is None:
            assert window["percentRemaining"] is None
        else:
            assert window["percentRemaining"] == pytest.approx(100.0 - state.used_percent)
        if state.primary_reset_at is None:
            assert window["resetsAt"] is None
        else:
            parsed = datetime.fromisoformat(window["resetsAt"].replace("Z", "+00:00"))
            assert parsed == datetime.fromtimestamp(state.primary_reset_at, timezone.utc)

    snapshot = snapshot_from_json(raw_snapshot)
    assert snapshot is not None
    now = datetime.now(timezone.utc)
    for auth in snapshot.accounts:
        state = routing_state_for_auth(auth, holds=(), now=now)
        assert state is not None
        row = _row(body_all, state.account_id)
        if auth.provider == "claude":
            window = _window(body_all, state.account_id, "five_hour")
            assert row["provider"] == "claude"
            assert window["source"] == "anthropic_oauth_usage"
            assert window["confidence"] == "established"
            assert window["percentRemaining"] == pytest.approx(100.0 - (state.used_percent or 0.0))
        elif auth.provider == "xai":
            window = _window(body_all, state.account_id, "credits")
            tokens = _window(body_all, state.account_id, "tokens_24h")
            assert row["provider"] == "xai"
            assert window["source"] == "grok_credits_config"
            assert window["percentRemaining"] == pytest.approx(100.0 - (state.used_percent or 0.0))
            assert tokens["confidence"] == "estimated"
            assert tokens["percentRemaining"] is None
        else:
            assert row["provider"] == "unknown"
            assert row["windows"][0]["confidence"] == "unknown"

    _assert_no_secrets(body_all, unscoped.text)
    _assert_no_secrets(body_a, scoped_a.text)
    assert claude_quota.status_code == 200
    assert claude_quota.json()["status"] == "disabled"
    assert claude_quota.json()["accounts"] == []
    assert _SECRET not in claude_quota.text
    assert "xai-idx" not in claude_quota.text
