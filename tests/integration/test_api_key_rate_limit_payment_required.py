"""Per-key toggle that answers rate limiting with HTTP 402 instead of 429.

Reproduces the Kodus case end to end: an API key calls the real proxy routes
while every account is usage-exhausted, and codex-lb answers from account
selection without contacting the upstream.
"""

from __future__ import annotations

import base64
import json
from datetime import timezone

import pytest
from sqlalchemy import select

import app.modules.proxy.service as proxy_module
from app.core.auth import generate_unique_account_id
from app.core.utils.time import utcnow
from app.db.models import Account, AccountStatus, RequestLog
from app.db.session import SessionLocal
from app.modules.usage.repository import UsageRepository

pytestmark = pytest.mark.integration

_CHAT_PAYLOAD = {"model": "gpt-5.2", "messages": [{"role": "user", "content": "hi"}]}
_RESPONSES_PAYLOAD = {"model": "gpt-5.2", "input": "hi"}


def _encode_jwt(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    body = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    return f"header.{body}.sig"


async def _import_account(async_client, account_id: str, email: str) -> str:
    claims = {
        "email": email,
        "chatgpt_account_id": account_id,
        "https://api.openai.com/auth": {"chatgpt_plan_type": "plus"},
    }
    auth_json = {
        "tokens": {
            "idToken": _encode_jwt(claims),
            "accessToken": "access-token",
            "refreshToken": "refresh-token",
            "accountId": account_id,
        },
    }
    files = {"auth_json": ("auth.json", json.dumps(auth_json), "application/json")}
    response = await async_client.post("/api/accounts/import", files=files)
    assert response.status_code == 200
    return generate_unique_account_id(account_id, email)


async def _exhaust_account(account_id: str) -> None:
    """Put the account in the state codex-lb records after a real usage-limit hit."""

    now_epoch = int(utcnow().replace(tzinfo=timezone.utc).timestamp())
    async with SessionLocal() as session:
        usage = UsageRepository(session)
        await usage.add_entry(
            account_id=account_id,
            used_percent=100.0,
            window="primary",
            reset_at=now_epoch + 1800,
            window_minutes=300,
        )
        await usage.add_entry(
            account_id=account_id,
            used_percent=40.0,
            window="secondary",
            reset_at=now_epoch + 86400,
            window_minutes=10080,
        )
        account = await session.get(Account, account_id)
        assert account is not None
        account.status = AccountStatus.RATE_LIMITED
        account.reset_at = now_epoch + 1800
        await session.commit()


async def _enable_api_key_auth(async_client) -> None:
    current = await async_client.get("/api/settings")
    assert current.status_code == 200
    settings = current.json()
    settings["apiKeyAuthEnabled"] = True
    response = await async_client.put("/api/settings", json=settings)
    assert response.status_code == 200


async def _create_key(async_client, name: str, **fields: object) -> tuple[str, dict]:
    response = await async_client.post("/api/api-keys/", json={"name": name, **fields})
    assert response.status_code == 200
    payload = response.json()
    return payload["key"], payload


@pytest.fixture
async def exhausted_pool(async_client, monkeypatch):
    """Every account is usage-exhausted, and the upstream must never be called."""

    await _enable_api_key_auth(async_client)
    account_id = await _import_account(async_client, "acc_payment_required", "payment-required@example.com")
    await _exhaust_account(account_id)

    async def upstream_must_not_be_called(*args, **kwargs):
        raise AssertionError("an exhausted pool must be answered without contacting the upstream")
        yield  # pragma: no cover - makes this an async generator like the real client

    monkeypatch.setattr(proxy_module, "core_stream_responses", upstream_must_not_be_called)
    return account_id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "payload"),
    [("/v1/chat/completions", _CHAT_PAYLOAD), ("/v1/responses", _RESPONSES_PAYLOAD)],
)
async def test_default_key_keeps_429_for_exhausted_pool(async_client, exhausted_pool, path, payload):
    del exhausted_pool
    key, created = await _create_key(async_client, "default-key")
    assert created["rateLimitAsPaymentRequired"] is False

    response = await async_client.post(path, headers={"Authorization": f"Bearer {key}"}, json=payload)

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "usage_limit_reached"
    assert response.headers.get("retry-after") is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "payload"),
    [("/v1/chat/completions", _CHAT_PAYLOAD), ("/v1/responses", _RESPONSES_PAYLOAD)],
)
async def test_flagged_key_receives_402_with_body_and_headers_unchanged(async_client, exhausted_pool, path, payload):
    del exhausted_pool
    default_key, _ = await _create_key(async_client, "reference-key")
    flagged_key, created = await _create_key(async_client, "kodus-key", rateLimitAsPaymentRequired=True)
    assert created["rateLimitAsPaymentRequired"] is True

    reference = await async_client.post(path, headers={"Authorization": f"Bearer {default_key}"}, json=payload)
    flagged = await async_client.post(path, headers={"Authorization": f"Bearer {flagged_key}"}, json=payload)

    assert reference.status_code == 429
    assert flagged.status_code == 402
    flagged_error = flagged.json()["error"]
    reference_error = reference.json()["error"]
    assert flagged_error["code"] == "usage_limit_reached"
    assert flagged_error["message"] == reference_error["message"]
    assert flagged_error["type"] == reference_error["type"]
    assert flagged.headers.get("retry-after") is not None
    assert flagged.headers.get("content-type") == reference.headers.get("content-type")


