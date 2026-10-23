from __future__ import annotations

import json
from types import SimpleNamespace
from typing import cast

import pytest

import app.modules.settings.service as settings_service_module
from app.core.clients.claude_sidecar import SidecarPrefix
from app.core.config.dashboard_overrides import DASHBOARD_TIMEOUT_SETTINGS
from app.core.config.settings import Settings
from app.db.models import DashboardSettings, DashboardUser
from app.modules.openai_compat.endpoints import OpenAICompatEndpointUpdateData
from app.modules.settings.repository import SettingsRepository
from app.modules.settings.service import (
    DashboardSettingsUpdateData,
    InheritableValue,
    SettingSource,
    SettingsService,
    SidecarRoutingConflictError,
    _dump_additional_quota_routing_policies,
    _dump_claude_sidecar_model_prefixes,
    _dump_sidecar_full_models,
    _parse_additional_quota_routing_policies,
    _parse_claude_sidecar_model_prefixes,
    _parse_sidecar_full_models,
    _validate_unique_sidecar_routes,
    resolve_inheritable,
)

pytestmark = pytest.mark.unit


def _validate_routes(
    payload: DashboardSettingsUpdateData, stored_stars: dict[str, str] | None = None
) -> dict[str, str]:
    """Run the save-time route validation the way the service does.

    Returns the effective star map so star-filtering assertions read like the
    service's own return value.
    """

    return _validate_unique_sidecar_routes(payload, stored_full_model_stars=stored_stars or {})


def test_resolve_inheritable_null_column_uses_environment_when_it_differs_from_default() -> None:
    assert resolve_inheritable(None, 12, 8) == InheritableValue(12, "env", 12, 8)


def test_resolve_inheritable_null_column_reports_default_when_environment_matches_default() -> None:
    assert resolve_inheritable(None, 8, 8) == InheritableValue(8, "default", 8, 8)
    # Database-only settings have no environment layer at all.
    assert resolve_inheritable(None, None, 0) == InheritableValue(0, "default", None, 0)


def test_resolve_inheritable_dashboard_value_wins_including_zero() -> None:
    assert resolve_inheritable(24, 12, 8) == InheritableValue(24, "dashboard", 12, 8)
    assert resolve_inheritable(0, 12, 8) == InheritableValue(0, "dashboard", 12, 8)
    assert resolve_inheritable(0, None, 0) == InheritableValue(0, "dashboard", None, 0)


@pytest.mark.asyncio
async def test_settings_data_reports_provenance_for_every_inheritable_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = DashboardSettings()
    row.proxy_account_response_create_limit = None
    row.proxy_account_stream_limit = None
    row.proxy_account_stream_recovery_reserve = 3
    row.proxy_api_key_fair_share_congestion_threshold_pct = None
    row.request_log_retention_days = 30
    row.usage_history_retention_days = None

    class _Repository:
        async def get_or_create(self) -> DashboardSettings:
            return row

        async def list_active_password_users(self) -> list[DashboardUser]:
            # No accounts: these tests exercise settings resolution, not enrolment.
            return []

    # Environment differs from the code default for the stream limit (8) only.
    monkeypatch.setattr(
        settings_service_module,
        "get_settings",
        lambda: SimpleNamespace(
            proxy_account_response_create_limit=4,
            proxy_account_stream_limit=12,
            proxy_account_stream_recovery_reserve=1,
            proxy_api_key_fair_share_congestion_threshold_pct=0,
            # C2-2 routing/overload: the lease TTL differs from its default.
            proxy_overload_isolation_seconds=1800,
            proxy_account_error_rate_weighting_enabled=True,
            proxy_account_inflight_penalty_pct=2.5,
            proxy_account_lease_token_weight=1.0,
            proxy_account_lease_ttl_seconds=300.0,
        ),
    )
    row.proxy_overload_isolation_seconds = None
    row.proxy_account_error_rate_weighting_enabled = False
    row.proxy_account_inflight_penalty_pct = None
    row.proxy_account_lease_token_weight = None
    row.proxy_account_lease_ttl_seconds = None

    settings = await SettingsService(cast(SettingsRepository, _Repository())).get_settings()

    assert settings.provenance == {
        # Thread cache identity: NULL column and a stub startup-settings object
        # without the field, so it falls back to the ``shared`` code default.
        "thread_cache_identity_mode": InheritableValue("shared", "default", "shared", "shared"),
        "proxy_account_response_create_limit": InheritableValue(4, "default", 4, 4),
        "proxy_account_stream_limit": InheritableValue(12, "env", 12, 8),
        "proxy_account_stream_recovery_reserve": InheritableValue(3, "dashboard", 1, 1),
        "proxy_api_key_fair_share_congestion_threshold_pct": InheritableValue(0, "default", 0, 0),
        "proxy_overload_isolation_seconds": InheritableValue(1800, "default", 1800, 1800),
        "proxy_account_error_rate_weighting_enabled": InheritableValue(False, "dashboard", True, True),
        "proxy_account_inflight_penalty_pct": InheritableValue(2.5, "default", 2.5, 2.5),
        "proxy_account_lease_token_weight": InheritableValue(1.0, "default", 1.0, 1.0),
        "proxy_account_lease_ttl_seconds": InheritableValue(300.0, "env", 300.0, 900.0),
        "request_log_retention_days": InheritableValue(30, "dashboard", None, 0),
        "usage_history_retention_days": InheritableValue(0, "default", None, 0),
        # C2-3 resilience toggles: NULL columns, env double without the fields
        # -> code defaults.
        "soft_drain_enabled": InheritableValue(True, "default", True, True),
        "deterministic_failover_enabled": InheritableValue(True, "default", True, True),
        "circuit_breaker_enabled": InheritableValue(False, "default", False, False),
        # M3 codex prewarm: NULL column, env double without the field -> off.
        "http_responses_session_bridge_codex_prewarm_enabled": InheritableValue(False, "default", False, False),
        # M2 background jobs: NULL columns, env double without the fields ->
        # code defaults (every scheduler on).
        "auth_guardian_enabled": InheritableValue(True, "default", True, True),
        "automations_scheduler_enabled": InheritableValue(True, "default", True, True),
        "rate_limit_reset_credits_refresh_enabled": InheritableValue(True, "default", True, True),
        # M5 conversation archive: NULL column, env double without the field
        # -> code default (off).
        "conversation_archive_enabled": InheritableValue(False, "default", False, False),
        # R2 spool retention: NULL column, env double without the field -> the
        # 7-day code default.
        "http_responses_session_bridge_operation_spool_retention_seconds": InheritableValue(
            604800.0, "default", 604800.0, 604800.0
        ),
        # C2-1 timeouts: NULL columns and a startup fake without the fields
        # resolve to the code default.
        **{
            name: InheritableValue(
                Settings.model_fields[name].default,
                "default",
                Settings.model_fields[name].default,
                Settings.model_fields[name].default,
            )
            for name in DASHBOARD_TIMEOUT_SETTINGS
        },
    }
    assert settings.proxy_account_error_rate_weighting_enabled is False
    assert settings.proxy_account_lease_ttl_seconds == 300.0
    # The flat effective fields come from the same resolution.
    assert settings.proxy_account_stream_limit == 12
    assert settings.proxy_account_stream_recovery_reserve == 3
    assert settings.request_log_retention_days == 30


