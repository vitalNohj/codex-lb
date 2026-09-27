from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.modules.claude_sidecar.quota import (
    SidecarAuthQuota,
    SidecarOAuthUsage,
    SidecarOAuthUsageBucket,
    SidecarQuotaSnapshot,
    SidecarRateLimitHold,
    snapshot_from_json,
    snapshot_to_json,
)
from app.modules.claude_sidecar.rate_limit_hold import (
    apply_hold_results,
    plan_rate_limit_holds,
    rate_limit_hold_until,
)
from app.modules.settings.repository import SettingsRepository

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 26, 2, 0, tzinfo=timezone.utc)
_FUTURE = datetime(2026, 9, 26, 3, 0, tzinfo=timezone.utc)
_LATER = datetime(2026, 9, 27, 2, 0, tzinfo=timezone.utc)
_PAST = datetime(2026, 9, 26, 1, 0, tzinfo=timezone.utc)
_NAME = "claude-a@example.com.json"


def _bucket(remaining: float | None, resets_at: datetime | None) -> SidecarOAuthUsageBucket:
    return SidecarOAuthUsageBucket(remaining_percent=remaining, resets_at=resets_at)


def _auth(
    *,
    disabled: bool = False,
    five_hour: SidecarOAuthUsageBucket | None = None,
    seven_day: SidecarOAuthUsageBucket | None = None,
    status_message: str | None = None,
    name: str = _NAME,
) -> SidecarAuthQuota:
    usage = None
    if five_hour is not None or seven_day is not None:
        usage = SidecarOAuthUsage(five_hour=five_hour, seven_day=seven_day)
    return SidecarAuthQuota(
        name=name,
        auth_index="1",
        email="a@example.com",
        status="error",
        status_message=status_message,
        disabled=disabled,
        unavailable=False,
        quota_exceeded=False,
        next_recover_at=None,
        model_states=(),
        success=0,
        failed=0,
        last_refresh=None,
        oauth_usage=usage,
    )


def test_hold_until_uses_the_later_exhausted_reset() -> None:
    account = _auth(
        five_hour=_bucket(0, _FUTURE),
        seven_day=_bucket(0, _LATER),
    )

    assert rate_limit_hold_until(account, _NOW) == _LATER


def test_hold_until_ignores_a_window_that_still_has_remaining() -> None:
    account = _auth(
        five_hour=_bucket(0, _FUTURE),
        seven_day=_bucket(70, _LATER),
        status_message="rate_limit_error",
    )

    assert rate_limit_hold_until(account, _NOW) == _FUTURE


def test_hold_until_is_none_without_a_future_reset() -> None:
    missing = _auth(five_hour=_bucket(0, None), seven_day=_bucket(80, _LATER))
    past = _auth(five_hour=_bucket(0, _PAST), seven_day=_bucket(80, _LATER))
    recovered = _auth(
        five_hour=_bucket(12, _FUTURE),
        seven_day=_bucket(40, _LATER),
        status_message="rate_limit_error",
    )

    assert rate_limit_hold_until(missing, _NOW) is None
    assert rate_limit_hold_until(past, _NOW) is None
    assert rate_limit_hold_until(recovered, _NOW) is None


def test_plan_holds_until_the_later_exhausted_reset() -> None:
    account = _auth(five_hour=_bucket(0, _FUTURE), seven_day=_bucket(0, _LATER))

    plan = plan_rate_limit_holds((account,), (), _NOW)

    assert plan.disable_names == (_NAME,)
    assert plan.holds == (SidecarRateLimitHold(name=_NAME, until=_LATER, released=False),)


def test_plan_does_not_adopt_an_operator_pause() -> None:
    account = _auth(disabled=True, five_hour=_bucket(0, _FUTURE), seven_day=_bucket(70, _LATER))

    plan = plan_rate_limit_holds((account,), (), _NOW)

    assert plan.disable_names == ()
    assert plan.enable_names == ()
    assert plan.holds == ()


def test_plan_keeps_an_unreleased_hold_when_usage_is_unknown() -> None:
    account = _auth(disabled=True)
    hold = SidecarRateLimitHold(name=_NAME, until=_FUTURE, released=False)

    plan = plan_rate_limit_holds((account,), (hold,), _NOW)

    assert plan.enable_names == ()
    assert plan.disable_names == ()
    assert plan.holds == (hold,)


def test_plan_enables_unknown_usage_after_the_stored_reset() -> None:
    account = _auth(disabled=True)
    hold = SidecarRateLimitHold(name=_NAME, until=_PAST, released=False)

    plan = plan_rate_limit_holds((account,), (hold,), _NOW)

    assert plan.enable_names == (_NAME,)
    assert plan.holds == ()


def test_apply_keeps_a_hold_for_an_auth_missing_from_the_listing() -> None:
    present = _auth(name="claude-b.json", five_hour=_bucket(50, _FUTURE), seven_day=_bucket(80, _LATER))
    hold = SidecarRateLimitHold(name=_NAME, until=_FUTURE, released=False)
    plan = plan_rate_limit_holds((present,), (hold,), _NOW)

    _accounts, holds = apply_hold_results(
        (present,),
        (hold,),
        plan,
        failed_disables=set(),
        failed_enables=set(),
    )

    assert holds == (hold,)


def test_plan_enables_only_an_owned_hold_after_the_window_clears() -> None:
    account = _auth(disabled=True, five_hour=_bucket(30, _FUTURE), seven_day=_bucket(70, _LATER))
    hold = SidecarRateLimitHold(name=_NAME, until=_FUTURE, released=False)

    plan = plan_rate_limit_holds((account,), (hold,), _NOW)

    assert plan.enable_names == (_NAME,)
    assert plan.holds == ()


