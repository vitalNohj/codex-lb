"""A shared API key (``is_shared``) sees only its own usage, limits and expiry.

Every endpoint an API key can reach is exercised twice with the same usage
sections (all of them): once for a shared key, which must learn nothing about
the owner's pool, and once for an unshared key, which keeps every capability
those sections grant.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock

import pytest

import app.modules.proxy.service as proxy_module
from app.core.auth import generate_unique_account_id
from app.core.clients.rate_limit_reset_credits import (
    ConsumeResetCreditResponse,
    RateLimitResetCreditsSnapshot,
    ResetCreditItem,
    ResetCreditsResponse,
)
from app.core.config.settings_cache import get_settings_cache
from app.core.openai.models import OpenAIResponsePayload
from app.core.utils.time import utcnow
from app.db.models import ApiKeyLimit, LimitType, LimitWindow
from app.db.session import SessionLocal
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.fleet import api as fleet_api
from app.modules.fleet.schemas import FleetRefreshResponse
from app.modules.rate_limit_reset_credits.store import get_rate_limit_reset_credits_store
from app.modules.usage.repository import UsageRepository
from tests.integration.compact_test_helpers import _make_auth_json

pytestmark = pytest.mark.integration

_ALL_SECTIONS = "upstream_limits,account_pool_usage,reset_credits"
_EMAIL = "owner-shared-9c1e@example.com"
_RAW_ACCOUNT_ID = "acc-shared-9c1e"
_ACCOUNT_ID = generate_unique_account_id(_RAW_ACCOUNT_ID, _EMAIL)
_REDEEM_ID = "credit-shared-9c1e"
_CREDIT_EXPIRES = datetime(2031, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
_SHARED_DENIAL_CODE = "shared_api_key_not_allowed"


@pytest.fixture(autouse=True)
async def _enable_api_key_auth(async_client):
    """Proxy routes ignore a bearer key while global key auth is off."""

    response = await async_client.put("/api/settings", json={"apiKeyAuthEnabled": True})
    assert response.status_code == 200


@pytest.fixture(autouse=True)
async def _clear_reset_credit_store():
    await get_rate_limit_reset_credits_store().invalidate()
    yield
    await get_rate_limit_reset_credits_store().invalidate()


async def _seed_owner_pool(async_client) -> None:
    """One Codex account with usage windows, credits and an available reset credit."""

    files = {"auth_json": ("auth.json", json.dumps(_make_auth_json(_RAW_ACCOUNT_ID, _EMAIL)), "application/json")}
    response = await async_client.post("/api/accounts/import", files=files)
    assert response.status_code == 200
    now = utcnow()
    now_epoch = int(now.replace(tzinfo=timezone.utc).timestamp())
    async with SessionLocal() as session:
        usage_repo = UsageRepository(session)
        await usage_repo.add_entry(
            account_id=_ACCOUNT_ID,
            used_percent=25.0,
            window="primary",
            reset_at=now_epoch + 3600,
            window_minutes=300,
            recorded_at=now,
            credits_has=True,
            credits_unlimited=False,
            credits_balance=12.5,
        )
        await usage_repo.add_entry(
            account_id=_ACCOUNT_ID,
            used_percent=40.0,
            window="secondary",
            reset_at=now_epoch + 5 * 86400,
            window_minutes=10080,
            recorded_at=now,
        )
    await get_rate_limit_reset_credits_store().set(
        _ACCOUNT_ID,
        RateLimitResetCreditsSnapshot(
            available_count=1,
            nearest_expires_at=_CREDIT_EXPIRES,
            credits=[ResetCreditItem(id=_REDEEM_ID, status="available", expires_at=_CREDIT_EXPIRES)],
        ),
    )


async def _create_key(
    async_client,
    *,
    name: str,
    shared: bool,
    usage_sections: str = _ALL_SECTIONS,
    limits: list[dict[str, object]] | None = None,
    expires_at: str | None = None,
) -> tuple[str, str]:
    body: dict[str, object] = {"name": name, "usageSections": usage_sections, "isShared": shared}
    if limits is not None:
        body["limits"] = limits
    if expires_at is not None:
        body["expiresAt"] = expires_at
    response = await async_client.post("/api/api-keys/", json=body)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["isShared"] is shared
    assert payload["usageSections"] == usage_sections
    return payload["id"], payload["key"]


def _bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def _assert_no_owner_identity(response) -> None:
    for secret in (_EMAIL, _ACCOUNT_ID, _RAW_ACCOUNT_ID, _REDEEM_ID):
        assert secret not in response.text


def _assert_shared_denial(response) -> None:
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == _SHARED_DENIAL_CODE
    _assert_no_owner_identity(response)


def _assert_dashboard_shared_denial(response) -> None:
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "permission_denied"
    _assert_no_owner_identity(response)


# --- Key management ----------------------------------------------------------


@pytest.mark.asyncio
async def test_new_keys_are_unshared_by_default(async_client) -> None:
    response = await async_client.post("/api/api-keys/", json={"name": "default-unshared"})

    assert response.status_code == 200
    assert response.json()["isShared"] is False


@pytest.mark.asyncio
async def test_shared_toggle_round_trip_keeps_usage_sections(async_client) -> None:
    key_id, key = await _create_key(async_client, name="round-trip", shared=False)

    shared = await async_client.patch(f"/api/api-keys/{key_id}", json={"isShared": True})
    assert shared.status_code == 200
    assert shared.json()["isShared"] is True
    assert shared.json()["usageSections"] == _ALL_SECTIONS
    # The cached key picks up the flag immediately.
    _assert_shared_denial(await async_client.get("/v1/reset-credit", headers=_bearer(key)))

    # Editing anything else leaves the flag alone.
    renamed = await async_client.patch(f"/api/api-keys/{key_id}", json={"name": "round-trip-renamed"})
    assert renamed.json()["isShared"] is True

    unshared = await async_client.patch(f"/api/api-keys/{key_id}", json={"isShared": False})
    assert unshared.status_code == 200
    assert unshared.json()["isShared"] is False
    assert unshared.json()["usageSections"] == _ALL_SECTIONS
    listed = await async_client.get("/api/api-keys/")
    row = next(item for item in listed.json() if item["id"] == key_id)
    assert row["isShared"] is False
    assert row["usageSections"] == _ALL_SECTIONS
    reset_credits = await async_client.get("/v1/reset-credit", headers=_bearer(key))
    assert reset_credits.status_code == 200


# --- /v1/usage ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_v1_usage_shows_shared_key_only_its_own_usage_limits_and_expiry(async_client) -> None:
    await _seed_owner_pool(async_client)
    _, key = await _create_key(
        async_client,
        name="usage-shared",
        shared=True,
        limits=[
            {"limitType": "cost_usd", "limitWindow": "daily", "maxValue": 5_000_000},
            {"limitType": "total_tokens", "limitWindow": "weekly", "maxValue": 100_000},
        ],
        expires_at="2031-03-04T05:06:07Z",
    )

    response = await async_client.get("/v1/usage", headers=_bearer(key))

    assert response.status_code == 200
    body = response.json()
    assert {(limit["limit_type"], limit["limit_window"]) for limit in body["limits"]} == {
        ("cost_usd", "daily"),
        ("total_tokens", "weekly"),
    }
    assert all(limit["source"] == "api_key_limit" for limit in body["limits"])
    cost = next(limit for limit in body["limits"] if limit["limit_type"] == "cost_usd")
    assert cost["remaining_value"] == 5_000_000
    assert body["upstream_limits"] == []
    assert body["account_pool_usage"] is None
    assert body["expires_at"] == "2031-03-04T05:06:07Z"
    assert "aggregate" not in response.text
    _assert_no_owner_identity(response)


@pytest.mark.asyncio
async def test_v1_usage_shared_key_without_limits_never_mirrors_upstream(async_client) -> None:
    await _seed_owner_pool(async_client)
    _, key = await _create_key(async_client, name="usage-shared-no-limits", shared=True)

    response = await async_client.get("/v1/usage", headers=_bearer(key))

    assert response.status_code == 200
    assert response.json()["limits"] == []
    assert response.json()["upstream_limits"] == []
    assert response.json()["account_pool_usage"] is None


@pytest.mark.asyncio
async def test_v1_usage_unshared_key_keeps_pool_sections(async_client) -> None:
    await _seed_owner_pool(async_client)
    _, key = await _create_key(async_client, name="usage-unshared", shared=False)

    response = await async_client.get("/v1/usage", headers=_bearer(key))

    assert response.status_code == 200
    body = response.json()
    assert body["upstream_limits"] != []
    assert body["account_pool_usage"] is not None


# --- /api/codex/usage --------------------------------------------------------


@pytest.mark.asyncio
async def test_codex_usage_shows_shared_key_its_own_cost_and_credit_budgets(async_client) -> None:
    await _seed_owner_pool(async_client)
    key_id, key = await _create_key(
        async_client,
        name="codex-usage-shared",
        shared=True,
        limits=[
            {"limitType": "credits", "limitWindow": "5h", "maxValue": 100},
            {"limitType": "cost_usd", "limitWindow": "daily", "maxValue": 4_000_000},
        ],
    )
    now = utcnow()
    async with SessionLocal() as session:
        await ApiKeysRepository(session).replace_limits(
            key_id,
            [
                ApiKeyLimit(
                    api_key_id=key_id,
                    limit_type=LimitType.CREDITS,
                    limit_window=LimitWindow.FIVE_HOURS,
                    max_value=100,
                    current_value=30,
                    model_filter=None,
                    reset_at=now + timedelta(hours=5),
                ),
                ApiKeyLimit(
                    api_key_id=key_id,
                    limit_type=LimitType.COST_USD,
                    limit_window=LimitWindow.DAILY,
                    max_value=4_000_000,
                    current_value=1_000_000,
                    model_filter=None,
                    reset_at=now + timedelta(days=1),
                ),
            ],
        )
        await session.commit()

    response = await async_client.get("/api/codex/usage", headers=_bearer(key))

    assert response.status_code == 200
    body = response.json()
    assert body["plan_type"] == "api_key"
    assert body["rate_limit"]["primary_window"]["used_percent"] == 30
    assert body["rate_limit_reset_credits"] is None
    [cost] = body["additional_rate_limits"]
    assert cost["limit_name"] == "api_key:cost_usd:daily"
    assert cost["metered_feature"] == "api_key_cost_usd"
    assert cost["rate_limit"]["primary_window"]["used_percent"] == 25
    assert cost["rate_limit"]["primary_window"]["limit_window_seconds"] == 86400
    _assert_no_owner_identity(response)


# --- /v1/reset-credit --------------------------------------------------------


@pytest.mark.asyncio
async def test_reset_credit_get_and_post_refuse_shared_key(async_client, monkeypatch) -> None:
    await _seed_owner_pool(async_client)
    consume_mock = AsyncMock()
    monkeypatch.setattr("app.modules.proxy.api.consume_reset_credit", consume_mock)
    _, key = await _create_key(async_client, name="reset-shared", shared=True)

    listing = await async_client.get("/v1/reset-credit", headers=_bearer(key))
    redeem = await async_client.post(
        "/v1/reset-credit",
        headers=_bearer(key),
        json={"account_id": _ACCOUNT_ID, "redeem_id": _REDEEM_ID},
    )

    _assert_shared_denial(listing)
    _assert_shared_denial(redeem)
    consume_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_reset_credit_get_and_post_work_for_unshared_key_with_section(async_client, monkeypatch) -> None:
    await _seed_owner_pool(async_client)
    _, key = await _create_key(async_client, name="reset-unshared", shared=False)
    credit = ResetCreditItem(id=_REDEEM_ID, status="available", expires_at=_CREDIT_EXPIRES)
    monkeypatch.setattr(
        "app.modules.proxy.api.fetch_reset_credits",
        AsyncMock(return_value=ResetCreditsResponse(credits=[credit], available_count=1)),
    )
    consume_mock = AsyncMock(
        return_value=ConsumeResetCreditResponse.model_validate(
            {
                "code": "reset",
                "credit": {"id": _REDEEM_ID, "status": "redeemed", "redeemed_at": "2031-01-01T00:00:00Z"},
                "windows_reset": 1,
            }
        )
    )
    monkeypatch.setattr("app.modules.proxy.api.consume_reset_credit", consume_mock)

    listing = await async_client.get("/v1/reset-credit", headers=_bearer(key))
    assert listing.status_code == 200
    assert listing.json() == [
        {
            "account_id": _ACCOUNT_ID,
            "email": _EMAIL,
            "redeem_id": _REDEEM_ID,
            "expiredAt": "2031-01-02T03:04:05Z",
        }
    ]

    redeem = await async_client.post(
        "/v1/reset-credit",
        headers=_bearer(key),
        json={"account_id": _ACCOUNT_ID, "redeem_id": _REDEEM_ID},
    )
    assert redeem.status_code == 200
    assert redeem.json()["code"] == "reset"
    consume_mock.assert_awaited_once()


# --- /api/fleet/* -------------------------------------------------------------


@pytest.mark.asyncio
async def test_fleet_endpoints_refuse_shared_key(async_client, monkeypatch) -> None:
    await _seed_owner_pool(async_client)

    async def fail_refresh(*_args, **_kwargs):
        pytest.fail("a shared key must not start an upstream refresh")

    monkeypatch.setattr(fleet_api, "_refresh_fleet_usage_with_owned_session", fail_refresh)
    _, key = await _create_key(async_client, name="fleet-shared", shared=True)

    _assert_dashboard_shared_denial(await async_client.get("/api/fleet/summary", headers=_bearer(key)))
    _assert_dashboard_shared_denial(await async_client.get("/api/fleet/observability", headers=_bearer(key)))
    _assert_dashboard_shared_denial(await async_client.post("/api/fleet/refresh", headers=_bearer(key)))


@pytest.mark.asyncio
async def test_fleet_endpoints_work_for_unshared_key_with_sections(async_client, monkeypatch) -> None:
    await _seed_owner_pool(async_client)
    refreshed: list[list[str] | None] = []

    async def fake_refresh(visible_account_ids):
        refreshed.append(visible_account_ids)
        return FleetRefreshResponse(usage_written=False, account_count=1, attempted_count=1, generated_at=utcnow())

    monkeypatch.setattr(fleet_api, "_refresh_fleet_usage_with_owned_session", fake_refresh)
    _, key = await _create_key(async_client, name="fleet-unshared", shared=False)

    summary = await async_client.get("/api/fleet/summary", headers=_bearer(key))
    observability = await async_client.get("/api/fleet/observability", headers=_bearer(key))
    refresh = await async_client.post("/api/fleet/refresh", headers=_bearer(key))

    assert summary.status_code == 200
    [account] = summary.json()["accounts"]
    assert account["accountId"] == _ACCOUNT_ID
    assert account["email"] == _EMAIL
    assert account["primary"]["remainingPercent"] == 75
    assert observability.status_code == 200
    assert observability.json()["available"] is True
    assert refresh.status_code == 200
    assert refreshed == [None]


# --- /v1/quota-feed -----------------------------------------------------------


@pytest.mark.asyncio
async def test_quota_feed_refuses_shared_key(async_client) -> None:
    await _seed_owner_pool(async_client)
    _, key = await _create_key(async_client, name="feed-shared", shared=True)

    _assert_shared_denial(await async_client.get("/v1/quota-feed", headers=_bearer(key)))


@pytest.mark.asyncio
async def test_quota_feed_lists_codex_rows_for_unshared_key_with_sections(async_client) -> None:
    await _seed_owner_pool(async_client)
    _, key = await _create_key(async_client, name="feed-unshared", shared=False)

    response = await async_client.get("/v1/quota-feed", headers=_bearer(key))

    assert response.status_code == 200
    assert "codex" in {row["provider"] for row in response.json()["providers"]}


# --- /api/oauth/usage ---------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/oauth/usage", "/api/oauth/usage/"])
async def test_oauth_usage_refuses_shared_key(async_client, path: str) -> None:
    _, key = await _create_key(async_client, name=f"oauth-shared-{path}", shared=True)

    _assert_shared_denial(await async_client.get(path, headers=_bearer(key)))


@pytest.mark.asyncio
async def test_oauth_usage_serves_unshared_key(async_client) -> None:
    _, key = await _create_key(async_client, name="oauth-unshared", shared=False)

    response = await async_client.get("/api/oauth/usage", headers=_bearer(key))

    assert response.status_code == 200
    assert "five_hour" in response.json()


# --- /v1/warmup ---------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("path", "body"), [("/v1/warmup", {"mode": "normal"}), ("/v1/warmup/normal", None)])
async def test_warmup_refuses_shared_key(async_client, monkeypatch, path: str, body: dict[str, Any] | None) -> None:
    await _seed_owner_pool(async_client)
    warmup_mock = AsyncMock()
    monkeypatch.setattr(proxy_module.ProxyService, "warmup", warmup_mock)
    _, key = await _create_key(async_client, name=f"warmup-shared-{path}", shared=True)

    response = await async_client.post(path, headers=_bearer(key), json=body)

    _assert_shared_denial(response)
    warmup_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_warmup_serves_unshared_key(async_client) -> None:
    _, key = await _create_key(async_client, name="warmup-unshared", shared=False)

    response = await async_client.post("/v1/warmup", headers=_bearer(key), json={"mode": "normal"})

    assert response.status_code == 200
    assert response.json()["mode"] == "normal"


# --- quota headers on proxied responses ----------------------------------------


async def _compact(async_client, monkeypatch, key: str):
    async def fake_compact(payload, headers, access_token, account_id):
        return OpenAIResponsePayload.model_validate({"output": []})

    monkeypatch.setattr(proxy_module, "core_compact_responses", fake_compact)
    return await async_client.post(
        "/backend-api/codex/responses/compact",
        json={"model": "gpt-5.1", "instructions": "hi", "input": []},
        headers=_bearer(key),
    )


@pytest.mark.asyncio
async def test_proxied_responses_carry_no_quota_headers_for_shared_key(async_client, monkeypatch) -> None:
    await _seed_owner_pool(async_client)
    _, key = await _create_key(async_client, name="headers-shared", shared=True)

    response = await _compact(async_client, monkeypatch, key)

    assert response.status_code == 200
    assert not [name for name in response.headers if name.lower().startswith(("x-codex-primary", "x-codex-secondary"))]
    assert not [name for name in response.headers if name.lower().startswith("x-codex-credits")]


@pytest.mark.asyncio
async def test_proxied_responses_carry_quota_headers_for_unshared_key(async_client, monkeypatch) -> None:
    await _seed_owner_pool(async_client)
    await get_settings_cache().invalidate()
    _, key = await _create_key(async_client, name="headers-unshared", shared=False)

    response = await _compact(async_client, monkeypatch, key)

    assert response.status_code == 200
    assert response.headers.get("x-codex-primary-used-percent") == "25.0"
    assert response.headers.get("x-codex-credits-has-credits") == "true"