def test_resolve_inheritable_handles_float_timeouts_including_zero_keepalive() -> None:
    assert resolve_inheritable(None, 12.5, 10.0) == InheritableValue(12.5, "env", 12.5, 10.0)
    assert resolve_inheritable(None, 10.0, 10.0) == InheritableValue(10.0, "default", 10.0, 10.0)
    assert resolve_inheritable(0.0, 12.5, 10.0) == InheritableValue(0.0, "dashboard", 12.5, 10.0)


@pytest.mark.asyncio
async def test_timeout_settings_resolve_dashboard_then_environment_then_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = DashboardSettings()
    row.proxy_request_budget_seconds = 900.0
    row.sse_keepalive_interval_seconds = None
    row.upstream_connect_timeout_seconds = None

    class _Repository:
        async def get_or_create(self) -> DashboardSettings:
            return row

        async def list_active_password_users(self) -> list[DashboardUser]:
            # No accounts: these tests exercise settings resolution, not enrolment.
            return []

    monkeypatch.setattr(
        settings_service_module,
        "get_settings",
        lambda: SimpleNamespace(proxy_request_budget_seconds=601.0, sse_keepalive_interval_seconds=3.0),
    )

    settings = await SettingsService(cast(SettingsRepository, _Repository())).get_settings()

    assert settings.proxy_request_budget_seconds == 900.0
    assert settings.provenance["proxy_request_budget_seconds"] == InheritableValue(900.0, "dashboard", 601.0, 600.0)
    assert settings.sse_keepalive_interval_seconds == 3.0
    assert settings.provenance["sse_keepalive_interval_seconds"] == InheritableValue(3.0, "env", 3.0, 10.0)
    assert settings.upstream_connect_timeout_seconds == 8.0
    assert settings.provenance["upstream_connect_timeout_seconds"] == InheritableValue(8.0, "default", 8.0, 8.0)


@pytest.mark.asyncio
async def test_stream_and_bridge_budgets_resolve_dashboard_then_environment_then_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # M1 stream/bridge budgets: the three resolver states on the two new columns.
    row = DashboardSettings()
    row.http_responses_stream_request_budget_seconds = 3600.0
    row.http_responses_session_bridge_request_budget_seconds = None

    class _Repository:
        async def get_or_create(self) -> DashboardSettings:
            return row

        async def list_active_password_users(self) -> list[DashboardUser]:
            # No accounts: these tests exercise settings resolution, not enrolment.
            return []

    # (a) dashboard column set -> dashboard; (b) NULL column + env differs -> env.
    monkeypatch.setattr(
        settings_service_module,
        "get_settings",
        lambda: SimpleNamespace(
            http_responses_stream_request_budget_seconds=5000.0,
            http_responses_session_bridge_request_budget_seconds=5400.0,
        ),
    )
    settings = await SettingsService(cast(SettingsRepository, _Repository())).get_settings()
    assert settings.http_responses_stream_request_budget_seconds == 3600.0
    assert settings.provenance["http_responses_stream_request_budget_seconds"] == InheritableValue(
        3600.0, "dashboard", 5000.0, 7200.0
    )
    assert settings.http_responses_session_bridge_request_budget_seconds == 5400.0
    assert settings.provenance["http_responses_session_bridge_request_budget_seconds"] == InheritableValue(
        5400.0, "env", 5400.0, 7200.0
    )

    # (c) NULL column and no environment value -> code default.
    row.http_responses_stream_request_budget_seconds = None
    monkeypatch.setattr(settings_service_module, "get_settings", lambda: SimpleNamespace())
    settings = await SettingsService(cast(SettingsRepository, _Repository())).get_settings()
    assert settings.http_responses_stream_request_budget_seconds == 7200.0
    assert settings.provenance["http_responses_stream_request_budget_seconds"] == InheritableValue(
        7200.0, "default", 7200.0, 7200.0
    )
    assert settings.provenance["http_responses_session_bridge_request_budget_seconds"].source == "default"


