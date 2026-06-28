from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import get_settings
from app.core.crypto import TokenEncryptor
from app.db.models import DashboardSettings

_SETTINGS_ID = 1
_UNSET = object()


class SettingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_or_create(self) -> DashboardSettings:
        existing = await self._session.get(DashboardSettings, _SETTINGS_ID)
        if existing is not None:
            return existing

        static_settings = get_settings()
        sidecar_api_key = static_settings.claude_sidecar_api_key.strip()
        sidecar_management_key = static_settings.claude_sidecar_management_key.strip()
        row = DashboardSettings(
            id=_SETTINGS_ID,
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
            openai_cache_affinity_max_age_seconds=static_settings.openai_cache_affinity_max_age_seconds,
            dashboard_session_ttl_seconds=43200,
            warmup_model=static_settings.warmup_model,
            import_without_overwrite=True,
            totp_required_on_login=False,
            password_hash=None,
            guest_access_enabled=False,
            guest_password_hash=None,
            bootstrap_token_encrypted=None,
            bootstrap_token_hash=None,
            api_key_auth_enabled=False,
            totp_secret_encrypted=None,
            totp_last_verified_step=None,
            sticky_reallocation_primary_budget_threshold_pct=95.0,
            sticky_reallocation_secondary_budget_threshold_pct=100.0,
            additional_quota_routing_policies_json="{}",
            model_aliases_json="{}",
            limit_warmup_enabled=False,
            limit_warmup_windows="both",
            limit_warmup_model="auto",
            limit_warmup_prompt="Say OK.",
            limit_warmup_cooldown_seconds=3600,
            limit_warmup_min_available_percent=100.0,
            weekly_pace_working_days="0,1,2,3,4,5,6",
            claude_sidecar_enabled=static_settings.claude_sidecar_enabled,
            claude_sidecar_base_url=static_settings.claude_sidecar_base_url,
            claude_sidecar_api_key_encrypted=TokenEncryptor().encrypt(sidecar_api_key) if sidecar_api_key else None,
            claude_sidecar_model_prefixes_json=json.dumps(
                [
                    {"prefix": prefix.strip().lower(), "strip": prefix.strip().endswith(("-", "_"))}
                    for prefix in static_settings.claude_sidecar_model_prefixes
                    if prefix.strip()
                ],
                separators=(",", ":"),
            ),
            claude_sidecar_full_models_json="[]",
            claude_sidecar_connect_timeout_seconds=static_settings.claude_sidecar_connect_timeout_seconds,
            claude_sidecar_request_timeout_seconds=static_settings.claude_sidecar_request_timeout_seconds,
            claude_sidecar_models_cache_ttl_seconds=static_settings.claude_sidecar_models_cache_ttl_seconds,
            claude_sidecar_management_key_encrypted=(
                TokenEncryptor().encrypt(sidecar_management_key) if sidecar_management_key else None
            ),
            claude_sidecar_quota_poll_interval_seconds=static_settings.claude_sidecar_quota_poll_interval_seconds,
            claude_sidecar_auth_plans_json="[]",
            claude_sidecar_usage_poll_interval_seconds=static_settings.claude_sidecar_usage_poll_interval_seconds,
            claude_sidecar_usage_queue_batch_size=static_settings.claude_sidecar_usage_queue_batch_size,
            claude_sidecar_usage_collection_enabled=static_settings.claude_sidecar_usage_collection_enabled,
            openrouter_sidecar_enabled=static_settings.openrouter_sidecar_enabled,
            openrouter_sidecar_base_url=static_settings.openrouter_sidecar_base_url,
            openrouter_sidecar_api_key_encrypted=(
                TokenEncryptor().encrypt(static_settings.openrouter_sidecar_api_key.strip())
                if static_settings.openrouter_sidecar_api_key.strip()
                else None
            ),
            openrouter_sidecar_model_prefixes_json=json.dumps(
                [
                    {"prefix": prefix.strip().lower(), "strip": prefix.strip().endswith(("-", "_"))}
                    for prefix in static_settings.openrouter_sidecar_model_prefixes
                    if prefix.strip()
                ],
                separators=(",", ":"),
            ),
            openrouter_sidecar_full_models_json="[]",
            openrouter_sidecar_connect_timeout_seconds=static_settings.openrouter_sidecar_connect_timeout_seconds,
            openrouter_sidecar_request_timeout_seconds=static_settings.openrouter_sidecar_request_timeout_seconds,
            openrouter_sidecar_models_cache_ttl_seconds=static_settings.openrouter_sidecar_models_cache_ttl_seconds,
            omniroute_sidecar_enabled=static_settings.omniroute_sidecar_enabled,
            omniroute_sidecar_base_url=static_settings.omniroute_sidecar_base_url,
            omniroute_sidecar_api_key_encrypted=(
                TokenEncryptor().encrypt(static_settings.omniroute_sidecar_api_key.strip())
                if static_settings.omniroute_sidecar_api_key.strip()
                else None
            ),
            omniroute_sidecar_selected_models_json=json.dumps(
                static_settings.omniroute_sidecar_selected_models,
                separators=(",", ":"),
            ),
            omniroute_sidecar_prefixes_json="[]",
            omniroute_sidecar_connect_timeout_seconds=static_settings.omniroute_sidecar_connect_timeout_seconds,
            omniroute_sidecar_request_timeout_seconds=static_settings.omniroute_sidecar_request_timeout_seconds,
            omniroute_sidecar_models_cache_ttl_seconds=static_settings.omniroute_sidecar_models_cache_ttl_seconds,
            ollama_sidecar_enabled=static_settings.ollama_sidecar_enabled,
            ollama_sidecar_base_url=static_settings.ollama_sidecar_base_url,
            ollama_sidecar_api_key_encrypted=(
                TokenEncryptor().encrypt(static_settings.ollama_sidecar_api_key.strip())
                if static_settings.ollama_sidecar_api_key.strip()
                else None
            ),
            ollama_sidecar_model_prefixes_json=json.dumps(
                [
                    {"prefix": prefix.strip().lower(), "strip": prefix.strip().endswith(("-", "_"))}
                    for prefix in static_settings.ollama_sidecar_model_prefixes
                    if prefix.strip()
                ],
                separators=(",", ":"),
            ),
            ollama_sidecar_full_models_json=json.dumps(
                static_settings.ollama_sidecar_full_models,
                separators=(",", ":"),
            ),
            ollama_sidecar_connect_timeout_seconds=static_settings.ollama_sidecar_connect_timeout_seconds,
            ollama_sidecar_request_timeout_seconds=static_settings.ollama_sidecar_request_timeout_seconds,
            ollama_sidecar_models_cache_ttl_seconds=static_settings.ollama_sidecar_models_cache_ttl_seconds,
        )
        self._session.add(row)
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            existing = await self._session.get(DashboardSettings, _SETTINGS_ID)
            if existing is None:
                raise
            return existing
        await self._session.refresh(row)
        return row

    async def update(
        self,
        *,
        sticky_threads_enabled: bool | None = None,
        upstream_stream_transport: str | None = None,
        upstream_proxy_routing_enabled: bool | None = None,
        upstream_proxy_default_pool_id: str | None | object = _UNSET,
        prefer_earlier_reset_accounts: bool | None = None,
        prefer_earlier_reset_window: str | None = None,
        routing_strategy: str | None = None,
        relative_availability_power: float | None = None,
        relative_availability_top_k: int | None = None,
        single_account_id: str | None = None,
        openai_cache_affinity_max_age_seconds: int | None = None,
        dashboard_session_ttl_seconds: int | None = None,
        http_responses_session_bridge_prompt_cache_idle_ttl_seconds: int | None = None,
        http_responses_session_bridge_gateway_safe_mode: bool | None = None,
        sticky_reallocation_budget_threshold_pct: float | None = None,
        sticky_reallocation_primary_budget_threshold_pct: float | None = None,
        sticky_reallocation_secondary_budget_threshold_pct: float | None = None,
        additional_quota_routing_policies_json: str | None = None,
        model_aliases_json: str | None = None,
        warmup_model: str | None = None,
        import_without_overwrite: bool | None = None,
        totp_required_on_login: bool | None = None,
        api_key_auth_enabled: bool | None = None,
        limit_warmup_enabled: bool | None = None,
        limit_warmup_windows: str | None = None,
        limit_warmup_model: str | None = None,
        limit_warmup_prompt: str | None = None,
        limit_warmup_cooldown_seconds: int | None = None,
        limit_warmup_min_available_percent: float | None = None,
        weekly_pace_working_days: str | None = None,
        claude_sidecar_enabled: bool | None = None,
        claude_sidecar_base_url: str | None = None,
        claude_sidecar_api_key_encrypted: bytes | None | object = _UNSET,
        claude_sidecar_model_prefixes_json: str | None = None,
        claude_sidecar_full_models_json: str | None = None,
        claude_sidecar_connect_timeout_seconds: float | None = None,
        claude_sidecar_request_timeout_seconds: float | None = None,
        claude_sidecar_models_cache_ttl_seconds: float | None = None,
        claude_sidecar_last_health_status: str | None | object = _UNSET,
        claude_sidecar_last_health_message: str | None | object = _UNSET,
        claude_sidecar_last_checked_at: datetime | None | object = _UNSET,
        claude_sidecar_last_model_count: int | None | object = _UNSET,
        claude_sidecar_management_key_encrypted: bytes | None | object = _UNSET,
        claude_sidecar_quota_poll_interval_seconds: float | None = None,
        claude_sidecar_quota_state_json: str | None | object = _UNSET,
        claude_sidecar_quota_checked_at: datetime | None | object = _UNSET,
        claude_sidecar_auth_plans_json: str | None = None,
        claude_sidecar_usage_poll_interval_seconds: float | None = None,
        claude_sidecar_usage_queue_batch_size: int | None = None,
        claude_sidecar_usage_collection_enabled: bool | None = None,
        claude_sidecar_default_reasoning_effort: str | None | object = _UNSET,
        openrouter_sidecar_enabled: bool | None = None,
        openrouter_sidecar_base_url: str | None = None,
        openrouter_sidecar_api_key_encrypted: bytes | None | object = _UNSET,
        openrouter_sidecar_model_prefixes_json: str | None = None,
        openrouter_sidecar_full_models_json: str | None = None,
        openrouter_sidecar_connect_timeout_seconds: float | None = None,
        openrouter_sidecar_request_timeout_seconds: float | None = None,
        openrouter_sidecar_models_cache_ttl_seconds: float | None = None,
        openrouter_sidecar_last_health_status: str | None | object = _UNSET,
        openrouter_sidecar_last_health_message: str | None | object = _UNSET,
        openrouter_sidecar_last_checked_at: datetime | None | object = _UNSET,
        openrouter_sidecar_last_model_count: int | None | object = _UNSET,
        openrouter_sidecar_default_reasoning_effort: str | None | object = _UNSET,
        omniroute_sidecar_enabled: bool | None = None,
        omniroute_sidecar_base_url: str | None = None,
        omniroute_sidecar_api_key_encrypted: bytes | None | object = _UNSET,
        omniroute_sidecar_selected_models_json: str | None = None,
        omniroute_sidecar_prefixes_json: str | None = None,
        omniroute_sidecar_connect_timeout_seconds: float | None = None,
        omniroute_sidecar_request_timeout_seconds: float | None = None,
        omniroute_sidecar_models_cache_ttl_seconds: float | None = None,
        omniroute_sidecar_last_health_status: str | None | object = _UNSET,
        omniroute_sidecar_last_health_message: str | None | object = _UNSET,
        omniroute_sidecar_last_checked_at: datetime | None | object = _UNSET,
        omniroute_sidecar_last_model_count: int | None | object = _UNSET,
        omniroute_sidecar_default_reasoning_effort: str | None | object = _UNSET,
        ollama_sidecar_enabled: bool | None = None,
        ollama_sidecar_base_url: str | None = None,
        ollama_sidecar_api_key_encrypted: bytes | None | object = _UNSET,
        ollama_sidecar_model_prefixes_json: str | None = None,
        ollama_sidecar_full_models_json: str | None = None,
        ollama_sidecar_connect_timeout_seconds: float | None = None,
        ollama_sidecar_request_timeout_seconds: float | None = None,
        ollama_sidecar_models_cache_ttl_seconds: float | None = None,
        ollama_sidecar_last_health_status: str | None | object = _UNSET,
        ollama_sidecar_last_health_message: str | None | object = _UNSET,
        ollama_sidecar_last_checked_at: datetime | None | object = _UNSET,
        ollama_sidecar_last_model_count: int | None | object = _UNSET,
        ollama_sidecar_default_reasoning_effort: str | None | object = _UNSET,
        guest_access_enabled: bool | None = None,
    ) -> DashboardSettings:
        settings = await self.get_or_create()
        if sticky_threads_enabled is not None:
            settings.sticky_threads_enabled = sticky_threads_enabled
        if upstream_stream_transport is not None:
            settings.upstream_stream_transport = upstream_stream_transport
        if upstream_proxy_routing_enabled is not None:
            settings.upstream_proxy_routing_enabled = upstream_proxy_routing_enabled
        if upstream_proxy_default_pool_id is not _UNSET:
            settings.upstream_proxy_default_pool_id = upstream_proxy_default_pool_id or None
        if prefer_earlier_reset_accounts is not None:
            settings.prefer_earlier_reset_accounts = prefer_earlier_reset_accounts
        if prefer_earlier_reset_window is not None:
            settings.prefer_earlier_reset_window = prefer_earlier_reset_window
        if routing_strategy is not None:
            settings.routing_strategy = routing_strategy
        if relative_availability_power is not None:
            settings.relative_availability_power = relative_availability_power
        if relative_availability_top_k is not None:
            settings.relative_availability_top_k = relative_availability_top_k
        if single_account_id is not None or routing_strategy == "single_account":
            settings.single_account_id = single_account_id
        if openai_cache_affinity_max_age_seconds is not None:
            settings.openai_cache_affinity_max_age_seconds = openai_cache_affinity_max_age_seconds
        if dashboard_session_ttl_seconds is not None:
            settings.dashboard_session_ttl_seconds = dashboard_session_ttl_seconds
        if http_responses_session_bridge_prompt_cache_idle_ttl_seconds is not None:
            settings.http_responses_session_bridge_prompt_cache_idle_ttl_seconds = (
                http_responses_session_bridge_prompt_cache_idle_ttl_seconds
            )
        if http_responses_session_bridge_gateway_safe_mode is not None:
            settings.http_responses_session_bridge_gateway_safe_mode = http_responses_session_bridge_gateway_safe_mode
        if sticky_reallocation_budget_threshold_pct is not None:
            settings.sticky_reallocation_budget_threshold_pct = sticky_reallocation_budget_threshold_pct
        if sticky_reallocation_primary_budget_threshold_pct is not None:
            settings.sticky_reallocation_primary_budget_threshold_pct = sticky_reallocation_primary_budget_threshold_pct
        if sticky_reallocation_secondary_budget_threshold_pct is not None:
            settings.sticky_reallocation_secondary_budget_threshold_pct = (
                sticky_reallocation_secondary_budget_threshold_pct
            )
        if additional_quota_routing_policies_json is not None:
            settings.additional_quota_routing_policies_json = additional_quota_routing_policies_json
        if model_aliases_json is not None:
            settings.model_aliases_json = model_aliases_json
        if warmup_model is not None:
            settings.warmup_model = warmup_model
        if import_without_overwrite is not None:
            settings.import_without_overwrite = import_without_overwrite
        if totp_required_on_login is not None:
            settings.totp_required_on_login = totp_required_on_login
        if api_key_auth_enabled is not None:
            settings.api_key_auth_enabled = api_key_auth_enabled
        if limit_warmup_enabled is not None:
            settings.limit_warmup_enabled = limit_warmup_enabled
        if limit_warmup_windows is not None:
            settings.limit_warmup_windows = limit_warmup_windows
        if limit_warmup_model is not None:
            settings.limit_warmup_model = limit_warmup_model
        if limit_warmup_prompt is not None:
            settings.limit_warmup_prompt = limit_warmup_prompt
        if limit_warmup_cooldown_seconds is not None:
            settings.limit_warmup_cooldown_seconds = limit_warmup_cooldown_seconds
        if limit_warmup_min_available_percent is not None:
            settings.limit_warmup_min_available_percent = limit_warmup_min_available_percent
        if weekly_pace_working_days is not None:
            settings.weekly_pace_working_days = weekly_pace_working_days
        if claude_sidecar_enabled is not None:
            settings.claude_sidecar_enabled = claude_sidecar_enabled
        if claude_sidecar_base_url is not None:
            settings.claude_sidecar_base_url = claude_sidecar_base_url
        if claude_sidecar_api_key_encrypted is not _UNSET:
            settings.claude_sidecar_api_key_encrypted = claude_sidecar_api_key_encrypted
        if claude_sidecar_model_prefixes_json is not None:
            settings.claude_sidecar_model_prefixes_json = claude_sidecar_model_prefixes_json
        if claude_sidecar_full_models_json is not None:
            settings.claude_sidecar_full_models_json = claude_sidecar_full_models_json
        if claude_sidecar_connect_timeout_seconds is not None:
            settings.claude_sidecar_connect_timeout_seconds = claude_sidecar_connect_timeout_seconds
        if claude_sidecar_request_timeout_seconds is not None:
            settings.claude_sidecar_request_timeout_seconds = claude_sidecar_request_timeout_seconds
        if claude_sidecar_models_cache_ttl_seconds is not None:
            settings.claude_sidecar_models_cache_ttl_seconds = claude_sidecar_models_cache_ttl_seconds
        if claude_sidecar_last_health_status is not _UNSET:
            settings.claude_sidecar_last_health_status = claude_sidecar_last_health_status
        if claude_sidecar_last_health_message is not _UNSET:
            settings.claude_sidecar_last_health_message = claude_sidecar_last_health_message
        if claude_sidecar_last_checked_at is not _UNSET:
            settings.claude_sidecar_last_checked_at = claude_sidecar_last_checked_at
        if claude_sidecar_last_model_count is not _UNSET:
            settings.claude_sidecar_last_model_count = claude_sidecar_last_model_count
        if claude_sidecar_management_key_encrypted is not _UNSET:
            settings.claude_sidecar_management_key_encrypted = claude_sidecar_management_key_encrypted
        if claude_sidecar_quota_poll_interval_seconds is not None:
            settings.claude_sidecar_quota_poll_interval_seconds = claude_sidecar_quota_poll_interval_seconds
        if claude_sidecar_quota_state_json is not _UNSET:
            settings.claude_sidecar_quota_state_json = claude_sidecar_quota_state_json
        if claude_sidecar_quota_checked_at is not _UNSET:
            settings.claude_sidecar_quota_checked_at = claude_sidecar_quota_checked_at
        if claude_sidecar_auth_plans_json is not None:
            settings.claude_sidecar_auth_plans_json = claude_sidecar_auth_plans_json
        if claude_sidecar_usage_poll_interval_seconds is not None:
            settings.claude_sidecar_usage_poll_interval_seconds = claude_sidecar_usage_poll_interval_seconds
        if claude_sidecar_usage_queue_batch_size is not None:
            settings.claude_sidecar_usage_queue_batch_size = claude_sidecar_usage_queue_batch_size
        if claude_sidecar_usage_collection_enabled is not None:
            settings.claude_sidecar_usage_collection_enabled = claude_sidecar_usage_collection_enabled
        if claude_sidecar_default_reasoning_effort is not _UNSET:
            settings.claude_sidecar_default_reasoning_effort = claude_sidecar_default_reasoning_effort
        if openrouter_sidecar_enabled is not None:
            settings.openrouter_sidecar_enabled = openrouter_sidecar_enabled
        if openrouter_sidecar_base_url is not None:
            settings.openrouter_sidecar_base_url = openrouter_sidecar_base_url
        if openrouter_sidecar_api_key_encrypted is not _UNSET:
            settings.openrouter_sidecar_api_key_encrypted = openrouter_sidecar_api_key_encrypted
        if openrouter_sidecar_model_prefixes_json is not None:
            settings.openrouter_sidecar_model_prefixes_json = openrouter_sidecar_model_prefixes_json
        if openrouter_sidecar_full_models_json is not None:
            settings.openrouter_sidecar_full_models_json = openrouter_sidecar_full_models_json
        if openrouter_sidecar_connect_timeout_seconds is not None:
            settings.openrouter_sidecar_connect_timeout_seconds = openrouter_sidecar_connect_timeout_seconds
        if openrouter_sidecar_request_timeout_seconds is not None:
            settings.openrouter_sidecar_request_timeout_seconds = openrouter_sidecar_request_timeout_seconds
        if openrouter_sidecar_models_cache_ttl_seconds is not None:
            settings.openrouter_sidecar_models_cache_ttl_seconds = openrouter_sidecar_models_cache_ttl_seconds
        if openrouter_sidecar_last_health_status is not _UNSET:
            settings.openrouter_sidecar_last_health_status = openrouter_sidecar_last_health_status
        if openrouter_sidecar_last_health_message is not _UNSET:
            settings.openrouter_sidecar_last_health_message = openrouter_sidecar_last_health_message
        if openrouter_sidecar_last_checked_at is not _UNSET:
            settings.openrouter_sidecar_last_checked_at = openrouter_sidecar_last_checked_at
        if openrouter_sidecar_last_model_count is not _UNSET:
            settings.openrouter_sidecar_last_model_count = openrouter_sidecar_last_model_count
        if openrouter_sidecar_default_reasoning_effort is not _UNSET:
            settings.openrouter_sidecar_default_reasoning_effort = openrouter_sidecar_default_reasoning_effort
        if omniroute_sidecar_enabled is not None:
            settings.omniroute_sidecar_enabled = omniroute_sidecar_enabled
        if omniroute_sidecar_base_url is not None:
            settings.omniroute_sidecar_base_url = omniroute_sidecar_base_url
        if omniroute_sidecar_api_key_encrypted is not _UNSET:
            settings.omniroute_sidecar_api_key_encrypted = omniroute_sidecar_api_key_encrypted
        if omniroute_sidecar_selected_models_json is not None:
            settings.omniroute_sidecar_selected_models_json = omniroute_sidecar_selected_models_json
        if omniroute_sidecar_prefixes_json is not None:
            settings.omniroute_sidecar_prefixes_json = omniroute_sidecar_prefixes_json
        if omniroute_sidecar_connect_timeout_seconds is not None:
            settings.omniroute_sidecar_connect_timeout_seconds = omniroute_sidecar_connect_timeout_seconds
        if omniroute_sidecar_request_timeout_seconds is not None:
            settings.omniroute_sidecar_request_timeout_seconds = omniroute_sidecar_request_timeout_seconds
        if omniroute_sidecar_models_cache_ttl_seconds is not None:
            settings.omniroute_sidecar_models_cache_ttl_seconds = omniroute_sidecar_models_cache_ttl_seconds
        if omniroute_sidecar_last_health_status is not _UNSET:
            settings.omniroute_sidecar_last_health_status = omniroute_sidecar_last_health_status
        if omniroute_sidecar_last_health_message is not _UNSET:
            settings.omniroute_sidecar_last_health_message = omniroute_sidecar_last_health_message
        if omniroute_sidecar_last_checked_at is not _UNSET:
            settings.omniroute_sidecar_last_checked_at = omniroute_sidecar_last_checked_at
        if omniroute_sidecar_last_model_count is not _UNSET:
            settings.omniroute_sidecar_last_model_count = omniroute_sidecar_last_model_count
        if omniroute_sidecar_default_reasoning_effort is not _UNSET:
            settings.omniroute_sidecar_default_reasoning_effort = omniroute_sidecar_default_reasoning_effort
        if ollama_sidecar_enabled is not None:
            settings.ollama_sidecar_enabled = ollama_sidecar_enabled
        if ollama_sidecar_base_url is not None:
            settings.ollama_sidecar_base_url = ollama_sidecar_base_url
        if ollama_sidecar_api_key_encrypted is not _UNSET:
            settings.ollama_sidecar_api_key_encrypted = ollama_sidecar_api_key_encrypted
        if ollama_sidecar_model_prefixes_json is not None:
            settings.ollama_sidecar_model_prefixes_json = ollama_sidecar_model_prefixes_json
        if ollama_sidecar_full_models_json is not None:
            settings.ollama_sidecar_full_models_json = ollama_sidecar_full_models_json
        if ollama_sidecar_connect_timeout_seconds is not None:
            settings.ollama_sidecar_connect_timeout_seconds = ollama_sidecar_connect_timeout_seconds
        if ollama_sidecar_request_timeout_seconds is not None:
            settings.ollama_sidecar_request_timeout_seconds = ollama_sidecar_request_timeout_seconds
        if ollama_sidecar_models_cache_ttl_seconds is not None:
            settings.ollama_sidecar_models_cache_ttl_seconds = ollama_sidecar_models_cache_ttl_seconds
        if ollama_sidecar_last_health_status is not _UNSET:
            settings.ollama_sidecar_last_health_status = ollama_sidecar_last_health_status
        if ollama_sidecar_last_health_message is not _UNSET:
            settings.ollama_sidecar_last_health_message = ollama_sidecar_last_health_message
        if ollama_sidecar_last_checked_at is not _UNSET:
            settings.ollama_sidecar_last_checked_at = ollama_sidecar_last_checked_at
        if ollama_sidecar_last_model_count is not _UNSET:
            settings.ollama_sidecar_last_model_count = ollama_sidecar_last_model_count
        if ollama_sidecar_default_reasoning_effort is not _UNSET:
            settings.ollama_sidecar_default_reasoning_effort = ollama_sidecar_default_reasoning_effort
        if guest_access_enabled is not None:
            settings.guest_access_enabled = guest_access_enabled
        await self.commit_refresh(settings)
        return settings

    async def commit_refresh(self, settings: DashboardSettings) -> None:
        await self._session.commit()
        await self._session.refresh(settings)
