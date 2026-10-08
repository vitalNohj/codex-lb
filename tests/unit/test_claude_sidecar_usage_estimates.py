from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.modules.claude_sidecar.quota import (
    SidecarAuthQuota,
    SidecarOAuthUsage,
    SidecarOAuthUsageBucket,
    SidecarQuotaSnapshot,
)
from app.modules.claude_sidecar.usage_estimates import build_claude_usage_estimates
from app.modules.claude_sidecar.usage_queue import ClaudeSidecarUsageRecord
from app.modules.settings.service import ClaudeSidecarAuthPlanData

pytestmark = pytest.mark.unit

NOW = datetime(2026, 5, 5, 12, 0, tzinfo=timezone.utc)


def _plan(auth_index: str, primary: int = 100, secondary: int = 700) -> ClaudeSidecarAuthPlanData:
    return ClaudeSidecarAuthPlanData(
        auth_index=auth_index,
        email=f"{auth_index}@example.com",
        source=f"{auth_index}@example.com",
        plan_type="custom",
        primary_token_budget=primary,
        secondary_token_budget=secondary,
    )


def _event(
    auth_index: str,
    total_tokens: int,
    timestamp: datetime | None = None,
    *,
    failed: bool = False,
) -> ClaudeSidecarUsageRecord:
    return ClaudeSidecarUsageRecord(
        request_id=f"{auth_index}-{total_tokens}-{timestamp or NOW}",
        timestamp=timestamp or NOW - timedelta(minutes=30),
        auth_index=auth_index,
        source=f"{auth_index}@example.com",
        provider="claude",
        model="claude-sonnet",
        alias="claude",
        endpoint="POST /v1/chat/completions",
        auth_type="oauth",
        input_tokens=0,
        output_tokens=0,
        reasoning_tokens=0,
        cached_tokens=0,
        total_tokens=total_tokens,
        failed=failed,
        latency_ms=None,
    )


def _snapshot(
    auth_index: str,
    *,
    exceeded: bool = False,
    oauth_usage: SidecarOAuthUsage | None = None,
) -> SidecarQuotaSnapshot:
    return SidecarQuotaSnapshot(
        checked_at=NOW,
        status="healthy",
        message=None,
        accounts=(
            SidecarAuthQuota(
                name=f"{auth_index}@example.com",
                auth_index=auth_index,
                email=f"{auth_index}@example.com",
                status="active",
                status_message=None,
                disabled=False,
                unavailable=False,
                quota_exceeded=exceeded,
                next_recover_at=NOW + timedelta(hours=1) if exceeded else None,
                model_states=(),
                success=1,
                failed=0,
                last_refresh=NOW,
                oauth_usage=oauth_usage,
            ),
        ),
    )


def test_empty_usage_with_budget_is_full_remaining() -> None:
    estimates = build_claude_usage_estimates(
        events=[],
        plans=[_plan("auth-1")],
        snapshot=None,
        now=NOW,
    )

    assert estimates.accounts[0].primary_remaining_percent == 100.0
    assert estimates.accounts[0].secondary_remaining_percent == 100.0
    assert estimates.aggregate.primary_remaining_percent == 100.0


def test_normal_usage_calculates_remaining_percent() -> None:
    estimates = build_claude_usage_estimates(
        events=[_event("auth-1", 25)],
        plans=[_plan("auth-1")],
        snapshot=None,
        now=NOW,
    )

    account = estimates.accounts[0]
    assert account.primary_used_tokens == 25
    assert account.primary_remaining_percent == 75.0
    assert account.secondary_remaining_percent == pytest.approx(96.428571)


def test_over_budget_usage_clamps_to_zero() -> None:
    estimates = build_claude_usage_estimates(
        events=[_event("auth-1", 150)],
        plans=[_plan("auth-1")],
        snapshot=None,
        now=NOW,
    )

    assert estimates.accounts[0].primary_remaining_percent == 0.0


def test_missing_budget_leaves_percent_unknown_but_keeps_tokens() -> None:
    estimates = build_claude_usage_estimates(
        events=[_event("auth-1", 25)],
        plans=[],
        snapshot=None,
        now=NOW,
    )

    account = estimates.accounts[0]
    assert account.primary_used_tokens == 25
    assert account.primary_remaining_percent is None
    assert account.confidence == "unknown"


