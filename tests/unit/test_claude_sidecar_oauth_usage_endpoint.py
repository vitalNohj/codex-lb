from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.modules.claude_sidecar.oauth_usage_response import (
    build_anthropic_oauth_usage_payload,
    utilization_from_remaining,
)
from app.modules.claude_sidecar.quota import (
    SidecarAuthQuota,
    SidecarOAuthUsage,
    SidecarOAuthUsageBucket,
    SidecarQuotaSnapshot,
    snapshot_to_json,
)
from app.modules.claude_sidecar.service import ClaudeSidecarService
from app.modules.claude_sidecar.usage_estimates import ClaudeAggregateUsageEstimate

pytestmark = pytest.mark.unit

NOW = datetime(2026, 5, 5, 12, 0, tzinfo=timezone.utc)


def test_utilization_from_remaining_inverts_and_clamps() -> None:
    assert utilization_from_remaining(67.0) == 33.0
    assert utilization_from_remaining(None) is None
    assert utilization_from_remaining(150.0) == 0.0
    assert utilization_from_remaining(-10.0) == 100.0


def test_build_anthropic_oauth_usage_payload_maps_aggregate() -> None:
    reset_primary = datetime(2026, 5, 5, 17, 0, tzinfo=timezone.utc)
    reset_secondary = datetime(2026, 5, 12, 12, 0, tzinfo=timezone.utc)
    payload = build_anthropic_oauth_usage_payload(
        ClaudeAggregateUsageEstimate(
            primary_remaining_percent=67.0,
            secondary_remaining_percent=87.0,
            primary_used_tokens=0,
            secondary_used_tokens=0,
            primary_token_budget=100,
            secondary_token_budget=700,
            reset_at_primary=reset_primary,
            reset_at_secondary=reset_secondary,
            confidence="oauth",
        )
    )

    assert payload == {
        "five_hour": {"utilization": 33.0, "resets_at": "2026-05-05T17:00:00Z"},
        "seven_day": {"utilization": 13.0, "resets_at": "2026-05-12T12:00:00Z"},
        "seven_day_opus": None,
        "seven_day_sonnet": None,
        "extra_usage": None,
    }
    assert "accounts" not in payload
    assert "email" not in payload


def test_build_anthropic_oauth_usage_payload_null_when_missing() -> None:
    payload = build_anthropic_oauth_usage_payload(None)
    assert payload["five_hour"] is None
    assert payload["seven_day"] is None
    assert payload["extra_usage"] is None


class _FakeSettingsRepo:
    def __init__(self, settings: SimpleNamespace) -> None:
        self._settings = settings

    async def get_or_create(self) -> SimpleNamespace:
        return self._settings


class _FakeUsageRepo:
    def __init__(self, events: list[object] | None = None) -> None:
        self._events = events or []

    async def list_events_since(self, _since: datetime) -> list[object]:
        return list(self._events)


def _auth(
    auth_index: str,
    *,
    disabled: bool = False,
    remaining_primary: float = 67.0,
    remaining_secondary: float = 87.0,
) -> SidecarAuthQuota:
    return SidecarAuthQuota(
        name=f"{auth_index}@example.com",
        auth_index=auth_index,
        email=f"{auth_index}@example.com",
        status="active",
        status_message=None,
        disabled=disabled,
        unavailable=False,
        quota_exceeded=False,
        next_recover_at=None,
        model_states=(),
        success=1,
        failed=0,
        last_refresh=NOW,
        oauth_usage=SidecarOAuthUsage(
            five_hour=SidecarOAuthUsageBucket(remaining_percent=remaining_primary, resets_at=NOW),
            seven_day=SidecarOAuthUsageBucket(remaining_percent=remaining_secondary, resets_at=NOW),
        ),
    )


def _settings(
    *,
    enabled: bool = True,
    management_key: str | None = "encrypted",
    accounts: tuple[SidecarAuthQuota, ...] = (),
    plans_json: str | None = None,
) -> SimpleNamespace:
    snapshot = SidecarQuotaSnapshot(
        checked_at=NOW,
        status="healthy",
        message=None,
        accounts=accounts,
    )
    return SimpleNamespace(
        claude_sidecar_enabled=enabled,
        claude_sidecar_management_key_encrypted=management_key,
        claude_sidecar_quota_state_json=snapshot_to_json(snapshot) if accounts else None,
        claude_sidecar_auth_plans_json=plans_json
        or '[{"auth_index":"active","plan_type":"pro","primary_token_budget":40000,"secondary_token_budget":280000}]',
    )


@pytest.mark.asyncio
async def test_pooled_oauth_usage_excludes_paused_auths() -> None:
    settings = _settings(
        accounts=(
            _auth("paused", disabled=True, remaining_primary=10.0, remaining_secondary=10.0),
            _auth("active", disabled=False, remaining_primary=67.0, remaining_secondary=87.0),
        ),
        plans_json=(
            '[{"auth_index":"paused","plan_type":"pro","primary_token_budget":40000,"secondary_token_budget":280000},'
            '{"auth_index":"active","plan_type":"pro","primary_token_budget":40000,"secondary_token_budget":280000}]'
        ),
    )
    service = ClaudeSidecarService(_FakeSettingsRepo(settings), _FakeUsageRepo())
    payload = await service.get_pooled_oauth_usage_payload()

    assert payload["five_hour"]["utilization"] == 33.0
    assert payload["seven_day"]["utilization"] == 13.0


@pytest.mark.asyncio
async def test_pooled_oauth_usage_null_when_disabled() -> None:
    service = ClaudeSidecarService(_FakeSettingsRepo(_settings(enabled=False, accounts=(_auth("active"),))))
    payload = await service.get_pooled_oauth_usage_payload()
    assert payload["five_hour"] is None
    assert payload["seven_day"] is None


@pytest.mark.asyncio
async def test_pooled_oauth_usage_null_when_hide_upstream() -> None:
    service = ClaudeSidecarService(_FakeSettingsRepo(_settings(accounts=(_auth("active"),))))
    payload = await service.get_pooled_oauth_usage_payload(hide_upstream=True)
    assert payload["five_hour"] is None
    assert payload["seven_day"] is None