@pytest.mark.asyncio
async def test_migrated_null_account_caps_inherit_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    row = DashboardSettings()
    row.proxy_account_response_create_limit = None
    row.proxy_account_stream_limit = None
    row.proxy_account_stream_recovery_reserve = None

    class _Repository:
        async def get_or_create(self) -> DashboardSettings:
            return row

        async def list_active_password_users(self) -> list[DashboardUser]:
            # No accounts: these tests exercise settings resolution, not enrolment.
            return []

    monkeypatch.setattr(
        settings_service_module,
        "get_settings",
        lambda: type(
            "_StartupSettings",
            (),
            {
                "proxy_account_response_create_limit": 24,
                "proxy_account_stream_limit": 32,
                "proxy_account_stream_recovery_reserve": 4,
                "proxy_api_key_fair_share_congestion_threshold_pct": 0,
                "hourly_rollup_retention_days": 0,
            },
        )(),
    )

    settings = await SettingsService(cast(SettingsRepository, _Repository())).get_settings()

    assert settings.proxy_account_response_create_limit == 24
    assert settings.proxy_account_response_create_limit_override is None
    assert settings.proxy_account_stream_limit == 32
    assert settings.proxy_account_stream_limit_override is None
    assert settings.proxy_account_stream_recovery_reserve == 4
    assert settings.proxy_account_stream_recovery_reserve_override is None


@pytest.mark.asyncio
async def test_cleared_account_cap_follows_environment_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    row = DashboardSettings()
    row.proxy_account_stream_limit = None
    startup_settings = SimpleNamespace(
        proxy_account_response_create_limit=24,
        proxy_account_stream_limit=8,
        proxy_account_stream_recovery_reserve=4,
        proxy_api_key_fair_share_congestion_threshold_pct=0,
    )

    class _Repository:
        async def get_or_create(self) -> DashboardSettings:
            return row

        async def list_active_password_users(self) -> list[DashboardUser]:
            # No accounts: these tests exercise settings resolution, not enrolment.
            return []

    monkeypatch.setattr(settings_service_module, "get_settings", lambda: startup_settings)
    service = SettingsService(cast(SettingsRepository, _Repository()))

    settings = await service.get_settings()
    assert settings.proxy_account_stream_limit == 8
    assert settings.proxy_account_stream_limit_override is None

    startup_settings.proxy_account_stream_limit = 12
    settings = await service.get_settings()
    assert settings.proxy_account_stream_limit == 12
    assert settings.proxy_account_stream_limit_override is None


@pytest.mark.asyncio
async def test_migrated_null_api_key_fair_share_threshold_inherits_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = DashboardSettings()
    row.proxy_api_key_fair_share_congestion_threshold_pct = None

    class _Repository:
        async def get_or_create(self) -> DashboardSettings:
            return row

        async def list_active_password_users(self) -> list[DashboardUser]:
            # No accounts: these tests exercise settings resolution, not enrolment.
            return []

    monkeypatch.setattr(
        settings_service_module,
        "get_settings",
        lambda: type(
            "_StartupSettings",
            (),
            {
                "proxy_account_response_create_limit": 24,
                "proxy_account_stream_limit": 32,
                "proxy_account_stream_recovery_reserve": 4,
                "proxy_api_key_fair_share_congestion_threshold_pct": 55,
                "hourly_rollup_retention_days": 0,
            },
        )(),
    )
    service = SettingsService(cast(SettingsRepository, _Repository()))

    # NULL migrated rows inherit the environment default.
    settings = await service.get_settings()
    assert settings.proxy_api_key_fair_share_congestion_threshold_pct == 55
    assert settings.proxy_api_key_fair_share_congestion_threshold_pct_override is None

    # A non-NULL dashboard value wins, including 0 (explicitly disabled).
    row.proxy_api_key_fair_share_congestion_threshold_pct = 80
    settings = await service.get_settings()
    assert settings.proxy_api_key_fair_share_congestion_threshold_pct == 80
    assert settings.proxy_api_key_fair_share_congestion_threshold_pct_override == 80

    row.proxy_api_key_fair_share_congestion_threshold_pct = 0
    settings = await service.get_settings()
    assert settings.proxy_api_key_fair_share_congestion_threshold_pct == 0
    assert settings.proxy_api_key_fair_share_congestion_threshold_pct_override == 0


@pytest.mark.asyncio
async def test_null_retention_inherits_environment_and_dashboard_value_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = DashboardSettings()

    class _Repository:
        async def get_or_create(self) -> DashboardSettings:
            return row

        async def list_active_password_users(self) -> list[DashboardUser]:
            # No accounts: these tests exercise settings resolution, not enrolment.
            return []

    monkeypatch.setattr(
        settings_service_module,
        "get_settings",
        lambda: type(
            "_StartupSettings",
            (),
            {
                "proxy_account_response_create_limit": 24,
                "proxy_account_stream_limit": 32,
                "proxy_account_stream_recovery_reserve": 4,
                "proxy_api_key_fair_share_congestion_threshold_pct": 0,
                "hourly_rollup_retention_days": 7,
            },
        )(),
    )
    service = SettingsService(cast(SettingsRepository, _Repository()))

    # NULL dashboard values mean retention was never configured, which is
    # disabled (0); the raw overrides stay exposed as None (= not set).
    settings = await service.get_settings()
    assert settings.request_log_retention_days == 0
    assert settings.usage_history_retention_days == 0
    assert settings.hourly_rollup_retention_days == 7
    assert settings.request_log_retention_override_days is None
    assert settings.usage_history_retention_override_days is None
    assert settings.hourly_rollup_retention_override_days is None

    # Non-NULL dashboard values win, including 0 (explicitly disabled).
    row.request_log_retention_days = 30
    row.usage_history_retention_days = 0
    row.hourly_rollup_retention_days = 0
    settings = await service.get_settings()
    assert settings.request_log_retention_days == 30
    assert settings.usage_history_retention_days == 0
    assert settings.hourly_rollup_retention_days == 0
    assert settings.request_log_retention_override_days == 30
    assert settings.usage_history_retention_override_days == 0
    assert settings.hourly_rollup_retention_override_days == 0


def test_parse_additional_quota_routing_policies_normalizes_aliases_and_policy_case() -> None:
    raw = json.dumps(
        {
            "codex-spark": "burn_first",
            "codex_spark": " preserve ",
            "gpt-5.3-codex-spark": "normal",
            "other": "legacy",
            123: "preserve",
        }
    )

    parsed = _parse_additional_quota_routing_policies(raw)
    assert parsed == {
        "codex_spark": "normal",
    }


