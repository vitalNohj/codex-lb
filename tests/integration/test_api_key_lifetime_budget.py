"""A one-time (lifetime) cost budget for an API key, and the rules that protect it.

A key handed to a friend gets a budget that never resets: it is spent once, and
the owner tops it up by raising its maximum. Three things keep that budget
honest:

* the lifetime limit never resets, neither in the hourly sweep nor lazily at
  admission, and ``reset usage`` does not clear it;
* a shared key with a cost budget refuses a model it cannot price, because that
  model would be served free against the budget;
* a stream the client abandons after the upstream started is charged its
  reservation instead of nothing.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy import select

import app.modules.proxy.service as proxy_service
from app.core.crypto import TokenEncryptor
from app.core.utils.time import utcnow
from app.db.models import (
    Account,
    AccountStatus,
    ApiKey,
    ApiKeyUsageReservation,
    LimitWindow,
    QuotaPlannerDecision,
)
from app.db.session import SessionLocal
from app.dependencies import _proxy_repo_context
from app.modules.api_keys.limit_windows import LIFETIME_RESET_AT
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import (
    ApiKeyRateLimitExceededError,
    ApiKeysService,
    ApiKeyUnpricedModelError,
)
from app.modules.quota_planner.logic import PlannerSettings
from app.modules.quota_planner.repository import QuotaPlannerRepository
from app.modules.quota_planner.warmup import QuotaWarmupService
from app.modules.request_logs.repository import RequestLogsRepository

pytestmark = pytest.mark.integration

_PRICED_MODEL = "gpt-5.4"
_UNPRICED_MODEL = "codex-lb-test-unpriced-model"
_BUDGET_MICRODOLLARS = 5_000_000


async def _create_key(async_client, *, name: str, shared: bool, limits: list[dict[str, object]]) -> tuple[str, str]:
    response = await async_client.post("/api/api-keys/", json={"name": name, "isShared": shared, "limits": limits})
    assert response.status_code == 200, response.text
    payload = response.json()
    return payload["id"], payload["key"]


def _lifetime_cost(max_value: int = _BUDGET_MICRODOLLARS) -> dict[str, object]:
    return {"limitType": "cost_usd", "limitWindow": "lifetime", "maxValue": max_value}


async def _limits(key_id: str):
    async with SessionLocal() as session:
        return await ApiKeysRepository(session).get_limits_by_key(key_id)


async def _set_lifetime_spend(key_id: str, current_value: int) -> None:
    async with SessionLocal() as session:
        limits = await ApiKeysRepository(session).get_limits_by_key(key_id)
        limits[0].current_value = current_value
        await session.commit()


async def _enforce(key_id: str, model: str):
    async with SessionLocal() as session:
        return await ApiKeysService(ApiKeysRepository(session)).enforce_limits_for_request(key_id, request_model=model)


async def _enable_api_key_auth(async_client) -> None:
    current = await async_client.get("/api/settings")
    assert current.status_code == 200
    settings = current.json()
    settings["apiKeyAuthEnabled"] = True
    response = await async_client.put("/api/settings", json=settings)
    assert response.status_code == 200


# --- the lifetime window ------------------------------------------------------


@pytest.mark.asyncio
async def test_lifetime_limit_is_created_with_no_reset_time(async_client):
    key_id, _ = await _create_key(async_client, name="lifetime-created", shared=True, limits=[_lifetime_cost()])

    limits = await _limits(key_id)
    assert len(limits) == 1
    assert limits[0].limit_window == LimitWindow.LIFETIME
    assert limits[0].reset_at == LIFETIME_RESET_AT

    listed = await async_client.get("/api/api-keys/")
    entry = next(item for item in listed.json() if item["id"] == key_id)
    assert entry["limits"][0]["limitWindow"] == "lifetime"
    assert entry["limits"][0]["resetAt"] is None


@pytest.mark.asyncio
async def test_lifetime_limit_never_resets_in_the_sweep_or_at_admission(async_client):
    key_id, _ = await _create_key(async_client, name="lifetime-no-reset", shared=False, limits=[_lifetime_cost()])
    await _set_lifetime_spend(key_id, 1_234_567)

    # The hourly sweep would reset anything whose reset time has passed; far in
    # the future, the lifetime sentinel must still be skipped.
    async with SessionLocal() as session:
        reset_count = await ApiKeysRepository(session).reset_expired_limits(now=utcnow() + timedelta(days=365 * 100))
    assert reset_count == 0

    # Even a lifetime row whose stamp has somehow passed is not reset, by the
    # sweep or by the lazy reset admission runs.
    async with SessionLocal() as session:
        limits = await ApiKeysRepository(session).get_limits_by_key(key_id)
        limits[0].reset_at = utcnow() - timedelta(days=1)
        await session.commit()
    async with SessionLocal() as session:
        assert await ApiKeysRepository(session).reset_expired_limits(now=utcnow()) == 0
    reservation = await _enforce(key_id, _PRICED_MODEL)
    assert reservation is not None

    limits = await _limits(key_id)
    async with SessionLocal() as session:
        reserved = await ApiKeysRepository(session).get_usage_reservation(reservation.reservation_id)
    assert reserved is not None
    assert limits[0].current_value == 1_234_567 + reserved.items[0].reserved_delta


@pytest.mark.asyncio
async def test_exhausted_lifetime_budget_says_so_without_a_reset_time(async_client):
    key_id, _ = await _create_key(async_client, name="lifetime-exhausted", shared=True, limits=[_lifetime_cost()])
    await _set_lifetime_spend(key_id, _BUDGET_MICRODOLLARS)

    with pytest.raises(ApiKeyRateLimitExceededError) as raised:
        await _enforce(key_id, _PRICED_MODEL)
    assert raised.value.reset_at is None
    assert str(raised.value) == "API key cost_usd lifetime budget exhausted"


@pytest.mark.asyncio
async def test_exhausted_lifetime_budget_is_a_terminal_402_on_the_proxy(async_client):
    await _enable_api_key_auth(async_client)
    key_id, key = await _create_key(async_client, name="lifetime-402", shared=True, limits=[_lifetime_cost()])
    await _set_lifetime_spend(key_id, _BUDGET_MICRODOLLARS)

    response = await async_client.post(
        "/v1/responses",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": _PRICED_MODEL, "input": "hi"},
    )

    assert response.status_code == 402, response.text
    error = response.json()["error"]
    assert error["code"] == "insufficient_quota"
    assert "lifetime budget exhausted" in error["message"]
    assert "resets at" not in error["message"]


@pytest.mark.asyncio
async def test_self_usage_reports_a_lifetime_limit_without_a_reset_time(async_client):
    await _enable_api_key_auth(async_client)
    key_id, key = await _create_key(async_client, name="lifetime-self-usage", shared=True, limits=[_lifetime_cost()])
    await _set_lifetime_spend(key_id, 2_000_000)

    usage = await async_client.get("/v1/usage", headers={"Authorization": f"Bearer {key}"})

    assert usage.status_code == 200, usage.text
    limit = next(item for item in usage.json()["limits"] if item["limit_window"] == "lifetime")
    assert limit["reset_at"] is None
    assert limit["current_value"] == 2_000_000
    assert limit["remaining_value"] == _BUDGET_MICRODOLLARS - 2_000_000


@pytest.mark.asyncio
async def test_reset_usage_keeps_lifetime_spend_and_raising_the_maximum_tops_it_up(async_client):
    key_id, _ = await _create_key(
        async_client,
        name="lifetime-top-up",
        shared=True,
        limits=[
            _lifetime_cost(),
            {"limitType": "total_tokens", "limitWindow": "daily", "maxValue": 1000},
        ],
    )
    async with SessionLocal() as session:
        for limit in await ApiKeysRepository(session).get_limits_by_key(key_id):
            limit.current_value = _BUDGET_MICRODOLLARS if limit.limit_window == LimitWindow.LIFETIME else 999
        await session.commit()

    reset = await async_client.patch(f"/api/api-keys/{key_id}", json={"resetUsage": True})
    assert reset.status_code == 200, reset.text
    by_window = {limit.limit_window: limit for limit in await _limits(key_id)}
    assert by_window[LimitWindow.LIFETIME].current_value == _BUDGET_MICRODOLLARS
    assert by_window[LimitWindow.LIFETIME].reset_at == LIFETIME_RESET_AT
    assert by_window[LimitWindow.DAILY].current_value == 0

    # Resubmitting the limits with reset usage still keeps the lifetime spend.
    raised = await async_client.patch(
        f"/api/api-keys/{key_id}",
        json={
            "resetUsage": True,
            "limits": [
                _lifetime_cost(_BUDGET_MICRODOLLARS * 2),
                {"limitType": "total_tokens", "limitWindow": "daily", "maxValue": 1000},
            ],
        },
    )
    assert raised.status_code == 200, raised.text
    lifetime = next(limit for limit in await _limits(key_id) if limit.limit_window == LimitWindow.LIFETIME)
    assert lifetime.current_value == _BUDGET_MICRODOLLARS
    assert lifetime.max_value == _BUDGET_MICRODOLLARS * 2
    assert await _enforce(key_id, _PRICED_MODEL) is not None


@pytest.mark.asyncio
async def test_a_lifetime_budget_added_later_counts_spend_since_the_key_was_created(async_client):
    key_id, _ = await _create_key(async_client, name="lifetime-backfill", shared=True, limits=[])
    async with SessionLocal() as session:
        created_at = (await session.execute(select(ApiKey.created_at).where(ApiKey.id == key_id))).scalar_one()
        logs = RequestLogsRepository(session)
        # Older than any rolling window, but after the key was created.
        for request_id, days_ago, cost in (("req_old", 40, 1.25), ("req_recent", 1, 0.5)):
            await logs.add_log(
                account_id=None,
                api_key_id=key_id,
                request_id=request_id,
                model=_PRICED_MODEL,
                input_tokens=10,
                output_tokens=10,
                latency_ms=10,
                status="success",
                error_code=None,
                requested_at=utcnow() - timedelta(days=days_ago),
                cost_usd=cost,
            )
        # Before the key existed: not its spend.
        await logs.add_log(
            account_id=None,
            api_key_id=key_id,
            request_id="req_before_key",
            model=_PRICED_MODEL,
            input_tokens=10,
            output_tokens=10,
            latency_ms=10,
            status="success",
            error_code=None,
            requested_at=created_at - timedelta(days=400),
            cost_usd=100.0,
        )
        await session.execute(
            ApiKey.__table__.update().where(ApiKey.id == key_id).values(created_at=utcnow() - timedelta(days=60))
        )
        await session.commit()

    updated = await async_client.patch(f"/api/api-keys/{key_id}", json={"limits": [_lifetime_cost()]})
    assert updated.status_code == 200, updated.text

    limits = await _limits(key_id)
    assert len(limits) == 1
    assert limits[0].current_value == 1_750_000
    assert limits[0].reset_at == LIFETIME_RESET_AT


# --- unpriced models ----------------------------------------------------------


@pytest.mark.asyncio
async def test_shared_key_with_a_cost_budget_refuses_an_unpriced_model(async_client):
    key_id, _ = await _create_key(async_client, name="shared-cost-unpriced", shared=True, limits=[_lifetime_cost()])

    with pytest.raises(ApiKeyUnpricedModelError):
        await _enforce(key_id, _UNPRICED_MODEL)

    # Nothing was reserved for the refused request.
    assert (await _limits(key_id))[0].current_value == 0
    async with SessionLocal() as session:
        reservations = (
            await session.execute(select(ApiKeyUsageReservation).where(ApiKeyUsageReservation.api_key_id == key_id))
        ).all()
    assert reservations == []
    # A priced model is still served.
    assert await _enforce(key_id, _PRICED_MODEL) is not None


@pytest.mark.asyncio
async def test_shared_key_refuses_an_unpriced_model_on_the_proxy(async_client):
    await _enable_api_key_auth(async_client)
    _, key = await _create_key(async_client, name="shared-cost-unpriced-proxy", shared=True, limits=[_lifetime_cost()])

    response = await async_client.post(
        "/v1/responses",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": _UNPRICED_MODEL, "input": "hi"},
    )

    assert response.status_code == 403, response.text
    error = response.json()["error"]
    assert error["code"] == "model_not_priced"
    assert _UNPRICED_MODEL in error["message"]


@pytest.mark.asyncio
async def test_a_key_that_is_not_shared_still_serves_an_unpriced_model(async_client):
    key_id, _ = await _create_key(async_client, name="unpriced-allowed-private", shared=False, limits=[_lifetime_cost()])

    await _enforce(key_id, _UNPRICED_MODEL)


@pytest.mark.asyncio
async def test_the_route_price_check_decides_for_a_shared_cost_budget_key(async_client):
    key_id, _ = await _create_key(async_client, name="route-price-check", shared=True, limits=[_lifetime_cost()])

    async def priced() -> bool:
        return True

    async def unpriced() -> bool:
        return False

    async with SessionLocal() as session:
        service = ApiKeysService(ApiKeysRepository(session))
        # A route that prices the model admits it even when the static table does not.
        assert await service.enforce_limits_for_request(key_id, request_model=_UNPRICED_MODEL, model_is_priced=priced)
        with pytest.raises(ApiKeyUnpricedModelError):
            await service.enforce_limits_for_request(key_id, request_model=_PRICED_MODEL, model_is_priced=unpriced)


@pytest.mark.asyncio
async def test_a_warmup_on_an_unpriced_model_with_a_shared_cost_budget_key_is_skipped(async_client, monkeypatch):
    # The warmup service shares one session with API-key admission, and the
    # refusal rolls that session back; the decision must still be marked
    # skipped rather than failing on the rolled-back (expired) decision row.
    key_id, _ = await _create_key(async_client, name="warmup-unpriced", shared=True, limits=[_lifetime_cost()])
    encryptor = TokenEncryptor()
    async with SessionLocal() as session:
        account = Account(
            id="acc-warm-unpriced",
            email="warm-unpriced@example.test",
            plan_type="plus",
            access_token_encrypted=encryptor.encrypt("access"),
            refresh_token_encrypted=encryptor.encrypt("refresh"),
            id_token_encrypted=encryptor.encrypt("id"),
            last_refresh=utcnow(),
            status=AccountStatus.ACTIVE,
        )
        session.add(account)
        repo = QuotaPlannerRepository(session)
        await repo.upsert_settings(
            PlannerSettings(
                mode="auto",
                allow_synthetic_traffic=True,
                dry_run=False,
                max_warmup_credits_per_day=1.0,
                warmup_model_preference=_UNPRICED_MODEL,
            )
        )
        await repo.add_window_observation(
            account_id=account.id,
            model=_UNPRICED_MODEL,
            source="warmup_probe",
            confidence="observed",
        )
        service = QuotaWarmupService(session)

        async def fail_send(self, *, account, model, request_id):
            del self, account, model, request_id
            raise AssertionError("an unpriced model should be skipped before the warmup probe is sent")

        monkeypatch.setattr(QuotaWarmupService, "_send_warmup_probe", fail_send)

        result = await service.warm_now(
            account_id=account.id,
            model=_UNPRICED_MODEL,
            api_key_id=key_id,
            force_probe=True,
        )

    assert result.status == "skipped"
    assert result.reason == "api_key_model_not_priced"
    async with SessionLocal() as session:
        decision = await session.get(QuotaPlannerDecision, result.decision_id)
    assert decision is not None
    assert decision.status == "skipped"


# --- abandoned streams ----------------------------------------------------------


async def _reservation_row(reservation_id: str) -> ApiKeyUsageReservation:
    async with SessionLocal() as session:
        row = await session.get(ApiKeyUsageReservation, reservation_id)
        assert row is not None
        return row


@pytest.mark.asyncio
async def test_charging_a_reservation_keeps_what_it_reserved(async_client):
    key_id, _ = await _create_key(async_client, name="charge-reserved", shared=True, limits=[_lifetime_cost()])
    reservation = await _enforce(key_id, _PRICED_MODEL)
    assert reservation is not None
    reserved = (await _limits(key_id))[0].current_value
    assert reserved > 0

    async with SessionLocal() as session:
        await ApiKeysService(ApiKeysRepository(session)).charge_reserved_usage(reservation.reservation_id)

    assert (await _limits(key_id))[0].current_value == reserved
    row = await _reservation_row(reservation.reservation_id)
    assert row.status == "finalized"
    assert row.cost_microdollars == reserved

    # Settling again is a no-op: the reservation is no longer held.
    async with SessionLocal() as session:
        service = ApiKeysService(ApiKeysRepository(session))
        await service.charge_reserved_usage(reservation.reservation_id)
        await service.release_usage_reservation(reservation.reservation_id)
    assert (await _limits(key_id))[0].current_value == reserved


def _proxy_service() -> proxy_service.ProxyService:
    return proxy_service.ProxyService(_proxy_repo_context)


async def _settle_codex_stream(key_id: str, *, downstream_visible: bool) -> tuple[int, ApiKeyUsageReservation]:
    reservation = await _enforce(key_id, _PRICED_MODEL)
    assert reservation is not None
    reserved = (await _limits(key_id))[0].current_value
    service = _proxy_service()
    settlement = proxy_service._StreamSettlement(status="cancelled", model=_PRICED_MODEL)
    settlement.downstream_visible = downstream_visible
    api_key = cast(proxy_service.ApiKeyData, SimpleNamespace(id=key_id))

    await service._settle_stream_api_key_usage(
        api_key, reservation, settlement, "req_abandoned", wait_for_settlement=True
    )

    return reserved, await _reservation_row(reservation.reservation_id)


@pytest.mark.asyncio
async def test_codex_stream_abandoned_after_it_started_is_charged(async_client):
    key_id, _ = await _create_key(async_client, name="codex-abandoned", shared=True, limits=[_lifetime_cost()])

    reserved, row = await _settle_codex_stream(key_id, downstream_visible=True)

    assert reserved > 0
    assert row.status == "finalized"
    assert (await _limits(key_id))[0].current_value == reserved


@pytest.mark.asyncio
async def test_codex_stream_abandoned_before_it_started_is_released(async_client):
    key_id, _ = await _create_key(async_client, name="codex-unstarted", shared=True, limits=[_lifetime_cost()])

    _, row = await _settle_codex_stream(key_id, downstream_visible=False)

    assert row.status == "released"
    assert (await _limits(key_id))[0].current_value == 0


@pytest.mark.asyncio
async def test_codex_unsettled_stream_fallback_charges_an_abandoned_stream(async_client):
    key_id, _ = await _create_key(async_client, name="codex-fallback", shared=True, limits=[_lifetime_cost()])
    reservation = await _enforce(key_id, _PRICED_MODEL)
    assert reservation is not None
    reserved = (await _limits(key_id))[0].current_value
    api_key = cast(proxy_service.ApiKeyData, SimpleNamespace(id=key_id))

    settled = await _proxy_service()._charge_abandoned_stream_api_key_usage(
        api_key=api_key,
        api_key_reservation=reservation,
        request_id="req_fallback",
    )

    assert settled is True
    assert (await _reservation_row(reservation.reservation_id)).status == "finalized"
    assert (await _limits(key_id))[0].current_value == reserved


@pytest.mark.asyncio
async def test_cliproxy_chat_stream_abandoned_mid_turn_is_charged(async_client, monkeypatch):
    from app.modules.proxy import claude_sidecar_dispatch

    key_id, _ = await _create_key(async_client, name="cliproxy-abandoned", shared=True, limits=[_lifetime_cost()])
    reservation = await _enforce(key_id, _PRICED_MODEL)
    assert reservation is not None
    reserved = (await _limits(key_id))[0].current_value

    class _Client:
        def stream_chat_completion(self, payload):
            del payload

            class _Stream:
                async def __aenter__(self):
                    async def chunks():
                        yield b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
                        yield b'data: {"choices":[{"delta":{"content":" there"}}]}\n\n'

                    return chunks()

                async def __aexit__(self, *exc):
                    return False

            return _Stream()

    monkeypatch.setattr(claude_sidecar_dispatch, "CLAUDE_SIDECAR_COOLDOWN_WAIT_SECONDS", 0.0)
    stream = claude_sidecar_dispatch._sidecar_stream_iterator(
        {"model": _PRICED_MODEL},
        reverse_tool_names={},
        api_key=cast(claude_sidecar_dispatch.ApiKeyData, SimpleNamespace(id=key_id)),
        reservation=reservation,
        model=_PRICED_MODEL,
        started_at=0.0,
        client=cast(claude_sidecar_dispatch.ClaudeSidecarClient, _Client()),
        request_payload=cast(claude_sidecar_dispatch.ChatCompletionsRequest, None),
        cursor_compat=False,
        rate_limit_headers={},
    )
    first = await stream.__anext__()
    assert b"hi" in first
    # The client leaves mid-turn: the generator is closed before the upstream ends.
    await stream.aclose()

    assert (await _reservation_row(reservation.reservation_id)).status == "finalized"
    assert (await _limits(key_id))[0].current_value == reserved


def test_codex_status_shows_a_lifetime_budget_without_a_window_or_reset():
    from app.modules.proxy.api import _codex_usage_additional_key_limits
    from app.modules.proxy.schemas import V1UsageLimitResponse

    lifetime = V1UsageLimitResponse(
        limit_type="cost_usd",
        limit_window="lifetime",
        max_value=_BUDGET_MICRODOLLARS,
        current_value=_BUDGET_MICRODOLLARS // 4,
        remaining_value=_BUDGET_MICRODOLLARS - _BUDGET_MICRODOLLARS // 4,
        reset_at=None,
    )

    [entry] = _codex_usage_additional_key_limits([lifetime], primary=())

    assert entry.quota_key == "api_key:cost_usd:lifetime"
    assert entry.rate_limit is not None
    window = entry.rate_limit.primary_window
    assert window is not None
    assert window.used_percent == 25
    assert window.reset_at is None
    assert window.limit_window_seconds is None
