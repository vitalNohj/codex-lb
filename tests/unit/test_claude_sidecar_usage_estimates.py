from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.modules.claude_sidecar.quota import SidecarAuthQuota, SidecarQuotaSnapshot
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


def _snapshot(auth_index: str, *, exceeded: bool = False) -> SidecarQuotaSnapshot:
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