def test_parse_additional_quota_routing_policies_handles_invalid_json() -> None:
    assert _parse_additional_quota_routing_policies(None) == {}
    assert _parse_additional_quota_routing_policies("not-json") == {}


def test_dump_additional_quota_routing_policies_canonicalizes_keys_and_filters_invalid() -> None:
    dumped = _dump_additional_quota_routing_policies(
        {
            "codex-spark": "normal",
            "codex_spark": "preserve",
            "  gpt-5.3-codex-spark  ": "burn_first",
            "bad-key": "normal",
        }
    )
    assert json.loads(dumped) == {"codex_spark": "burn_first"}


def test_sidecar_prefix_dump_parse_preserves_strip_flags_and_dedupes() -> None:
    dumped = _dump_claude_sidecar_model_prefixes(
        [
            SidecarPrefix(prefix=" CP- ", strip=True),
            SidecarPrefix(prefix="cp-", strip=False),
            SidecarPrefix(prefix="Claude", strip=False),
        ]
    )

    assert json.loads(dumped) == [
        {"prefix": "cp-", "strip": True},
        {"prefix": "claude", "strip": False},
    ]
    assert _parse_claude_sidecar_model_prefixes(dumped) == [
        SidecarPrefix(prefix="cp-", strip=True),
        SidecarPrefix(prefix="claude", strip=False),
    ]


def test_sidecar_full_model_dump_parse_trims_and_dedupes_case_insensitively() -> None:
    dumped = _dump_sidecar_full_models([" DeepSeek/Chat ", "deepseek/chat", "Claude/Sonnet"])

    assert json.loads(dumped) == ["DeepSeek/Chat", "Claude/Sonnet"]
    assert _parse_sidecar_full_models(dumped) == ["DeepSeek/Chat", "Claude/Sonnet"]


