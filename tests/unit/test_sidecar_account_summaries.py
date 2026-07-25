from __future__ import annotations

from datetime import datetime, timezone

from app.db.models import DashboardSettings
from app.modules.accounts.ollama_sidecar_summary import build_ollama_sidecar_summary
from app.modules.accounts.omniroute_sidecar_summary import build_omniroute_sidecar_summary
from app.modules.accounts.openrouter_sidecar_summary import build_openrouter_sidecar_summary
from app.modules.accounts.sidecar_summary import build_claude_sidecar_summary
from app.modules.claude_sidecar.quota import (
    SidecarAuthQuota,
    SidecarQuotaSnapshot,
    snapshot_to_json,
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


def test_openrouter_summary_paused_when_missing_api_key() -> None:
    settings = _settings(
        openrouter_sidecar_enabled=True,
        openrouter_sidecar_api_key_encrypted=None,
        openrouter_sidecar_base_url="https://openrouter.ai/api/v1",
    )

    summary = build_openrouter_sidecar_summary(settings, request_usage=None)

    assert summary is not None
    assert summary.status == "paused"


def test_omniroute_summary_active_when_enabled_and_configured() -> None:
    settings = _settings(
        omniroute_sidecar_enabled=True,
        omniroute_sidecar_api_key_encrypted=b"key",
    )

    summary = build_omniroute_sidecar_summary(settings, request_usage=None)

    assert summary is not None
    assert summary.status == "active"


def test_omniroute_summary_paused_when_disabled() -> None:
    settings = _settings(
        omniroute_sidecar_enabled=False,
        omniroute_sidecar_api_key_encrypted=b"key",
    )

    summary = build_omniroute_sidecar_summary(settings, request_usage=None)

    assert summary is not None
    assert summary.status == "paused"


def test_omniroute_summary_paused_when_missing_api_key() -> None:
    settings = _settings(
        omniroute_sidecar_enabled=True,
        omniroute_sidecar_api_key_encrypted=None,
        omniroute_sidecar_base_url="http://127.0.0.1:20128/v1",
    )

    summary = build_omniroute_sidecar_summary(settings, request_usage=None)

    assert summary is not None
    assert summary.status == "paused"


def test_omniroute_summary_ignores_stale_missing_key_health_when_configured() -> None:
    settings = _settings(
        omniroute_sidecar_enabled=True,
        omniroute_sidecar_api_key_encrypted=b"key",
        omniroute_sidecar_last_health_status="missing_api_key",
    )

    summary = build_omniroute_sidecar_summary(settings, request_usage=None)

    assert summary is not None
    assert summary.status == "active"
    assert summary.health_status == "healthy"


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
