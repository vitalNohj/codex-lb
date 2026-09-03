from __future__ import annotations

import json
from typing import cast

import pytest

import app.modules.settings.service as settings_service_module
from app.core.clients.claude_sidecar import SidecarPrefix
from app.db.models import DashboardSettings
from app.modules.settings.repository import SettingsRepository
from app.modules.settings.service import (
    DashboardSettingsUpdateData,
    SettingsService,
    SidecarRoutingConflictError,
    _dump_additional_quota_routing_policies,
    _dump_claude_sidecar_model_prefixes,
    _dump_sidecar_full_models,
    _parse_additional_quota_routing_policies,
    _parse_claude_sidecar_model_prefixes,
    _parse_sidecar_full_models,
    _validate_unique_sidecar_routes,
)

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_migrated_null_account_caps_inherit_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    row = DashboardSettings()
    row.proxy_account_response_create_limit = None
    row.proxy_account_stream_limit = None
    row.proxy_account_stream_recovery_reserve = None

    class _Repository:
        async def get_or_create(self) -> DashboardSettings:
            return row

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
                "request_log_retention_days": 0,
                "usage_history_retention_days": 0,
            },
        )(),
    )

    settings = await SettingsService(cast(SettingsRepository, _Repository())).get_settings()

    assert settings.proxy_account_response_create_limit == 24
    assert settings.proxy_account_stream_limit == 32
    assert settings.proxy_account_stream_recovery_reserve == 4


@pytest.mark.asyncio
async def test_migrated_null_api_key_fair_share_threshold_inherits_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = DashboardSettings()
    row.proxy_api_key_fair_share_congestion_threshold_pct = None

    class _Repository:
        async def get_or_create(self) -> DashboardSettings:
            return row

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
                "request_log_retention_days": 0,
                "usage_history_retention_days": 0,
            },
        )(),
    )
    service = SettingsService(cast(SettingsRepository, _Repository()))

    # NULL migrated rows inherit the environment default.
    settings = await service.get_settings()
    assert settings.proxy_api_key_fair_share_congestion_threshold_pct == 55

    # A non-NULL dashboard value wins, including 0 (explicitly disabled).
    row.proxy_api_key_fair_share_congestion_threshold_pct = 80
    settings = await service.get_settings()
    assert settings.proxy_api_key_fair_share_congestion_threshold_pct == 80

    row.proxy_api_key_fair_share_congestion_threshold_pct = 0
    settings = await service.get_settings()
    assert settings.proxy_api_key_fair_share_congestion_threshold_pct == 0


@pytest.mark.asyncio
async def test_null_retention_inherits_environment_and_dashboard_value_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = DashboardSettings()

    class _Repository:
        async def get_or_create(self) -> DashboardSettings:
            return row

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
                "request_log_retention_days": 90,
                "usage_history_retention_days": 45,
            },
        )(),
    )
    service = SettingsService(cast(SettingsRepository, _Repository()))

    # NULL dashboard values inherit the deprecated env alias; the raw
    # overrides stay exposed as None (= inherit).
    settings = await service.get_settings()
    assert settings.request_log_retention_days == 90
    assert settings.usage_history_retention_days == 45
    assert settings.request_log_retention_override_days is None
    assert settings.usage_history_retention_override_days is None

    # Non-NULL dashboard values win, including 0 (explicitly disabled).
    row.request_log_retention_days = 30
    row.usage_history_retention_days = 0
    settings = await service.get_settings()
    assert settings.request_log_retention_days == 30
    assert settings.usage_history_retention_days == 0
    assert settings.request_log_retention_override_days == 30
    assert settings.usage_history_retention_override_days == 0


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
    omniroute_prefixes: list[SidecarPrefix] | None = None,
    ollama_prefixes: list[SidecarPrefix] | None = None,
    claude_models: list[str] | None = None,
    openrouter_models: list[str] | None = None,
    orcarouter_models: list[str] | None = None,
    omniroute_models: list[str] | None = None,
    ollama_models: list[str] | None = None,
) -> DashboardSettingsUpdateData:
    return DashboardSettingsUpdateData(
        sticky_threads_enabled=True,
        upstream_stream_transport="default",
        prohibit_fast_mode=False,
        http_downstream_transport_policy="smart",
        proxy_account_response_create_limit=4,
        proxy_account_stream_limit=8,
        proxy_account_stream_recovery_reserve=1,
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
        _validate_unique_sidecar_routes(payload)

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


def test_sidecar_route_validator_rejects_duplicate_full_models() -> None:
    payload = _settings_update(
        openrouter_models=["DeepSeek/Chat"],
        omniroute_models=["deepseek/chat"],
    )

    with pytest.raises(SidecarRoutingConflictError) as exc_info:
        _validate_unique_sidecar_routes(payload)

    assert exc_info.value.conflict.kind == "full_model"
    assert exc_info.value.conflict.owner == "OpenRouter"


def test_sidecar_route_validator_rejects_ollama_duplicate_prefixes() -> None:
    payload = _settings_update(
        openrouter_prefixes=[SidecarPrefix(prefix="cloud/", strip=False)],
        ollama_prefixes=[SidecarPrefix(prefix="cloud/", strip=False)],
    )

    with pytest.raises(SidecarRoutingConflictError) as exc_info:
        _validate_unique_sidecar_routes(payload)

    assert exc_info.value.conflict.kind == "prefix"
    assert exc_info.value.conflict.value == "cloud/"
    assert exc_info.value.conflict.owner == "OpenRouter"
    assert exc_info.value.conflict.challenger == "Ollama"


def test_sidecar_route_validator_rejects_ollama_duplicate_full_models() -> None:
    payload = _settings_update(
        omniroute_models=["gpt-oss:120b-cloud"],
        ollama_models=["GPT-OSS:120B-CLOUD"],
    )

    with pytest.raises(SidecarRoutingConflictError) as exc_info:
        _validate_unique_sidecar_routes(payload)

    assert exc_info.value.conflict.kind == "full_model"
    assert exc_info.value.conflict.owner == "OmniRoute"
    assert exc_info.value.conflict.challenger == "Ollama"


def test_sidecar_route_validator_rejects_orcarouter_duplicate_prefixes() -> None:
    payload = _settings_update(
        omniroute_prefixes=[SidecarPrefix(prefix="orcarouter/", strip=False)],
        orcarouter_prefixes=[SidecarPrefix(prefix="orcarouter/", strip=False)],
    )

    with pytest.raises(SidecarRoutingConflictError) as exc_info:
        _validate_unique_sidecar_routes(payload)

    assert exc_info.value.conflict.kind == "prefix"
    assert exc_info.value.conflict.value == "orcarouter/"
    assert {exc_info.value.conflict.owner, exc_info.value.conflict.challenger} == {"OrcaRouter", "OmniRoute"}


def test_sidecar_route_validator_allows_prefix_and_full_model_text_coincidence() -> None:
    payload = _settings_update(
        openrouter_prefixes=[SidecarPrefix(prefix="cp-", strip=True)],
        ollama_models=["cp-"],
    )

    _validate_unique_sidecar_routes(payload)


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