def _settings_update(
    *,
    claude_prefixes: list[SidecarPrefix] | None = None,
    openrouter_prefixes: list[SidecarPrefix] | None = None,
    orcarouter_prefixes: list[SidecarPrefix] | None = None,
    opencode_go_prefixes: list[SidecarPrefix] | None = None,
    omniroute_prefixes: list[SidecarPrefix] | None = None,
    ollama_prefixes: list[SidecarPrefix] | None = None,
    openai_compat_endpoints: list[OpenAICompatEndpointUpdateData] | None = None,
    claude_models: list[str] | None = None,
    openrouter_models: list[str] | None = None,
    orcarouter_models: list[str] | None = None,
    opencode_go_models: list[str] | None = None,
    omniroute_models: list[str] | None = None,
    ollama_models: list[str] | None = None,
) -> DashboardSettingsUpdateData:
    return DashboardSettingsUpdateData(
        sticky_threads_enabled=True,
        upstream_stream_transport="auto",
        prohibit_fast_mode=False,
        http_downstream_transport_policy="smart",
        thread_cache_identity_mode=None,
        clear_thread_cache_identity_mode=False,
        proxy_account_response_create_limit=4,
        clear_proxy_account_response_create_limit=False,
        proxy_account_stream_limit=8,
        clear_proxy_account_stream_limit=False,
        proxy_account_stream_recovery_reserve=1,
        clear_proxy_account_stream_recovery_reserve=False,
        proxy_api_key_fair_share_congestion_threshold_pct=0,
        clear_proxy_api_key_fair_share_congestion_threshold_pct=False,
        proxy_overload_isolation_seconds=None,
        clear_proxy_overload_isolation_seconds=False,
        proxy_account_error_rate_weighting_enabled=None,
        clear_proxy_account_error_rate_weighting_enabled=False,
        proxy_account_inflight_penalty_pct=None,
        clear_proxy_account_inflight_penalty_pct=False,
        proxy_account_lease_token_weight=None,
        clear_proxy_account_lease_token_weight=False,
        proxy_account_lease_ttl_seconds=None,
        clear_proxy_account_lease_ttl_seconds=False,
        upstream_proxy_routing_enabled=False,
        upstream_proxy_default_pool_id=None,
        prefer_earlier_reset_accounts=True,
        prefer_earlier_reset_window="secondary",
        show_reset_credit_badges=True,
        auto_redeem_reset_credits_before_expiry=False,
        show_reset_credit_expiry_badge=True,
        routing_strategy="capacity_weighted",
        relative_availability_power=2.0,
        relative_availability_top_k=5,
        single_account_id=None,
        openai_cache_affinity_max_age_seconds=300,
        dashboard_session_ttl_seconds=43200,
        http_responses_session_bridge_prompt_cache_idle_ttl_seconds=1800,
        http_responses_session_bridge_gateway_safe_mode=True,
        sticky_reallocation_budget_threshold_pct=95.0,
        sticky_reallocation_primary_budget_threshold_pct=95.0,
        sticky_reallocation_secondary_budget_threshold_pct=100.0,
        additional_quota_routing_policies={},
        model_aliases={},
        custom_alias_catalog={},
        warmup_model="auto",
        import_without_overwrite=True,
        totp_required_on_login=False,
        totp_required_for_admin_role=False,
        local_login_policy="enabled",
        api_key_auth_enabled=False,
        hide_upstream_quota_from_api_keys=False,
        limit_warmup_enabled=False,
        limit_warmup_windows="both",
        limit_warmup_model="auto",
        limit_warmup_prompt="Say OK.",
        limit_warmup_cooldown_seconds=3600,
        limit_warmup_exhausted_threshold_percent=99.0,
        limit_warmup_idle_threshold_percent=1.0,
        limit_warmup_min_available_percent=100.0,
        weekly_pace_working_days="0,1,2,3,4,5,6",
        weekly_pace_smoothing_minutes=30,
        claude_sidecar_enabled=False,
        claude_sidecar_base_url="http://127.0.0.1:8317",
        claude_sidecar_api_key=None,
        claude_sidecar_clear_api_key=False,
        claude_sidecar_model_prefixes=claude_prefixes or [SidecarPrefix(prefix="claude", strip=False)],
        claude_sidecar_full_models=claude_models or [],
        claude_sidecar_connect_timeout_seconds=8.0,
        claude_sidecar_request_timeout_seconds=600.0,
        claude_sidecar_models_cache_ttl_seconds=60.0,
        claude_sidecar_management_key=None,
        claude_sidecar_clear_management_key=False,
        claude_sidecar_quota_poll_interval_seconds=60.0,
        claude_sidecar_auth_plans=[],
        claude_sidecar_usage_poll_interval_seconds=15.0,
        claude_sidecar_usage_queue_batch_size=100,
        claude_sidecar_usage_collection_enabled=True,
        claude_sidecar_default_reasoning_effort=None,
        openrouter_sidecar_enabled=False,
        openrouter_sidecar_base_url="https://openrouter.ai/api/v1",
        openrouter_sidecar_api_key=None,
        openrouter_sidecar_clear_api_key=False,
        openrouter_sidecar_model_prefixes=openrouter_prefixes or [],
        openrouter_sidecar_full_models=openrouter_models or [],
        openrouter_sidecar_connect_timeout_seconds=8.0,
        openrouter_sidecar_request_timeout_seconds=600.0,
        openrouter_sidecar_models_cache_ttl_seconds=60.0,
        openrouter_sidecar_default_reasoning_effort=None,
        openai_compat_endpoints=openai_compat_endpoints or [],
        orcarouter_sidecar_enabled=False,
        orcarouter_sidecar_base_url="https://api.orcarouter.ai/v1",
        orcarouter_sidecar_api_key=None,
        orcarouter_sidecar_clear_api_key=False,
        orcarouter_sidecar_model_prefixes=orcarouter_prefixes or [SidecarPrefix(prefix="orcarouter/", strip=False)],
        orcarouter_sidecar_full_models=orcarouter_models or [],
        orcarouter_sidecar_connect_timeout_seconds=8.0,
        orcarouter_sidecar_request_timeout_seconds=600.0,
        orcarouter_sidecar_models_cache_ttl_seconds=60.0,
        orcarouter_sidecar_default_reasoning_effort=None,
        # OpenCode Go participates in the same cross-integration uniqueness
        # check, so the fixture has to carry its fields. Disabled and
        # unconfigured by default, matching the shipped default.
        opencode_go_sidecar_enabled=False,
        opencode_go_sidecar_base_url="https://opencode.ai/zen/go/v1",
        opencode_go_sidecar_api_key=None,
        opencode_go_sidecar_clear_api_key=False,
        opencode_go_sidecar_model_prefixes=opencode_go_prefixes or [],
        opencode_go_sidecar_full_models=opencode_go_models or [],
        opencode_go_sidecar_connect_timeout_seconds=8.0,
        opencode_go_sidecar_request_timeout_seconds=600.0,
        opencode_go_sidecar_models_cache_ttl_seconds=60.0,
        omniroute_sidecar_enabled=False,
        omniroute_sidecar_base_url="http://127.0.0.1:20128/v1",
        omniroute_sidecar_api_key=None,
        omniroute_sidecar_clear_api_key=False,
        omniroute_sidecar_model_prefixes=omniroute_prefixes or [],
        omniroute_sidecar_full_models=omniroute_models or [],
        omniroute_sidecar_selected_models=omniroute_models or [],
        omniroute_sidecar_connect_timeout_seconds=8.0,
        omniroute_sidecar_request_timeout_seconds=600.0,
        omniroute_sidecar_models_cache_ttl_seconds=60.0,
        omniroute_sidecar_default_reasoning_effort=None,
        ollama_sidecar_enabled=False,
        ollama_sidecar_base_url="https://ollama.com",
        ollama_sidecar_api_key=None,
        ollama_sidecar_clear_api_key=False,
        ollama_sidecar_model_prefixes=ollama_prefixes or [],
        ollama_sidecar_full_models=ollama_models or [],
        ollama_sidecar_connect_timeout_seconds=8.0,
        ollama_sidecar_request_timeout_seconds=600.0,
        ollama_sidecar_models_cache_ttl_seconds=60.0,
        ollama_sidecar_default_reasoning_effort=None,
        guest_access_enabled=False,
        limit_warmup_staggered_idle_enabled=False,
        request_log_retention_override_days=None,
        usage_history_retention_override_days=None,
        clear_request_log_retention_override=False,
        clear_usage_history_retention_override=False,
    )


def test_sidecar_route_validator_rejects_duplicate_prefixes() -> None:
    payload = _settings_update(
        claude_prefixes=[SidecarPrefix(prefix="cp-", strip=True)],
        openrouter_prefixes=[SidecarPrefix(prefix="cp-", strip=False)],
    )

    with pytest.raises(SidecarRoutingConflictError) as exc_info:
        _validate_routes(payload)

    assert exc_info.value.conflict.kind == "prefix"
    assert exc_info.value.conflict.value == "cp-"
    assert exc_info.value.conflict.owner == "CLIProxyAPI"


def test_dashboard_error_supports_sidecar_conflict_details() -> None:
    from app.core.errors import dashboard_error

    envelope = dashboard_error(
        "sidecar_routing_conflict",
        "prefix conflict",
        details={
            "code": "sidecar_routing_conflict",
            "value": "cp-",
            "kind": "prefix",
            "owning_integration": "CLIProxyAPI",
        },
    )

    assert envelope["error"]["details"] == {
        "code": "sidecar_routing_conflict",
        "value": "cp-",
        "kind": "prefix",
        "owning_integration": "CLIProxyAPI",
    }


