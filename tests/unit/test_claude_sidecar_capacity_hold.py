from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from app.modules.claude_sidecar import quota_poller as quota_poller_module
from app.modules.claude_sidecar.capacity_hold import (
    StoredSnapshotReader,
    all_claude_auths_held_until,
    is_unknown_provider_message,
    next_hold_release,
    no_claude_auth_enabled,
)
from app.modules.claude_sidecar.quota import (
    SidecarAuthQuota,
    SidecarQuotaSnapshot,
    SidecarQuotaStatus,
    SidecarRateLimitHold,
    snapshot_to_json,
)
from app.modules.claude_sidecar.quota_poller import ClaudeSidecarQuotaPoller

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)


def _auth(name: str, *, disabled: bool) -> SidecarAuthQuota:
    return SidecarAuthQuota(
        name=name,
        auth_index=None,
        email=None,
        status=None,
        status_message=None,
        disabled=disabled,
        unavailable=False,
        quota_exceeded=False,
        next_recover_at=None,
        model_states=(),
        success=0,
        failed=0,
        last_refresh=None,
    )


def _hold(name: str, until: datetime, *, released: bool = False) -> SidecarRateLimitHold:
    return SidecarRateLimitHold(name=name, until=until, released=released)


def _snapshot(
    accounts: tuple[SidecarAuthQuota, ...],
    holds: tuple[SidecarRateLimitHold, ...] = (),
    *,
    status: SidecarQuotaStatus = "healthy",
) -> SidecarQuotaSnapshot:
    return SidecarQuotaSnapshot(
        checked_at=NOW,
        status=status,
        message=None,
        accounts=accounts,
        rate_limit_holds=holds,
    )


def test_every_auth_held_reports_the_earliest_release() -> None:
    snapshot = _snapshot(
        (_auth("a.json", disabled=True), _auth("b.json", disabled=True)),
        (_hold("a.json", NOW + timedelta(hours=2)), _hold("b.json", NOW + timedelta(minutes=30))),
    )

    assert all_claude_auths_held_until(snapshot) == NOW + timedelta(minutes=30)


def test_an_enabled_auth_means_no_hold() -> None:
    snapshot = _snapshot(
        (_auth("a.json", disabled=True), _auth("b.json", disabled=False)),
        (_hold("a.json", NOW + timedelta(hours=2)),),
    )

    assert all_claude_auths_held_until(snapshot) is None


def test_operator_paused_auths_are_not_a_hold() -> None:
    snapshot = _snapshot((_auth("a.json", disabled=True), _auth("b.json", disabled=True)))

    assert all_claude_auths_held_until(snapshot) is None
    assert no_claude_auth_enabled(snapshot) is True


def test_released_holds_and_holds_on_unknown_auths_are_ignored() -> None:
    snapshot = _snapshot(
        (_auth("a.json", disabled=True),),
        (
            _hold("a.json", NOW + timedelta(minutes=5), released=True),
            _hold("gone.json", NOW + timedelta(minutes=1)),
        ),
    )

    assert all_claude_auths_held_until(snapshot) is None


def test_a_past_release_is_still_reported_until_the_poller_lifts_it() -> None:
    snapshot = _snapshot((_auth("a.json", disabled=True),), (_hold("a.json", NOW - timedelta(seconds=5)),))

    assert all_claude_auths_held_until(snapshot) == NOW - timedelta(seconds=5)


@pytest.mark.parametrize(
    "snapshot",
    [None, _snapshot(()), _snapshot((_auth("a.json", disabled=True),), status="error")],
)
def test_missing_empty_or_unhealthy_snapshot_is_neither_held_nor_disabled(
    snapshot: SidecarQuotaSnapshot | None,
) -> None:
    assert all_claude_auths_held_until(snapshot) is None
    assert no_claude_auth_enabled(snapshot) is False


def test_next_hold_release_skips_past_and_released_holds() -> None:
    snapshot = _snapshot(
        (_auth("a.json", disabled=False),),
        (
            _hold("a.json", NOW - timedelta(minutes=1)),
            _hold("b.json", NOW + timedelta(minutes=1), released=True),
            _hold("c.json", NOW + timedelta(minutes=9)),
            _hold("d.json", NOW + timedelta(minutes=3)),
        ),
    )

    assert next_hold_release(snapshot, NOW) == NOW + timedelta(minutes=3)
    assert next_hold_release(None, NOW) is None


def test_unknown_provider_message_match_is_case_insensitive() -> None:
    assert is_unknown_provider_message("Unknown provider for model claude-sonnet-4-5")
    assert not is_unknown_provider_message("model not found")


def test_snapshot_reader_parses_each_distinct_value_once() -> None:
    raw = snapshot_to_json(_snapshot((_auth("a.json", disabled=True),)))
    reader = StoredSnapshotReader()

    first = reader.read(raw)
    assert first is not None and first.accounts[0].name == "a.json"
    assert reader.read(raw) is first
    assert reader.read(None) is None


@dataclass
class _Settings:
    claude_sidecar_quota_state_json: str | None


class _Cache:
    def __init__(self, raw: str | None) -> None:
        self.settings = _Settings(raw)

    async def get(self) -> _Settings:
        return self.settings


async def _poller_wait(monkeypatch: pytest.MonkeyPatch, raw: str | None) -> float:
    monkeypatch.setattr(quota_poller_module, "get_settings_cache", lambda: _Cache(raw))
    return await ClaudeSidecarQuotaPoller(interval_seconds=60.0, enabled=True)._next_wait_seconds()


async def test_poller_waits_the_full_interval_without_a_hold(monkeypatch: pytest.MonkeyPatch) -> None:
    assert await _poller_wait(monkeypatch, None) == 60.0


async def test_poller_wakes_just_after_a_near_hold_release(monkeypatch: pytest.MonkeyPatch) -> None:
    release = datetime.now(timezone.utc) + timedelta(seconds=10)
    raw = snapshot_to_json(_snapshot((_auth("a.json", disabled=True),), (_hold("a.json", release),)))

    wait = await _poller_wait(monkeypatch, raw)

    assert 9.0 < wait <= 11.0


async def test_poller_keeps_the_interval_for_a_far_hold(monkeypatch: pytest.MonkeyPatch) -> None:
    release = datetime.now(timezone.utc) + timedelta(hours=3)
    raw = snapshot_to_json(_snapshot((_auth("a.json", disabled=True),), (_hold("a.json", release),)))

    assert await _poller_wait(monkeypatch, raw) == 60.0
