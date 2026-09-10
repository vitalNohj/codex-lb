from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import DashboardSettings
from app.modules.accounts.ollama_sidecar_summary import build_ollama_sidecar_summary
from app.modules.accounts.omniroute_sidecar_summary import build_omniroute_sidecar_summary
from app.modules.accounts.openrouter_sidecar_summary import build_openrouter_sidecar_summary
from app.modules.accounts.orcarouter_sidecar_summary import build_orcarouter_sidecar_summary
from app.modules.accounts.sidecar_summary import build_claude_sidecar_summary
from app.modules.claude_sidecar.quota import (
    SidecarAuthQuota,
    SidecarQuotaSnapshot,
    snapshot_to_json,
)
from app.modules.claude_sidecar.usage_estimates import (
    ClaudeAggregateUsageEstimate,
    ClaudeAuthUsageEstimate,
    ClaudeUsageEstimates,
)


def _settings(**overrides) -> DashboardSettings:
    return DashboardSettings(id=1, **overrides)


def test_claude_auth_error_maps_to_reauth_required_badge_status() -> None:
    snapshot = SidecarQuotaSnapshot(
        checked_at=datetime(2026, 7, 25, 17, 0, tzinfo=timezone.utc),
        status="healthy",
        message=None,
        accounts=(
            SidecarAuthQuota(
                name="claude-vitalnohj@gmail.com.json",
                auth_index="8956369ab3af3441",
                email="vitalnohj@gmail.com",
                provider="claude",
                credential_path=None,
                status="error",
                status_message=(
                    '{"type":"error","error":{"type":"authentication_error",'
                    '"message":"OAuth access token has expired. Re-authenticate to continue."}}'
                ),
                disabled=False,
                unavailable=True,
                quota_exceeded=False,
                next_recover_at=None,
                model_states=(),
                success=0,
                failed=1,
                last_refresh=None,
            ),
        ),
    )
    settings = _settings(
        claude_sidecar_enabled=True,
        claude_sidecar_api_key_encrypted=b"key",
        claude_sidecar_base_url="http://127.0.0.1:8317",
        claude_sidecar_last_health_status="healthy",
        claude_sidecar_quota_state_json=snapshot_to_json(snapshot),
    )

    summary = build_claude_sidecar_summary(settings, request_usage=None)

    assert summary is not None
    assert summary.sidecar_auths[0].status == "reauth_required"


def test_claude_auth_transient_context_canceled_does_not_map_to_reauth() -> None:
    snapshot = SidecarQuotaSnapshot(
        checked_at=datetime(2026, 7, 25, 17, 0, tzinfo=timezone.utc),
        status="healthy",
        message=None,
        accounts=(
            SidecarAuthQuota(
                name="claude-vitalnohj@gmail.com.json",
                auth_index="8956369ab3af3441",
                email="vitalnohj@gmail.com",
                provider="claude",
                credential_path=None,
                status="error",
                status_message="context canceled",
                disabled=False,
                unavailable=True,
                quota_exceeded=False,
                next_recover_at=None,
                model_states=(),
                success=504,
                failed=1,
                last_refresh=None,
            ),
        ),
    )
    settings = _settings(
        claude_sidecar_enabled=True,
        claude_sidecar_api_key_encrypted=b"key",
        claude_sidecar_base_url="http://127.0.0.1:8317",
        claude_sidecar_last_health_status="healthy",
        claude_sidecar_quota_state_json=snapshot_to_json(snapshot),
    )

    summary = build_claude_sidecar_summary(settings, request_usage=None)

    assert summary is not None
    assert summary.sidecar_auths[0].status == "error"
    assert summary.sidecar_auths[0].status != "reauth_required"