def test_exceeded_auth_clamps_primary_remaining_to_zero_and_uses_recover_time() -> None:
    estimates = build_claude_usage_estimates(
        events=[_event("auth-1", 25)],
        plans=[_plan("auth-1")],
        snapshot=_snapshot("auth-1", exceeded=True),
        now=NOW,
    )

    account = estimates.accounts[0]
    assert account.primary_remaining_percent == 0.0
    assert account.reset_at_primary == NOW + timedelta(hours=1)


def test_multiple_auths_aggregate_budgets_and_usage() -> None:
    estimates = build_claude_usage_estimates(
        events=[_event("auth-1", 25), _event("auth-2", 50)],
        plans=[_plan("auth-1", primary=100), _plan("auth-2", primary=100)],
        snapshot=None,
        now=NOW,
    )

    assert len(estimates.accounts) == 2
    assert estimates.aggregate.primary_used_tokens == 75
    assert estimates.aggregate.primary_token_budget == 200
    assert estimates.aggregate.primary_remaining_percent == 62.5


def test_five_hour_block_rolls_over_after_expiry() -> None:
    old = NOW - timedelta(hours=6)
    fresh = NOW - timedelta(minutes=30)
    estimates = build_claude_usage_estimates(
        events=[_event("auth-1", 80, old), _event("auth-1", 10, fresh)],
        plans=[_plan("auth-1")],
        snapshot=None,
        now=NOW,
    )

    account = estimates.accounts[0]
    assert account.primary_used_tokens == 10
    assert account.primary_remaining_percent == 90.0
    assert account.reset_at_primary == fresh + timedelta(hours=5)


def test_oauth_usage_overrides_estimated_percentages() -> None:
    five_hour_reset = NOW + timedelta(hours=2)
    seven_day_reset = NOW + timedelta(days=3)
    oauth_usage = SidecarOAuthUsage(
        five_hour=SidecarOAuthUsageBucket(remaining_percent=57.0, resets_at=five_hour_reset),
        seven_day=SidecarOAuthUsageBucket(remaining_percent=82.0, resets_at=seven_day_reset),
    )
    estimates = build_claude_usage_estimates(
        events=[_event("auth-1", 25)],
        plans=[],
        snapshot=_snapshot("auth-1", oauth_usage=oauth_usage),
        now=NOW,
    )

    account = estimates.accounts[0]
    assert account.usage_source == "oauth_usage"
    assert account.confidence == "oauth"
    assert account.primary_remaining_percent == 57.0
    assert account.secondary_remaining_percent == 82.0
    assert account.reset_at_primary == five_hour_reset
    assert account.reset_at_secondary == seven_day_reset
    assert estimates.aggregate.primary_remaining_percent == 57.0
    assert estimates.aggregate.confidence == "oauth"


@pytest.mark.parametrize("reset_at", [NOW, NOW - timedelta(hours=1), NOW.replace(tzinfo=None)])
def test_expired_weekly_oauth_usage_does_not_carry_previous_week_into_new_estimate(reset_at) -> None:
    reset_utc = reset_at.replace(tzinfo=timezone.utc) if reset_at.tzinfo is None else reset_at
    fresh = reset_utc + (NOW - reset_utc) / 2
    five_hour_reset = NOW + timedelta(hours=2)
    usage = SidecarOAuthUsage(
        five_hour=SidecarOAuthUsageBucket(remaining_percent=57.0, resets_at=five_hour_reset),
        seven_day=SidecarOAuthUsageBucket(remaining_percent=2.0, resets_at=reset_at),
    )
    estimates = build_claude_usage_estimates(
        events=[
            _event("auth-1", 686, reset_utc - timedelta(minutes=1)),
            _event("auth-1", 7, fresh),
        ],
        plans=[_plan("auth-1")],
        snapshot=_snapshot("auth-1", oauth_usage=usage),
        now=NOW,
    )

    account = estimates.accounts[0]
    assert account.primary_remaining_percent == 57.0
    assert account.reset_at_primary == five_hour_reset
    assert account.secondary_used_tokens == 7
    assert account.secondary_remaining_percent == 99.0
    assert account.reset_at_secondary == fresh + timedelta(days=7)
    assert account.usage_source == "usage_queue"
    assert account.confidence == "estimated"
    assert estimates.aggregate.secondary_remaining_percent == 99.0
    assert estimates.aggregate.reset_at_secondary == fresh + timedelta(days=7)
    assert estimates.aggregate.confidence == "estimated"