def test_sidecar_route_validator_allows_duplicate_full_models_across_cards() -> None:
    """Full models stopped being unique across cards; the star map routes them.

    The historical conflict - adding ``glm-5.3`` to OpenRouter after OrcaRouter
    - must save cleanly now, because a pool chains the same model across both
    cards and the star decides which one owns the bare id.
    """

    payload = _settings_update(
        openrouter_models=["z-ai/glm-5.3"],
        orcarouter_models=["z-ai/glm-5.3"],
    )

    _validate_routes(payload)


def test_sidecar_route_validator_allows_duplicate_full_models_across_openai_compat_cards() -> None:
    payload = _settings_update(
        orcarouter_models=["z-ai/glm-5.3"],
        openai_compat_endpoints=_openai_compat_endpoints(models=["z-ai/glm-5.3"]),
    )

    _validate_routes(payload)


def test_sidecar_route_validator_allows_two_openai_compat_endpoints_sharing_a_full_model() -> None:
    payload = _settings_update(
        openai_compat_endpoints=[
            *_openai_compat_endpoints(models=["Qwen/Qwen2.5-7B"]),
            *_openai_compat_endpoints(
                name="vLLM",
                endpoint_id="3d0c9e4b-2f5e-4c8b-8d22-8b1f5e3c2d1b",
                models=["Qwen/Qwen2.5-7B"],
            ),
        ]
    )

    _validate_routes(payload)


def _openai_compat_endpoints(
    *,
    name: str = "Vast",
    endpoint_id: str = "2c9b8f3a-1e4d-4b7a-9c11-7a0e4d2b1c0a",
    prefixes: list[SidecarPrefix] | None = None,
    models: list[str] | None = None,
) -> list[OpenAICompatEndpointUpdateData]:
    return [
        OpenAICompatEndpointUpdateData(
            id=endpoint_id,
            name=name,
            enabled=True,
            base_url="https://openai.vast.ai/demo/v1",
            api_key=None,
            clear_api_key=False,
            prefixes=prefixes or [],
            full_models=models or [],
            connect_timeout_seconds=8.0,
            request_timeout_seconds=600.0,
            models_cache_ttl_seconds=60.0,
            default_reasoning_effort=None,
        )
    ]


def test_sidecar_route_validator_rejects_openai_compat_orcarouter_duplicate_prefixes() -> None:
    payload = _settings_update(
        orcarouter_prefixes=[SidecarPrefix(prefix="vast/", strip=True)],
        openai_compat_endpoints=_openai_compat_endpoints(prefixes=[SidecarPrefix(prefix="vast/", strip=True)]),
    )

    with pytest.raises(SidecarRoutingConflictError) as exc_info:
        _validate_routes(payload)

    assert exc_info.value.conflict.kind == "prefix"
    assert exc_info.value.conflict.value == "vast/"
    assert {exc_info.value.conflict.owner, exc_info.value.conflict.challenger} == {"OrcaRouter", "Vast"}


def test_sidecar_route_validator_rejects_ollama_duplicate_prefixes() -> None:
    payload = _settings_update(
        openrouter_prefixes=[SidecarPrefix(prefix="cloud/", strip=False)],
        ollama_prefixes=[SidecarPrefix(prefix="cloud/", strip=False)],
    )

    with pytest.raises(SidecarRoutingConflictError) as exc_info:
        _validate_routes(payload)

    assert exc_info.value.conflict.kind == "prefix"
    assert exc_info.value.conflict.value == "cloud/"
    assert exc_info.value.conflict.owner == "OpenRouter"
    assert exc_info.value.conflict.challenger == "Ollama"


def test_sidecar_route_validator_allows_duplicate_full_models_across_openrouter_and_ollama() -> None:
    payload = _settings_update(
        openrouter_models=["gpt-oss:120b-cloud"],
        ollama_models=["GPT-OSS:120B-CLOUD"],
    )

    _validate_routes(payload)


def test_sidecar_route_validator_rejects_orcarouter_duplicate_prefixes() -> None:
    payload = _settings_update(
        openrouter_prefixes=[SidecarPrefix(prefix="orcarouter/", strip=False)],
        orcarouter_prefixes=[SidecarPrefix(prefix="orcarouter/", strip=False)],
    )

    with pytest.raises(SidecarRoutingConflictError) as exc_info:
        _validate_routes(payload)

    assert exc_info.value.conflict.kind == "prefix"
    assert exc_info.value.conflict.value == "orcarouter/"
    assert {exc_info.value.conflict.owner, exc_info.value.conflict.challenger} == {"OrcaRouter", "OpenRouter"}


def test_sidecar_route_validator_rejects_opencode_go_duplicate_prefixes() -> None:
    """The new provider is inside the uniqueness guarantee, not beside it.

    Uniqueness is what makes the provider tiebreak order unreachable in
    practice; an integration omitted from the check would let two providers own
    the same prefix and make the owner depend on that order.
    """

    payload = _settings_update(
        openrouter_prefixes=[SidecarPrefix(prefix="opencode-go/", strip=False)],
        opencode_go_prefixes=[SidecarPrefix(prefix="opencode-go/", strip=True)],
    )

    with pytest.raises(SidecarRoutingConflictError) as exc_info:
        _validate_routes(payload)

    assert exc_info.value.conflict.kind == "prefix"
    assert exc_info.value.conflict.value == "opencode-go/"
    assert {exc_info.value.conflict.owner, exc_info.value.conflict.challenger} == {"OpenCode Go", "OpenRouter"}


def test_sidecar_route_validator_allows_duplicate_full_models_across_opencode_go_and_ollama() -> None:
    payload = _settings_update(
        opencode_go_models=["glm-5.3"],
        ollama_models=["GLM-5.3"],
    )

    _validate_routes(payload)


def test_sidecar_route_validator_accepts_the_default_payload() -> None:
    """Control: the shipped unconfigured default is not itself a conflict.

    Two integrations both carrying an empty prefix list must not be read as
    colliding on the empty value.
    """

    _validate_routes(_settings_update())