def test_claude_auth_unavailable_error_without_message_maps_to_reauth() -> None:
    snapshot = SidecarQuotaSnapshot(
        checked_at=datetime(2026, 7, 25, 17, 0, tzinfo=timezone.utc),
        status="healthy",
        message=None,
        accounts=(
            SidecarAuthQuota(
                name="claude-broken.json",
                auth_index="abc",
                email="broken@example.com",
                provider="claude",
                credential_path=None,
                status="unauthorized",
                status_message=None,
                disabled=False,
                unavailable=True,
                quota_exceeded=False,
                next_recover_at=None,
                model_states=(),
                success=0,
                failed=1,
                last_refresh=None,
            ),
        ),
    )
    settings = _settings(
        claude_sidecar_enabled=True,
        claude_sidecar_api_key_encrypted=b"key",
        claude_sidecar_base_url="http://127.0.0.1:8317",
        claude_sidecar_last_health_status="healthy",
        claude_sidecar_quota_state_json=snapshot_to_json(snapshot),
    )

    summary = build_claude_sidecar_summary(settings, request_usage=None)

    assert summary is not None
    assert summary.sidecar_auths[0].status == "reauth_required"


def _claude_auth(**overrides) -> SidecarAuthQuota:
    fields: dict = {
        "name": "claude-jvwarrior@gmail.com.json",
        "auth_index": "abc",
        "email": "jvwarrior@gmail.com",
        "provider": "claude",
        "credential_path": None,
        "status": "active",
        "status_message": None,
        "disabled": False,
        "unavailable": False,
        "quota_exceeded": False,
        "next_recover_at": None,
        "model_states": (),
        "success": 1,
        "failed": 0,
        "last_refresh": None,
        "expired": None,
    }
    fields.update(overrides)
    return SidecarAuthQuota(**fields)


def _summary_for(*accounts: SidecarAuthQuota):
    snapshot = SidecarQuotaSnapshot(
        checked_at=datetime(2026, 9, 8, 21, 0, tzinfo=timezone.utc),
        status="healthy",
        message=None,
        accounts=accounts,
    )
    settings = _settings(
        claude_sidecar_enabled=True,
        claude_sidecar_api_key_encrypted=b"key",
        claude_sidecar_base_url="http://127.0.0.1:8317",
        claude_sidecar_last_health_status="healthy",
        claude_sidecar_quota_state_json=snapshot_to_json(snapshot),
    )
    return build_claude_sidecar_summary(settings, request_usage=None)


def test_claude_long_past_oauth_expiry_alone_stays_active() -> None:
    """End-user path: expiry age alone never produces a Re-auth badge.

    CLIProxyAPI renews access tokens from a background loop and publishes no
    field separating a dead refresh token from a pending refresh, an unflushed
    write or a stopped sidecar. The dashboard therefore reports the account as
    upstream describes it rather than guessing from the timestamp.
    """
    summary = _summary_for(
        _claude_auth(
            status="active",
            unavailable=False,
            expired=datetime(2026, 9, 7, 14, 5, 5, tzinfo=timezone.utc),
        )
    )

    assert summary is not None
    assert summary.sidecar_auths[0].status == "active"
    assert summary.sidecar_auths[0].status != "reauth_required"


def test_claude_transient_message_containing_unauthorized_is_not_reauth() -> None:
    summary = _summary_for(
        _claude_auth(
            status="error",
            status_message="request failed: 502 unauthorized proxy upstream",
            unavailable=True,
            failed=1,
        )
    )

    assert summary is not None
    assert summary.sidecar_auths[0].status == "error"
    assert summary.sidecar_auths[0].status != "reauth_required"


def test_claude_future_oauth_expiry_stays_active() -> None:
    summary = _summary_for(_claude_auth(expired=datetime(2099, 1, 1, tzinfo=timezone.utc)))

    assert summary is not None
    assert summary.sidecar_auths[0].status == "active"
    assert summary.sidecar_auths[0].status != "reauth_required"


def test_claude_missing_oauth_expiry_stays_active() -> None:
    summary = _summary_for(_claude_auth(expired=None, status="active", unavailable=False))

    assert summary is not None
    assert summary.sidecar_auths[0].status == "active"