def test_snapshot_round_trips_a_hold_and_loads_older_json_without_one() -> None:
    snapshot = SidecarQuotaSnapshot(
        checked_at=_NOW,
        status="healthy",
        message=None,
        accounts=(_auth(five_hour=_bucket(0, _FUTURE)),),
        rate_limit_holds=(SidecarRateLimitHold(name=_NAME, until=_FUTURE, released=True),),
    )

    loaded = snapshot_from_json(snapshot_to_json(snapshot))

    assert loaded is not None
    assert loaded.rate_limit_holds == snapshot.rate_limit_holds

    payload = json.loads(snapshot_to_json(snapshot))
    del payload["rate_limit_holds"]
    decoded = snapshot_from_json(json.dumps(payload))
    assert decoded is not None
    assert decoded.rate_limit_holds == ()


@pytest.mark.asyncio
async def test_resume_records_a_released_hold_for_the_current_reset(monkeypatch) -> None:
    from app.modules.claude_sidecar.service import ClaudeSidecarService

    account = _auth(disabled=True, five_hour=_bucket(0, _FUTURE), seven_day=_bucket(70, _LATER))
    snapshot = SidecarQuotaSnapshot(
        checked_at=_NOW,
        status="healthy",
        message=None,
        accounts=(account,),
        rate_limit_holds=(SidecarRateLimitHold(name=_NAME, until=_FUTURE, released=False),),
    )
    settings = SimpleNamespace(claude_sidecar_quota_state_json=snapshot_to_json(snapshot))

    async def update_operational(**kwargs):
        settings.claude_sidecar_quota_state_json = kwargs["claude_sidecar_quota_state_json"]

    repo = Mock(spec=SettingsRepository)
    repo.get_fresh = AsyncMock(return_value=settings)
    repo.update_operational = AsyncMock(side_effect=update_operational)
    monkeypatch.setattr(
        "app.modules.claude_sidecar.service.get_settings_cache",
        lambda: SimpleNamespace(invalidate=AsyncMock()),
    )
    monkeypatch.setattr(
        "app.modules.claude_sidecar.service.datetime",
        SimpleNamespace(now=lambda tz=None: _NOW),
    )

    await ClaudeSidecarService(repo)._patch_snapshot_disabled_locked(_NAME, False)

    loaded = snapshot_from_json(settings.claude_sidecar_quota_state_json)
    assert loaded is not None
    assert loaded.accounts[0].disabled is False
    assert loaded.rate_limit_holds == (SidecarRateLimitHold(name=_NAME, until=_FUTURE, released=True),)

    follow_up = plan_rate_limit_holds(loaded.accounts, loaded.rate_limit_holds, _NOW)
    assert follow_up.disable_names == ()


@pytest.mark.asyncio
async def test_pause_drops_an_existing_hold(monkeypatch) -> None:
    from app.modules.claude_sidecar.service import ClaudeSidecarService

    hold = SidecarRateLimitHold(name=_NAME, until=_FUTURE, released=False)
    account = _auth(disabled=False, five_hour=_bucket(40, _FUTURE), seven_day=_bucket(70, _LATER))
    snapshot = SidecarQuotaSnapshot(
        checked_at=_NOW,
        status="healthy",
        message=None,
        accounts=(account,),
        rate_limit_holds=(hold,),
    )
    settings = SimpleNamespace(claude_sidecar_quota_state_json=snapshot_to_json(snapshot))

    async def update_operational(**kwargs):
        settings.claude_sidecar_quota_state_json = kwargs["claude_sidecar_quota_state_json"]

    repo = Mock(spec=SettingsRepository)
    repo.get_fresh = AsyncMock(return_value=settings)
    repo.update_operational = AsyncMock(side_effect=update_operational)
    monkeypatch.setattr(
        "app.modules.claude_sidecar.service.get_settings_cache",
        lambda: SimpleNamespace(invalidate=AsyncMock()),
    )

    await ClaudeSidecarService(repo)._patch_snapshot_disabled_locked(_NAME, True)

    loaded = snapshot_from_json(settings.claude_sidecar_quota_state_json)
    assert loaded is not None
    assert loaded.accounts[0].disabled is True
    assert loaded.rate_limit_holds == ()

    follow_up = plan_rate_limit_holds(loaded.accounts, loaded.rate_limit_holds, _NOW)
    assert follow_up.enable_names == ()


@pytest.mark.asyncio
async def test_resume_without_usage_releases_the_stored_hold(monkeypatch) -> None:
    from app.modules.claude_sidecar.service import ClaudeSidecarService

    hold = SidecarRateLimitHold(name=_NAME, until=_FUTURE, released=False)
    snapshot = SidecarQuotaSnapshot(
        checked_at=_NOW,
        status="unreachable",
        message="down",
        accounts=(),
        rate_limit_holds=(hold,),
    )
    settings = SimpleNamespace(claude_sidecar_quota_state_json=snapshot_to_json(snapshot))

    async def update_operational(**kwargs):
        settings.claude_sidecar_quota_state_json = kwargs["claude_sidecar_quota_state_json"]

    repo = Mock(spec=SettingsRepository)
    repo.get_fresh = AsyncMock(return_value=settings)
    repo.update_operational = AsyncMock(side_effect=update_operational)
    monkeypatch.setattr(
        "app.modules.claude_sidecar.service.get_settings_cache",
        lambda: SimpleNamespace(invalidate=AsyncMock()),
    )

    await ClaudeSidecarService(repo)._patch_snapshot_disabled_locked(_NAME, False)

    loaded = snapshot_from_json(settings.claude_sidecar_quota_state_json)
    assert loaded is not None
    assert loaded.rate_limit_holds == (SidecarRateLimitHold(name=_NAME, until=_FUTURE, released=True),)