@pytest.mark.asyncio
async def test_flagged_key_request_log_keeps_original_error(async_client, exhausted_pool):
    del exhausted_pool
    flagged_key, created = await _create_key(async_client, "kodus-log-key", rateLimitAsPaymentRequired=True)

    response = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {flagged_key}"},
        json=_CHAT_PAYLOAD,
    )
    assert response.status_code == 402

    async with SessionLocal() as session:
        rows = (await session.execute(select(RequestLog).where(RequestLog.api_key_id == created["id"]))).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "error"
    assert rows[0].error_code == "usage_limit_reached"


@pytest.mark.asyncio
async def test_flagged_key_receives_402_for_its_own_limit(async_client, monkeypatch):
    await _enable_api_key_auth(async_client)
    await _import_account(async_client, "acc_own_limit", "own-limit@example.com")
    flagged_key, _ = await _create_key(
        async_client,
        "kodus-own-limit",
        rateLimitAsPaymentRequired=True,
        limits=[{"limitType": "total_tokens", "limitWindow": "weekly", "maxValue": 10}],
    )

    async def fake_stream(payload, headers, access_token, account_id, base_url=None, raise_for_status=False, **kwargs):
        del payload, headers, access_token, account_id, base_url, raise_for_status, kwargs
        yield 'data: {"type":"response.output_text.delta","delta":"hi"}\n\n'
        yield (
            'data: {"type":"response.completed","response":{"id":"resp_own_limit",'
            '"usage":{"input_tokens":7,"output_tokens":5,"total_tokens":12}}}\n\n'
        )

    monkeypatch.setattr(proxy_module, "core_stream_responses", fake_stream)
    headers = {"Authorization": f"Bearer {flagged_key}"}

    first = await async_client.post("/v1/chat/completions", headers=headers, json=_CHAT_PAYLOAD)
    assert first.status_code == 200
    blocked = await async_client.post("/v1/chat/completions", headers=headers, json=_CHAT_PAYLOAD)

    assert blocked.status_code == 402
    assert blocked.json()["error"]["code"] == "rate_limit_exceeded"


@pytest.mark.asyncio
async def test_flagged_key_other_statuses_are_unchanged(async_client, monkeypatch):
    await _enable_api_key_auth(async_client)
    await _import_account(async_client, "acc_other_status", "other-status@example.com")
    flagged_key, _ = await _create_key(async_client, "kodus-other-status", rateLimitAsPaymentRequired=True)

    async def fake_stream(payload, headers, access_token, account_id, base_url=None, raise_for_status=False, **kwargs):
        del payload, headers, access_token, account_id, base_url, raise_for_status, kwargs
        yield 'data: {"type":"response.output_text.delta","delta":"hello"}\n\n'
        yield 'data: {"type":"response.completed","response":{"id":"resp_other_status"}}\n\n'

    monkeypatch.setattr(proxy_module, "core_stream_responses", fake_stream)
    headers = {"Authorization": f"Bearer {flagged_key}"}

    ok = await async_client.post("/v1/chat/completions", headers=headers, json=_CHAT_PAYLOAD)
    invalid = await async_client.post("/v1/chat/completions", headers=headers, json={"model": "gpt-5.2"})

    assert ok.status_code == 200
    assert ok.json()["choices"][0]["message"]["content"] == "hello"
    assert invalid.status_code in {400, 422}


@pytest.mark.asyncio
async def test_toggle_round_trips_and_takes_effect_without_restart(async_client, exhausted_pool):
    del exhausted_pool
    key, created = await _create_key(async_client, "kodus-toggle", rateLimitAsPaymentRequired=True)
    headers = {"Authorization": f"Bearer {key}"}

    enabled = await async_client.post("/v1/chat/completions", headers=headers, json=_CHAT_PAYLOAD)
    assert enabled.status_code == 402

    disabled_patch = await async_client.patch(
        f"/api/api-keys/{created['id']}", json={"rateLimitAsPaymentRequired": False}
    )
    assert disabled_patch.status_code == 200
    assert disabled_patch.json()["rateLimitAsPaymentRequired"] is False

    disabled = await async_client.post("/v1/chat/completions", headers=headers, json=_CHAT_PAYLOAD)
    assert disabled.status_code == 429


@pytest.mark.asyncio
async def test_unrelated_edit_preserves_the_flag(async_client):
    _, created = await _create_key(async_client, "kodus-rename", rateLimitAsPaymentRequired=True)

    renamed = await async_client.patch(f"/api/api-keys/{created['id']}", json={"name": "kodus-renamed"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "kodus-renamed"
    assert renamed.json()["rateLimitAsPaymentRequired"] is True

    listed = await async_client.get("/api/api-keys/")
    assert listed.status_code == 200
    [row] = [row for row in listed.json() if row["id"] == created["id"]]
    assert row["rateLimitAsPaymentRequired"] is True
