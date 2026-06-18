from __future__ import annotations

import json

import pytest

from app.core.clients.claude_sidecar import SidecarPrefix
from app.modules.settings.service import (
    DashboardSettingsUpdateData,
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
    omniroute_prefixes: list[SidecarPrefix] | None = None,
    claude_models: list[str] | None = None,
    openrouter_models: list[str] | None = None,
    omniroute_models: list[str] | None = None,
) -> DashboardSettingsUpdateData:
    return DashboardSettingsUpdateData(
        sticky_threads_enabled=True,
        upstream_stream_transport="default",
        upstream_proxy_routing_enabled=False,
        upstream_proxy_default_pool_id=None,
        prefer_earlier_reset_accounts=True,
        prefer_earlier_reset_window="secondary",
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
        warmup_model="auto",
        import_without_overwrite=True,
        totp_required_on_login=False,
        api_key_auth_enabled=False,
        limit_warmup_enabled=False,
        limit_warmup_windows="both",
        limit_warmup_model="auto",
        limit_warmup_prompt="Say OK.",
        limit_warmup_cooldown_seconds=3600,
        limit_warmup_min_available_percent=100.0,
        weekly_pace_working_days="0,1,2,3,4,5,6",
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
        openrouter_sidecar_enabled=False,
        openrouter_sidecar_base_url="https://openrouter.ai/api/v1",
        openrouter_sidecar_api_key=None,
        openrouter_sidecar_clear_api_key=False,
        openrouter_sidecar_model_prefixes=openrouter_prefixes or [],
        openrouter_sidecar_full_models=openrouter_models or [],
        openrouter_sidecar_connect_timeout_seconds=8.0,
        openrouter_sidecar_request_timeout_seconds=600.0,
        openrouter_sidecar_models_cache_ttl_seconds=60.0,
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


def test_sidecar_route_validator_allows_prefix_and_full_model_text_coincidence() -> None:
    payload = _settings_update(
        openrouter_prefixes=[SidecarPrefix(prefix="cp-", strip=True)],
        omniroute_models=["cp-"],
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