def test_sidecar_route_validator_allows_prefix_and_full_model_text_coincidence() -> None:
    payload = _settings_update(
        openrouter_prefixes=[SidecarPrefix(prefix="cp-", strip=True)],
        ollama_models=["cp-"],
    )

    _validate_routes(payload)


def test_sidecar_route_validator_keeps_stars_for_models_the_cards_still_list() -> None:
    payload = _settings_update(
        openrouter_models=["z-ai/glm-5.3"],
        orcarouter_models=["z-ai/glm-5.3"],
    )

    effective = _validate_routes(payload, stored_stars={"z-ai/glm-5.3": "orcarouter"})

    assert effective == {"z-ai/glm-5.3": "orcarouter"}


def test_sidecar_route_validator_drops_a_star_whose_card_no_longer_lists_the_model() -> None:
    """Deleting the starred entry leaves the model unrouted-by-default.

    The star decays instead of blocking an unrelated save: the operator removed
    the model from its starred card, so no card is the model's default route
    until one is starred again.
    """

    payload = _settings_update(
        openrouter_models=["z-ai/glm-5.3"],
        orcarouter_models=[],
    )

    effective = _validate_routes(payload, stored_stars={"z-ai/glm-5.3": "orcarouter"})

    assert effective == {}


def test_sidecar_route_validator_drops_a_star_whose_provider_is_absent_from_the_save() -> None:
    payload = _settings_update(
        openrouter_models=["z-ai/glm-5.3"],
    )

    effective = _validate_routes(payload, stored_stars={"z-ai/glm-5.3": "unknown_provider"})

    assert effective == {}


def test_sidecar_route_validator_rekeys_and_normalizes_stars() -> None:
    payload = _settings_update(
        openrouter_models=["z-ai/glm-5.3"],
        orcarouter_models=["GLM-5.3"],
    )

    effective = _validate_routes(payload, stored_stars={"  Z-AI/GLM-5.3 ": " openrouter ", " glm-5.3 ": "orcarouter"})

    assert effective == {"z-ai/glm-5.3": "openrouter", "glm-5.3": "orcarouter"}


def test_sidecar_route_validator_rejects_duplicate_prefixes_even_with_stars() -> None:
    """Prefix uniqueness is untouched by the star map."""

    payload = _settings_update(
        openrouter_prefixes=[SidecarPrefix(prefix="cloud/", strip=False)],
        ollama_prefixes=[SidecarPrefix(prefix="cloud/", strip=False)],
    )

    with pytest.raises(SidecarRoutingConflictError) as exc_info:
        _validate_routes(payload, stored_stars={"cloud": "openrouter"})

    assert exc_info.value.conflict.kind == "prefix"


def test_settings_update_request_accepts_legacy_string_prefix_arrays() -> None:
    from app.modules.settings.schemas import DashboardSettingsUpdateRequest

    payload = DashboardSettingsUpdateRequest.model_validate(
        {
            "claudeSidecarModelPrefixes": ["Claude", "CP-"],
            "openrouterSidecarModelPrefixes": ["or_"],
        }
    )

    assert payload.claude_sidecar_model_prefixes is not None
    assert [prefix.model_dump() for prefix in payload.claude_sidecar_model_prefixes] == [
        {"prefix": "claude", "strip": False},
        {"prefix": "cp-", "strip": True},
    ]
    assert payload.openrouter_sidecar_model_prefixes is not None
    assert [prefix.model_dump() for prefix in payload.openrouter_sidecar_model_prefixes] == [
        {"prefix": "or_", "strip": True},
    ]


def test_settings_update_request_accepts_ollama_string_prefix_arrays() -> None:
    from app.modules.settings.schemas import DashboardSettingsUpdateRequest

    payload = DashboardSettingsUpdateRequest.model_validate(
        {
            "ollamaSidecarModelPrefixes": ["Ollama-", "ollama_"],
            "ollamaSidecarFullModels": [" gpt-oss:120b-cloud ", "GPT-OSS:120B-CLOUD"],
        }
    )

    assert payload.ollama_sidecar_model_prefixes is not None
    assert [prefix.model_dump() for prefix in payload.ollama_sidecar_model_prefixes] == [
        {"prefix": "ollama-", "strip": True},
        {"prefix": "ollama_", "strip": True},
    ]
    assert payload.ollama_sidecar_full_models == ["gpt-oss:120b-cloud"]


# --- C2-3 resilience toggles -------------------------------------------------


def test_resolve_inheritable_boolean_toggle_in_each_state() -> None:
    # NULL column + env differs from the default -> env layer.
    assert resolve_inheritable(None, False, True) == InheritableValue(False, "env", False, True)
    # NULL column + env equals the default -> default layer.
    assert resolve_inheritable(None, True, True) == InheritableValue(True, "default", True, True)
    # Dashboard value wins, including an explicit False.
    assert resolve_inheritable(False, True, True) == InheritableValue(False, "dashboard", True, True)
    assert resolve_inheritable(True, False, False) == InheritableValue(True, "dashboard", False, False)


@pytest.mark.asyncio
async def test_settings_data_resolves_resilience_toggles_with_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    row = DashboardSettings()
    row.soft_drain_enabled = None
    row.deterministic_failover_enabled = None
    row.circuit_breaker_enabled = True

    class _Repository:
        async def get_or_create(self) -> DashboardSettings:
            return row

        async def list_active_password_users(self) -> list[DashboardUser]:
            # No accounts: these tests exercise settings resolution, not enrolment.
            return []

    monkeypatch.setattr(
        settings_service_module,
        "get_settings",
        lambda: SimpleNamespace(
            proxy_account_response_create_limit=4,
            proxy_account_stream_limit=8,
            proxy_account_stream_recovery_reserve=1,
            proxy_api_key_fair_share_congestion_threshold_pct=0,
            soft_drain_enabled=True,
            deterministic_failover_enabled=False,
            circuit_breaker_enabled=False,
        ),
    )
    service = SettingsService(cast(SettingsRepository, _Repository()))

    data = await service.get_settings()

    assert data.soft_drain_enabled is True
    assert data.deterministic_failover_enabled is False
    assert data.circuit_breaker_enabled is True
    assert data.provenance["soft_drain_enabled"] == InheritableValue(True, "default", True, True)
    assert data.provenance["deterministic_failover_enabled"] == InheritableValue(False, "env", False, True)
    assert data.provenance["circuit_breaker_enabled"] == InheritableValue(True, "dashboard", False, False)


