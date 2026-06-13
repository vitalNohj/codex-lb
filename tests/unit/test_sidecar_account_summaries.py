from __future__ import annotations

from app.db.models import DashboardSettings
from app.modules.accounts.omniroute_sidecar_summary import build_omniroute_sidecar_summary
from app.modules.accounts.openrouter_sidecar_summary import build_openrouter_sidecar_summary


def _settings(**overrides) -> DashboardSettings:
    return DashboardSettings(id=1, **overrides)


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
    assert summary.health_status == "unknown"


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