def test_claude_recently_lapsed_expiry_keeps_active_on_the_dashboard() -> None:
    """End-user path: a healthy idle account whose access token just lapsed.

    CLIProxyAPI refreshes Claude tokens from a background loop, so a just-lapsed
    persisted `expired` is a pending refresh, not a dead login. The dashboard card
    must keep showing the account as usable.
    """
    summary = _summary_for(
        _claude_auth(
            status="active",
            unavailable=False,
            expired=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
    )

    assert summary is not None
    assert summary.sidecar_auths[0].status == "active"
    assert summary.sidecar_auths[0].status != "reauth_required"


def test_claude_paused_account_with_lapsed_expiry_keeps_pause_label() -> None:
    summary = _summary_for(
        _claude_auth(
            status="disabled",
            disabled=True,
            expired=datetime.now(timezone.utc) - timedelta(days=2),
        )
    )

    assert summary is not None
    assert summary.sidecar_auths[0].status == "disabled"
    assert summary.sidecar_auths[0].paused is True


def test_claude_unauthorized_status_message_maps_to_reauth_with_fresh_token() -> None:
    """A genuinely dead refresh must still badge even before the token lapses."""
    summary = _summary_for(
        _claude_auth(
            status="error",
            status_message="unauthorized",
            unavailable=True,
            failed=3,
            expired=datetime.now(timezone.utc) + timedelta(hours=2),
        )
    )

    assert summary is not None
    assert summary.sidecar_auths[0].status == "reauth_required"


def test_claude_quota_exceeded_with_lapsed_expiry_is_not_reauth() -> None:
    summary = _summary_for(
        _claude_auth(
            status="rate_limited",
            status_message="Quota exceeded",
            quota_exceeded=True,
            unavailable=True,
            failed=7,
            expired=datetime.now(timezone.utc) - timedelta(days=1),
        )
    )

    assert summary is not None
    assert summary.sidecar_auths[0].status == "rate_limited"
    assert summary.sidecar_auths[0].status != "reauth_required"


def test_claude_quota_exceeded_with_future_expiry_is_not_reauth() -> None:
    summary = _summary_for(
        _claude_auth(
            status="rate_limited",
            status_message="Quota exceeded",
            quota_exceeded=True,
            expired=datetime(2099, 1, 1, tzinfo=timezone.utc),
        )
    )

    assert summary is not None
    assert summary.sidecar_auths[0].status == "rate_limited"
    assert summary.sidecar_auths[0].status != "reauth_required"


def test_openrouter_summary_active_when_enabled_and_configured() -> None:
    settings = _settings(
        openrouter_sidecar_enabled=True,
        openrouter_sidecar_api_key_encrypted=b"key",
    )

    summary = build_openrouter_sidecar_summary(settings, request_usage=None)

    assert summary is not None
    assert summary.status == "active"


def test_openrouter_summary_active_without_health_probe() -> None:
    settings = _settings(
        openrouter_sidecar_enabled=True,
        openrouter_sidecar_api_key_encrypted=b"key",
        openrouter_sidecar_last_health_status=None,
    )

    summary = build_openrouter_sidecar_summary(settings, request_usage=None)

    assert summary is not None
    assert summary.status == "active"
    assert summary.health_status == "healthy"


def test_openrouter_summary_ignores_stale_disabled_health_when_configured() -> None:
    settings = _settings(
        openrouter_sidecar_enabled=True,
        openrouter_sidecar_api_key_encrypted=b"key",
        openrouter_sidecar_last_health_status="disabled",
    )

    summary = build_openrouter_sidecar_summary(settings, request_usage=None)

    assert summary is not None
    assert summary.status == "active"
    assert summary.health_status == "healthy"


def test_openrouter_summary_paused_when_disabled() -> None:
    settings = _settings(
        openrouter_sidecar_enabled=False,
        openrouter_sidecar_api_key_encrypted=b"key",
    )

    summary = build_openrouter_sidecar_summary(settings, request_usage=None)

    assert summary is not None
    assert summary.status == "paused"


def test_orcarouter_summary_active_when_enabled_and_configured() -> None:
    settings = _settings(
        orcarouter_sidecar_enabled=True,
        orcarouter_sidecar_api_key_encrypted=b"key",
    )

    summary = build_orcarouter_sidecar_summary(settings, request_usage=None)

    assert summary is not None
    assert summary.account_id == "orcarouter-sidecar"
    assert summary.display_name == "OrcaRouter"
    assert summary.provider == "orcarouter"
    assert summary.status == "active"


def test_orcarouter_summary_paused_when_missing_api_key() -> None:
    settings = _settings(
        orcarouter_sidecar_enabled=True,
        orcarouter_sidecar_api_key_encrypted=None,
        orcarouter_sidecar_base_url="https://api.orcarouter.ai/v1",
    )

    summary = build_orcarouter_sidecar_summary(settings, request_usage=None)

    assert summary is not None
    assert summary.display_name == "OrcaRouter"
    assert summary.status == "paused"


def test_openrouter_summary_paused_when_missing_api_key() -> None:
    settings = _settings(
        openrouter_sidecar_enabled=True,
        openrouter_sidecar_api_key_encrypted=None,
        openrouter_sidecar_base_url="https://openrouter.ai/api/v1",
    )

    summary = build_openrouter_sidecar_summary(settings, request_usage=None)

    assert summary is not None
    assert summary.status == "paused"


@pytest.mark.parametrize(
    "stored",
    [
        {"omniroute_sidecar_enabled": True, "omniroute_sidecar_api_key_encrypted": b"key"},
        {"omniroute_sidecar_enabled": False, "omniroute_sidecar_api_key_encrypted": b"key"},
        {
            "omniroute_sidecar_enabled": True,
            "omniroute_sidecar_api_key_encrypted": None,
            "omniroute_sidecar_base_url": "http://127.0.0.1:20128/v1",
        },
        {
            "omniroute_sidecar_enabled": True,
            "omniroute_sidecar_api_key_encrypted": b"key",
            "omniroute_sidecar_last_health_status": "healthy",
        },
    ],
)
def test_omniroute_summary_is_never_built_while_the_capability_is_disabled(stored) -> None:
    """No stored configuration can surface an OmniRoute account card."""

    assert build_omniroute_sidecar_summary(_settings(**stored), request_usage=None) is None


def test_ollama_summary_active_when_enabled_and_configured() -> None:
    settings = _settings(
        ollama_sidecar_enabled=True,
        ollama_sidecar_api_key_encrypted=b"key",
        ollama_sidecar_base_url="https://ollama.com",
        ollama_sidecar_last_model_count=2,
    )

    summary = build_ollama_sidecar_summary(settings, request_usage=None)

    assert summary is not None
    assert summary.account_id == "ollama-sidecar"
    assert summary.display_name == "Ollama"
    assert summary.provider == "ollama"
    assert summary.plan_type == "ollama"
    assert summary.status == "active"
    assert summary.model_count == 2
    assert summary.base_url == "https://ollama.com"


def test_ollama_summary_paused_when_missing_api_key() -> None:
    settings = _settings(
        ollama_sidecar_enabled=True,
        ollama_sidecar_api_key_encrypted=None,
        ollama_sidecar_base_url="https://ollama.com",
    )

    summary = build_ollama_sidecar_summary(settings, request_usage=None)

    assert summary is not None
    assert summary.status == "paused"


def _estimate(**overrides) -> ClaudeAuthUsageEstimate:
    base = {
        "auth_index": "0",
        "email": "a@example.com",
        "source": "a@example.com",
        "plan_type": "max_20x",
        "usage_source": "oauth_usage",
        "primary_remaining_percent": 75.0,
        "secondary_remaining_percent": 96.0,
        "primary_used_tokens": 0,
        "secondary_used_tokens": 0,
        "primary_token_budget": None,
        "secondary_token_budget": None,
        "reset_at_primary": None,
        "reset_at_secondary": None,
        "confidence": "oauth",
    }
    base.update(overrides)
    return ClaudeAuthUsageEstimate(**base)


def _claude_settings(**overrides) -> DashboardSettings:
    return _settings(
        claude_sidecar_enabled=True,
        claude_sidecar_api_key_encrypted=b"key",
        claude_sidecar_base_url="http://127.0.0.1:8317",
        claude_sidecar_last_health_status="healthy",
        **overrides,
    )


def test_estimate_only_auth_row_is_unsupported_not_a_read_failure() -> None:
    """A fresh install has no snapshot yet; those rows are not failed reads."""
    estimates = ClaudeUsageEstimates(
        accounts=[_estimate()],
        aggregate=ClaudeAggregateUsageEstimate(
            primary_remaining_percent=75.0,
            secondary_remaining_percent=96.0,
            primary_used_tokens=0,
            secondary_used_tokens=0,
            primary_token_budget=None,
            secondary_token_budget=None,
            reset_at_primary=None,
            reset_at_secondary=None,
            confidence="oauth",
        ),
    )

    summary = build_claude_sidecar_summary(_claude_settings(), request_usage=None, usage_estimates=estimates)

    assert summary is not None
    row = summary.sidecar_auths[0]
    assert row.excluded_models_state == "unsupported"
    assert row.excluded_models == []


def test_snapshot_backed_auth_row_reports_the_read_result(tmp_path, monkeypatch) -> None:
    from dataclasses import replace

    path = tmp_path / "claude-a@example.com.json"
    path.write_text('{"excluded_models": ["fresh-*"]}')
    monkeypatch.setattr("app.modules.claude_sidecar.excluded_models.default_auth_dir", lambda: tmp_path)
    snapshot = SidecarQuotaSnapshot(
        checked_at=datetime(2026, 7, 25, 17, 0, tzinfo=timezone.utc),
        status="healthy",
        message=None,
        accounts=(
            SidecarAuthQuota(
                name="claude-a@example.com.json",
                auth_index="0",
                email="a@example.com",
                provider="claude",
                credential_path=None,
                status="active",
                status_message=None,
                disabled=False,
                unavailable=False,
                quota_exceeded=False,
                next_recover_at=None,
                model_states=(),
                success=1,
                failed=0,
                last_refresh=None,
                excluded_models=("claude-demo-*",),
                excluded_models_available=True,
            ),
            SidecarAuthQuota(
                name="claude-b@example.com.json",
                auth_index="1",
                email="b@example.com",
                provider="claude",
                credential_path=None,
                status="active",
                status_message=None,
                disabled=False,
                unavailable=False,
                quota_exceeded=False,
                next_recover_at=None,
                model_states=(),
                success=1,
                failed=0,
                last_refresh=None,
                excluded_models=(),
                excluded_models_available=False,
            ),
        ),
    )

    summary = build_claude_sidecar_summary(
        _claude_settings(claude_sidecar_quota_state_json=snapshot_to_json(snapshot)),
        request_usage=None,
    )

    assert summary is not None
    states = {row.name: row.excluded_models_state for row in summary.sidecar_auths}
    assert states["claude-a@example.com.json"] == "unreadable"
    snapshot = replace(snapshot, accounts=(replace(snapshot.accounts[0], credential_path=str(path)),))
    fresh = build_claude_sidecar_summary(
        _claude_settings(claude_sidecar_quota_state_json=snapshot_to_json(snapshot)),
        request_usage=None,
    )
    assert fresh is not None
    assert fresh.sidecar_auths[0].excluded_models == ["fresh-*"]
    assert fresh.sidecar_auths[0].excluded_models_state == "available"
    assert states["claude-b@example.com.json"] == "unreadable"