# --- M3 codex prewarm --------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("column_value", "env_value", "expected"),
    [
        # NULL column + env alias differs from the default -> env layer.
        (None, True, InheritableValue(True, "env", True, False)),
        # NULL column + env alias equals the default -> default layer.
        (None, False, InheritableValue(False, "default", False, False)),
        # Dashboard value wins in both directions, including an explicit False.
        (False, True, InheritableValue(False, "dashboard", True, False)),
        (True, False, InheritableValue(True, "dashboard", False, False)),
    ],
)
async def test_settings_data_resolves_codex_prewarm_switch_with_provenance(
    monkeypatch: pytest.MonkeyPatch,
    column_value: bool | None,
    env_value: bool,
    expected: InheritableValue[bool],
) -> None:
    row = DashboardSettings()
    row.http_responses_session_bridge_codex_prewarm_enabled = column_value

    class _Repository:
        async def get_or_create(self) -> DashboardSettings:
            return row

        async def list_active_password_users(self) -> list[DashboardUser]:
            # No accounts: these tests exercise settings resolution, not enrolment.
            return []

    monkeypatch.setattr(
        settings_service_module,
        "get_settings",
        lambda: SimpleNamespace(
            proxy_account_response_create_limit=4,
            proxy_account_stream_limit=8,
            proxy_account_stream_recovery_reserve=1,
            proxy_api_key_fair_share_congestion_threshold_pct=0,
            http_responses_session_bridge_codex_prewarm_enabled=env_value,
        ),
    )

    data = await SettingsService(cast(SettingsRepository, _Repository())).get_settings()

    assert data.http_responses_session_bridge_codex_prewarm_enabled is expected.value
    assert data.provenance["http_responses_session_bridge_codex_prewarm_enabled"] == expected


# --- M2 background jobs -------------------------------------------------------


@pytest.mark.asyncio
async def test_settings_data_resolves_background_job_toggles_with_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    """M2 background jobs: dashboard column > deprecated env alias > default, plus the topology flag."""
    row = DashboardSettings()
    row.auth_guardian_enabled = None
    row.automations_scheduler_enabled = False
    row.rate_limit_reset_credits_refresh_enabled = None
    # A real Settings so the topology gate is evaluated: two-replica ring
    # without leader election blocks the guardian whatever the toggle says.
    startup = Settings(
        _env_file=None,
        auth_guardian_enabled=True,
        automations_scheduler_enabled=True,
        rate_limit_reset_credits_refresh_enabled=False,
        leader_election_enabled=False,
        http_responses_session_bridge_instance_id="pod-a",
        http_responses_session_bridge_instance_ring=["pod-a", "pod-b"],
    )
    monkeypatch.setattr(settings_service_module, "get_settings", lambda: startup)

    class _Repository:
        async def get_or_create(self) -> DashboardSettings:
            return row

        async def list_active_password_users(self) -> list[DashboardUser]:
            # No accounts: these tests exercise settings resolution, not enrolment.
            return []

    service = SettingsService(cast(SettingsRepository, _Repository()))

    data = await service.get_settings()

    assert data.auth_guardian_enabled is True
    assert data.auth_guardian_blocked_by_topology is True
    assert data.automations_scheduler_enabled is False
    assert data.rate_limit_reset_credits_refresh_enabled is False
    assert data.provenance["auth_guardian_enabled"] == InheritableValue(True, "default", True, True)
    assert data.provenance["automations_scheduler_enabled"] == InheritableValue(False, "dashboard", True, True)
    assert data.provenance["rate_limit_reset_credits_refresh_enabled"] == InheritableValue(False, "env", False, True)

    startup.leader_election_enabled = True
    assert (await service.get_settings()).auth_guardian_blocked_by_topology is False


# M5 conversation archive
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("column", "env", "expected", "source"),
    [
        (None, False, False, "default"),
        (None, True, True, "env"),
        (True, False, True, "dashboard"),
        (False, True, False, "dashboard"),
    ],
)
async def test_settings_data_resolves_conversation_archive_toggle_with_provenance(
    monkeypatch: pytest.MonkeyPatch, column: bool | None, env: bool, expected: bool, source: SettingSource
) -> None:
    row = DashboardSettings()
    row.conversation_archive_enabled = column

    class _Repository:
        async def get_or_create(self) -> DashboardSettings:
            return row

        async def list_active_password_users(self) -> list[DashboardUser]:
            # No accounts: these tests exercise settings resolution, not enrolment.
            return []

    monkeypatch.setattr(
        settings_service_module,
        "get_settings",
        lambda: SimpleNamespace(
            proxy_account_response_create_limit=4,
            proxy_account_stream_limit=8,
            proxy_account_stream_recovery_reserve=1,
            proxy_api_key_fair_share_congestion_threshold_pct=0,
            conversation_archive_enabled=env,
        ),
    )

    data = await SettingsService(cast(SettingsRepository, _Repository())).get_settings()

    assert data.conversation_archive_enabled is expected
    assert data.provenance["conversation_archive_enabled"] == InheritableValue(expected, source, env, False)


def test_conversation_archive_env_shadow_warning_names_the_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    """A set CODEX_LB_CONVERSATION_ARCHIVE_ENABLED that the dashboard column overrides is reported at startup."""
    row = DashboardSettings()
    row.conversation_archive_enabled = False
    environment = Settings(conversation_archive_enabled=True)

    shadowed = settings_service_module.warn_environment_shadowed_by_dashboard(row, environment)

    assert "conversation_archive_enabled" in shadowed


# end M5 conversation archive
