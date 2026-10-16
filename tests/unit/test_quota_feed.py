"""Quota-feed rows match the account state the router selects on."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.balancer.logic import AccountState
from app.core.utils.time import utcnow
from app.db.models import Account, AccountStatus, UsageHistory
from app.modules.claude_sidecar.quota import (
    GrokCreditsQuota,
    GrokCreditWindow,
    GrokTokenRollup,
    SidecarAuthQuota,
    SidecarOAuthUsage,
    SidecarOAuthUsageBucket,
    SidecarRateLimitHold,
)
from app.modules.claude_sidecar.rate_limit_hold import XAI_LIMIT_FREE_USAGE
from app.modules.proxy.load_balancer import _build_states
from app.modules.quota_feed.service import compose_quota_feed, routing_state_for_auth

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 10, 16, 7, 45, tzinfo=timezone.utc)
_PRIMARY_RESET = 1_900_000_000
_SECONDARY_RESET = 1_910_000_000
_SECRET = "sk-clb-feed-secret-9f3a"


def _auth(
    name: str,
    auth_index: str,
    *,
    provider: str,
    prefix: str = "acct1",
    oauth: SidecarOAuthUsage | None = None,
    credits: GrokCreditsQuota | None = None,
    email: str | None = None,
    credential_path: str | None = None,
    status_message: str | None = None,
) -> SidecarAuthQuota:
    return SidecarAuthQuota(
        name=name,
        auth_index=auth_index,
        email=email,
        status="ok",
        status_message=status_message,
        disabled=False,
        unavailable=False,
        quota_exceeded=False,
        next_recover_at=None,
        model_states=(),
        success=1,
        failed=0,
        last_refresh=None,
        provider=provider,
        prefix=prefix,
        credential_path=credential_path,
        oauth_usage=oauth,
        grok_credits=credits,
    )


def _window(feed, account_key: str, window_id: str) -> dict[str, object]:
    row = next(account for account in feed.providers if account.account_key == account_key)
    return next(window for window in row.windows if window.id == window_id)


def test_codex_windows_match_router_selection_inputs() -> None:
    recorded = utcnow()
    account = Account(
        id="acc-123",
        email="hidden-codex@example.com",
        plan_type="plus",
        access_token_encrypted=b"access-token-secret",
        refresh_token_encrypted=b"refresh-token-secret",
        id_token_encrypted=b"id-token-secret",
        last_refresh=recorded,
        status=AccountStatus.ACTIVE,
    )
    primary = UsageHistory(
        account_id=account.id,
        recorded_at=recorded,
        window="primary",
        used_percent=37.5,
        reset_at=_PRIMARY_RESET,
        window_minutes=300,
    )
    secondary = UsageHistory(
        account_id=account.id,
        recorded_at=recorded,
        window="secondary",
        used_percent=12.5,
        reset_at=_SECONDARY_RESET,
        window_minutes=10080,
    )
    states, _ = _build_states(
        accounts=[account],
        latest_primary={account.id: primary},
        latest_secondary={account.id: secondary},
        latest_monthly={},
        runtime={},
    )
    state = states[0]
    feed = compose_quota_feed(
        generated_at=_NOW,
        codex_states=states,
        codex_long_window_ids={account.id: "seven_day"},
        sidecar_accounts=(),
        holds=(),
        prefixes_by_name={},
        prefixes_by_index={},
        now=_NOW,
    )

    five_hour = _window(feed, "acc-123", "five_hour")
    seven_day = _window(feed, "acc-123", "seven_day")
    assert five_hour.percent_remaining == pytest.approx(100.0 - (state.used_percent or 0.0))
    assert five_hour.confidence == "established"
    assert five_hour.source == "codex_usage"
    assert five_hour.resets_at == datetime.fromtimestamp(state.primary_reset_at, timezone.utc)
    assert seven_day.percent_remaining == pytest.approx(100.0 - (state.secondary_used_percent or 0.0))
    assert seven_day.resets_at == datetime.fromtimestamp(state.secondary_reset_at, timezone.utc)
    assert feed.per_provider["codex"].accounts_available == 1
    assert feed.per_provider["codex"].max_headroom_percent == pytest.approx(seven_day.percent_remaining)
    dumped = feed.model_dump_json()
    assert "hidden-codex@example.com" not in dumped
    assert "access-token-secret" not in dumped


def test_codex_without_usage_is_listed_unknown() -> None:
    state = AccountState("acc-empty", AccountStatus.ACTIVE)
    feed = compose_quota_feed(
        generated_at=_NOW,
        codex_states=[state],
        codex_long_window_ids={},
        sidecar_accounts=(),
        holds=(),
        prefixes_by_name={},
        prefixes_by_index={},
        now=_NOW,
    )

    five_hour = _window(feed, "acc-empty", "five_hour")
    assert five_hour.percent_remaining is None
    assert five_hour.resets_at is None
    assert five_hour.confidence == "unknown"
    assert feed.per_provider["codex"].accounts_available == 1
    assert feed.per_provider["codex"].max_headroom_percent is None


def test_paused_codex_account_is_listed_and_not_available() -> None:
    state = AccountState("acc-paused", AccountStatus.PAUSED, used_percent=10.0, primary_reset_at=_PRIMARY_RESET)
    feed = compose_quota_feed(
        generated_at=_NOW,
        codex_states=[state],
        codex_long_window_ids={"acc-paused": "monthly"},
        sidecar_accounts=(),
        holds=(),
        prefixes_by_name={},
        prefixes_by_index={},
        now=_NOW,
    )

    assert _window(feed, "acc-paused", "monthly").kind == "monthly"
    assert feed.per_provider["codex"].accounts_available == 0
    assert feed.per_provider["codex"].max_headroom_percent is None


def test_claude_xai_and_unknown_rows_match_sidecar_routing_state() -> None:
    claude_reset = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
    week_reset = datetime(2026, 10, 23, 0, 0, tzinfo=timezone.utc)
    claude = _auth(
        "claude-secret.json",
        "claude-idx",
        provider="claude",
        email=_SECRET + "@example.com",
        credential_path=f"/tmp/{_SECRET}.json",
        status_message=_SECRET,
        oauth=SidecarOAuthUsage(
            five_hour=SidecarOAuthUsageBucket(remaining_percent=41.0, resets_at=claude_reset),
            seven_day=SidecarOAuthUsageBucket(remaining_percent=88.0, resets_at=week_reset),
        ),
    )
    xai_reset = datetime(2026, 10, 20, 0, 0, tzinfo=timezone.utc)
    xai = _auth(
        "grok-secret.json",
        "xai-idx",
        provider="xai",
        email="xai-" + _SECRET,
        credits=GrokCreditsQuota(
            windows=(
                GrokCreditWindow(
                    id="product:grok",
                    label="Grok",
                    kind="product",
                    percent_used=10.0,
                    percent_remaining=90.0,
                ),
                GrokCreditWindow(
                    id="credits",
                    label="credits",
                    kind="weekly",
                    percent_used=33.0,
                    percent_remaining=67.0,
                    resets_at=xai_reset,
                ),
            ),
            prepaid_credits=424242,
            token_rollup=GrokTokenRollup(total_tokens=515151, request_count=4),
        ),
    )
    unknown = _auth(
        "kimi-secret.json",
        "kimi-idx",
        provider="kimi",
        credential_path=f"/secrets/{_SECRET}",
    )
    accounts = (claude, xai, unknown)
    feed = compose_quota_feed(
        generated_at=_NOW,
        codex_states=[],
        codex_long_window_ids={},
        sidecar_accounts=accounts,
        holds=(),
        prefixes_by_name={},
        prefixes_by_index={},
        now=_NOW,
    )

    claude_state = routing_state_for_auth(claude, holds=(), prefixes_by_name={}, prefixes_by_index={}, now=_NOW)
    xai_state = routing_state_for_auth(xai, holds=(), prefixes_by_name={}, prefixes_by_index={}, now=_NOW)
    unknown_state = routing_state_for_auth(unknown, holds=(), prefixes_by_name={}, prefixes_by_index={}, now=_NOW)
    assert claude_state is not None and xai_state is not None and unknown_state is not None

    claude_hour = _window(feed, claude_state.account_id, "five_hour")
    claude_week = _window(feed, claude_state.account_id, "seven_day")
    assert claude_hour.percent_remaining == pytest.approx(100.0 - (claude_state.used_percent or 0.0))
    assert claude_hour.confidence == "established"
    assert claude_hour.source == "anthropic_oauth_usage"
    assert claude_hour.resets_at == datetime.fromtimestamp(claude_state.reset_at, timezone.utc)
    assert claude_week.percent_remaining == pytest.approx(100.0 - (claude_state.secondary_used_percent or 0.0))
    assert claude_week.source == "anthropic_oauth_usage"

    credits = _window(feed, xai_state.account_id, "credits")
    product = _window(feed, xai_state.account_id, "product:grok")
    tokens = _window(feed, xai_state.account_id, "tokens_24h")
    assert credits.percent_remaining == pytest.approx(100.0 - (xai_state.used_percent or 0.0))
    assert credits.confidence == "established"
    assert credits.source == "grok_credits_config"
    assert credits.resets_at == datetime.fromtimestamp(xai_state.reset_at, timezone.utc)
    assert product.percent_remaining == 90.0
    assert tokens.percent_remaining is None
    assert tokens.resets_at is None
    assert tokens.confidence == "estimated"
    assert tokens.source == "usage_queue_tokens"

    unknown_row = next(account for account in feed.providers if account.account_key == unknown_state.account_id)
    assert unknown_row.provider == "unknown"
    unknown_window = unknown_row.windows[0]
    assert unknown_window.confidence == "unknown"
    assert unknown_window.percent_remaining is None
    assert unknown_window.source == "unknown"
    assert feed.per_provider["unknown"].accounts_available == 1

    dumped = feed.model_dump_json()
    assert _SECRET not in dumped
    assert "424242" not in dumped
    assert "515151" not in dumped
    assert "credential_path" not in dumped
    assert "email" not in dumped


def test_cliproxy_codex_oauth_windows_use_codex_source() -> None:
    reset = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
    auth = _auth(
        "codex-secret.json",
        "codex-idx",
        provider="codex",
        oauth=SidecarOAuthUsage(
            five_hour=SidecarOAuthUsageBucket(remaining_percent=55.0, resets_at=reset),
            seven_day=SidecarOAuthUsageBucket(remaining_percent=70.0, resets_at=reset),
        ),
    )
    state = routing_state_for_auth(auth, holds=(), prefixes_by_name={}, prefixes_by_index={}, now=_NOW)
    assert state is not None
    feed = compose_quota_feed(
        generated_at=_NOW,
        codex_states=[],
        codex_long_window_ids={},
        sidecar_accounts=(auth,),
        holds=(),
        prefixes_by_name={},
        prefixes_by_index={},
        now=_NOW,
    )

    hour = _window(feed, state.account_id, "five_hour")
    week = _window(feed, state.account_id, "seven_day")
    assert feed.providers[0].provider == "codex"
    assert hour.source == "codex_oauth_usage"
    assert hour.confidence == "established"
    assert hour.percent_remaining == pytest.approx(100.0 - (state.used_percent or 0.0))
    assert week.source == "codex_oauth_usage"
    assert week.percent_remaining == pytest.approx(100.0 - (state.secondary_used_percent or 0.0))


def test_xai_rate_limit_hold_matches_router_exhaustion() -> None:
    auth = _auth(
        "grok-held.json",
        "held-idx",
        provider="xai",
        credits=GrokCreditsQuota(
            windows=(
                GrokCreditWindow(
                    id="credits",
                    label="credits",
                    kind="weekly",
                    percent_used=33.0,
                    percent_remaining=67.0,
                    resets_at=_NOW + timedelta(days=3),
                ),
            ),
            observed_limit=XAI_LIMIT_FREE_USAGE,
        ),
    )
    hold = SidecarRateLimitHold(
        name=auth.name,
        until=_NOW + timedelta(hours=24),
        released=False,
        provider="xai",
        kind=XAI_LIMIT_FREE_USAGE,
    )
    state = routing_state_for_auth(auth, holds=(hold,), prefixes_by_name={}, prefixes_by_index={}, now=_NOW)
    assert state is not None
    feed = compose_quota_feed(
        generated_at=_NOW,
        codex_states=[],
        codex_long_window_ids={},
        sidecar_accounts=(auth,),
        holds=(hold,),
        prefixes_by_name={},
        prefixes_by_index={},
        now=_NOW,
    )

    credits = _window(feed, state.account_id, "credits")
    assert state.status == AccountStatus.RATE_LIMITED
    assert credits.percent_remaining == pytest.approx(100.0 - (state.used_percent or 0.0))
    assert credits.percent_remaining == 0.0
    assert credits.confidence == "estimated"
    assert credits.resets_at == datetime.fromtimestamp(state.reset_at, timezone.utc)
    assert feed.per_provider["xai"].accounts_available == 0