@pytest.mark.parametrize("window", ["five_hour", "seven_day"])
def test_expired_oauth_window_without_new_usage_estimates_full_quota(window) -> None:
    reset_at = NOW - timedelta(hours=1)
    expired = SidecarOAuthUsageBucket(remaining_percent=2.0, resets_at=reset_at)
    valid = SidecarOAuthUsageBucket(remaining_percent=75.0, resets_at=NOW + timedelta(days=1))
    usage = SidecarOAuthUsage(
        five_hour=expired if window == "five_hour" else valid,
        seven_day=expired if window == "seven_day" else valid,
    )
    estimates = build_claude_usage_estimates(
        events=[_event("auth-1", 686, reset_at - timedelta(minutes=1))],
        plans=[_plan("auth-1")],
        snapshot=_snapshot("auth-1", oauth_usage=usage),
        now=NOW,
    )

    account = estimates.accounts[0]
    if window == "five_hour":
        assert account.primary_remaining_percent == 100.0
        assert account.primary_used_tokens == 0
        assert account.reset_at_primary is None
        assert account.secondary_remaining_percent == 75.0
    else:
        assert account.secondary_remaining_percent == 100.0
        assert account.secondary_used_tokens == 0
        assert account.reset_at_secondary is None
        assert account.primary_remaining_percent == 75.0
    assert account.confidence == "estimated"


def test_expired_oauth_usage_without_budget_does_not_invent_remaining_quota() -> None:
    usage = SidecarOAuthUsage(
        five_hour=SidecarOAuthUsageBucket(remaining_percent=2.0, resets_at=NOW - timedelta(hours=1)),
        seven_day=SidecarOAuthUsageBucket(remaining_percent=2.0, resets_at=NOW),
    )
    estimates = build_claude_usage_estimates(
        events=[],
        plans=[],
        snapshot=_snapshot("auth-1", oauth_usage=usage),
        now=NOW,
    )

    account = estimates.accounts[0]
    assert account.primary_remaining_percent is None
    assert account.secondary_remaining_percent is None
    assert account.reset_at_primary is None
    assert account.reset_at_secondary is None
    assert account.usage_source == "usage_queue"
    assert account.confidence == "unknown"
    assert estimates.aggregate.primary_remaining_percent is None
    assert estimates.aggregate.secondary_remaining_percent is None


def test_oauth_usage_without_reset_deadline_is_retained() -> None:
    usage = SidecarOAuthUsage(
        five_hour=SidecarOAuthUsageBucket(remaining_percent=57.0, resets_at=None),
        seven_day=SidecarOAuthUsageBucket(remaining_percent=82.0, resets_at=None),
    )
    estimates = build_claude_usage_estimates(
        events=[],
        plans=[_plan("auth-1")],
        snapshot=_snapshot("auth-1", oauth_usage=usage),
        now=NOW,
    )

    assert estimates.accounts[0].primary_remaining_percent == 57.0
    assert estimates.accounts[0].secondary_remaining_percent == 82.0
    assert estimates.accounts[0].confidence == "oauth"


def test_oauth_usage_overrides_aggregate_even_with_plan_budget() -> None:
    """Regression: aggregate must not redo token math over OAuth percents.

    With a plan budget set and raw token usage far above it, the aggregate
    previously recomputed remaining percent from tokens (clamping to 0%) and
    ignored the authoritative OAuth-reported remaining percent.
    """
    oauth_usage = SidecarOAuthUsage(
        five_hour=SidecarOAuthUsageBucket(remaining_percent=33.0, resets_at=NOW + timedelta(hours=2)),
        seven_day=SidecarOAuthUsageBucket(remaining_percent=98.0, resets_at=NOW + timedelta(days=6)),
    )
    estimates = build_claude_usage_estimates(
        events=[_event("auth-1", 1_700_000)],
        plans=[_plan("auth-1", primary=40_000, secondary=280_000)],
        snapshot=_snapshot("auth-1", oauth_usage=oauth_usage),
        now=NOW,
    )

    assert estimates.accounts[0].primary_remaining_percent == 33.0
    assert estimates.aggregate.primary_remaining_percent == 33.0
    assert estimates.aggregate.secondary_remaining_percent == 98.0
    assert estimates.aggregate.confidence == "oauth"
