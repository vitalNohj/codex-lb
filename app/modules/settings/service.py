from __future__ import annotations

import json
<<<<<<< 22625a07e
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
||||||| 84fde5a1e
from dataclasses import dataclass
=======
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
>>>>>>> 72630bbfe

<<<<<<< 22625a07e
from app.core.clients.claude_sidecar import SidecarPrefix
from app.core.config.product_capabilities import omniroute_enabled
from app.core.config.settings import get_settings
from app.core.crypto import TokenEncryptor
from app.modules.openai_compat.endpoints import (
    OpenAICompatEndpointUpdateData,
    StoredOpenAICompatEndpoint,
    dump_openai_compat_endpoints,
    merge_openai_compat_endpoints,
    parse_openai_compat_endpoints,
)
from app.modules.proxy.sidecar_routing import (
    SidecarRoutingDecision,
    SidecarRoutingEntry,
    apply_full_model_stars,
    parse_full_model_stars,
    resolve_sidecar_pool_target,
)
from app.modules.settings.dashboard_layout import (
    DashboardLayoutVisibility,
    dump_dashboard_layout,
    parse_dashboard_layout,
)
from app.modules.settings.model_alias_pools import (
    MAX_ALIAS_LENGTH,
    MAX_POOL_TARGETS,
    MAX_TARGET_LENGTH,
    ModelAliasPool,
    ModelAliasPools,
    dump_alias_pools_json,
    normalize_alias_pools,
    parse_alias_pools_json,
)
||||||| 84fde5a1e
from app.core.config.settings import get_settings
=======
from app.core.auth.dashboard_access import is_admin_level
from app.core.clients.thread_cache_identity import (
    THREAD_CACHE_IDENTITY_MODE_DEFAULT,
    normalize_thread_cache_identity_mode,
)
from app.core.config.background_jobs import BACKGROUND_JOB_SETTINGS
from app.core.config.dashboard_overrides import DASHBOARD_TIMEOUT_SETTINGS

# Re-exported: the resolver lives in ``app.core.config.inheritable`` so hot
# paths in ``app.core`` share it without importing this module.
from app.core.config.inheritable import InheritableValue as InheritableValue
from app.core.config.inheritable import SettingScalar as SettingScalar
from app.core.config.inheritable import SettingSource as SettingSource
from app.core.config.inheritable import resolve_inheritable as resolve_inheritable
from app.core.config.settings import Settings, get_settings
from app.core.config.spool_retention import OPERATION_SPOOL_RETENTION_SETTING
from app.core.conversation_archive import CONVERSATION_ARCHIVE_SETTING
from app.core.resilience.toggles import RESILIENCE_TOGGLE_SETTINGS
from app.db.models import DashboardSettings, LocalLoginPolicy
from app.modules.dashboard_roles.service import resolve_role_grants
from app.modules.dashboard_users.break_glass import BreakGlassRequiresTotpError
>>>>>>> 72630bbfe
from app.modules.settings.repository import SettingsRepository
from app.modules.usage.additional_quota_keys import (
    normalize_additional_quota_key,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ClaudeSidecarAuthPlanData:
    auth_index: str | None
    email: str | None
    source: str | None
    plan_type: str
    primary_token_budget: int | None
    secondary_token_budget: int | None


@dataclass(frozen=True, slots=True)
class DashboardSettingsData:
    sticky_threads_enabled: bool
    upstream_stream_transport: str
    prohibit_fast_mode: bool
    http_downstream_transport_policy: str
    # Effective mode; ``provenance`` carries the source and the fallbacks.
    thread_cache_identity_mode: str
    thread_cache_identity_mode_override: str | None
    proxy_account_response_create_limit: int
    proxy_account_response_create_limit_override: int | None
    proxy_account_stream_limit: int
    proxy_account_stream_limit_override: int | None
    proxy_account_stream_recovery_reserve: int
    proxy_account_stream_recovery_reserve_override: int | None
    proxy_api_key_fair_share_congestion_threshold_pct: int
    proxy_api_key_fair_share_congestion_threshold_pct_override: int | None
    # C2-2 routing/overload: effective values; the dashboard-stored value and
    # the fallbacks are reported through ``provenance``.
    proxy_overload_isolation_seconds: int
    proxy_account_error_rate_weighting_enabled: bool
    proxy_account_inflight_penalty_pct: float
    proxy_account_lease_token_weight: float
    proxy_account_lease_ttl_seconds: float
    # end C2-2 routing/overload
    upstream_proxy_routing_enabled: bool
    upstream_proxy_default_pool_id: str | None
    prefer_earlier_reset_accounts: bool
    prefer_earlier_reset_window: str
    show_reset_credit_badges: bool
    auto_redeem_reset_credits_before_expiry: bool
    show_reset_credit_expiry_badge: bool
    routing_strategy: str
    relative_availability_power: float
    relative_availability_top_k: int
    single_account_id: str | None
    openai_cache_affinity_max_age_seconds: int
    dashboard_session_ttl_seconds: int
    http_responses_session_bridge_prompt_cache_idle_ttl_seconds: int
    http_responses_session_bridge_gateway_safe_mode: bool
    # M3 codex prewarm: effective value (dashboard column, else the deprecated
    # env alias, else the code default); provenance carries the source.
    http_responses_session_bridge_codex_prewarm_enabled: bool
    # end M3 codex prewarm
    sticky_reallocation_budget_threshold_pct: float
    sticky_reallocation_primary_budget_threshold_pct: float
    sticky_reallocation_secondary_budget_threshold_pct: float
    additional_quota_routing_policies: dict[str, str]
    model_aliases: ModelAliasPools
    custom_alias_catalog: dict[str, dict[str, int]]
    warmup_model: str
    import_without_overwrite: bool
    totp_required_on_login: bool
    totp_required_for_admin_role: bool
    local_login_policy: str
    users_without_totp_count: int
    admins_without_totp_count: int
    api_key_auth_enabled: bool
    hide_upstream_quota_from_api_keys: bool
    limit_warmup_enabled: bool
    limit_warmup_windows: str
    limit_warmup_model: str
    limit_warmup_prompt: str
    limit_warmup_cooldown_seconds: int
    limit_warmup_exhausted_threshold_percent: float
    limit_warmup_idle_threshold_percent: float
    limit_warmup_min_available_percent: float
    weekly_pace_working_days: str
    weekly_pace_smoothing_minutes: int
    claude_sidecar_enabled: bool
    claude_sidecar_base_url: str
    claude_sidecar_api_key_configured: bool
    claude_sidecar_model_prefixes: list[SidecarPrefix]
    claude_sidecar_full_models: list[str]
    claude_sidecar_connect_timeout_seconds: float
    claude_sidecar_request_timeout_seconds: float
    claude_sidecar_models_cache_ttl_seconds: float
    claude_sidecar_last_health_status: str | None
    claude_sidecar_last_health_message: str | None
    claude_sidecar_last_checked_at: datetime | None
    claude_sidecar_last_model_count: int | None
    claude_sidecar_management_key_configured: bool
    claude_sidecar_quota_poll_interval_seconds: float
    claude_sidecar_auth_plans: list[ClaudeSidecarAuthPlanData]
    claude_sidecar_usage_poll_interval_seconds: float
    claude_sidecar_usage_queue_batch_size: int
    claude_sidecar_usage_collection_enabled: bool
    claude_sidecar_default_reasoning_effort: str | None
    openrouter_sidecar_enabled: bool
    openrouter_sidecar_base_url: str
    openrouter_sidecar_api_key_configured: bool
    openrouter_sidecar_model_prefixes: list[SidecarPrefix]
    openrouter_sidecar_full_models: list[str]
    openrouter_sidecar_connect_timeout_seconds: float
    openrouter_sidecar_request_timeout_seconds: float
    openrouter_sidecar_models_cache_ttl_seconds: float
    openrouter_sidecar_last_health_status: str | None
    openrouter_sidecar_last_health_message: str | None
    openrouter_sidecar_last_checked_at: datetime | None
    openrouter_sidecar_last_model_count: int | None
    openrouter_sidecar_default_reasoning_effort: str | None
    openai_compat_endpoints: list[StoredOpenAICompatEndpoint]
    orcarouter_sidecar_enabled: bool
    orcarouter_sidecar_base_url: str
    orcarouter_sidecar_api_key_configured: bool
    orcarouter_sidecar_model_prefixes: list[SidecarPrefix]
    orcarouter_sidecar_full_models: list[str]
    orcarouter_sidecar_connect_timeout_seconds: float
    orcarouter_sidecar_request_timeout_seconds: float
    orcarouter_sidecar_models_cache_ttl_seconds: float
    orcarouter_sidecar_last_health_status: str | None
    orcarouter_sidecar_last_health_message: str | None
    orcarouter_sidecar_last_checked_at: datetime | None
    orcarouter_sidecar_last_model_count: int | None
    orcarouter_sidecar_default_reasoning_effort: str | None
    opencode_go_sidecar_enabled: bool
    opencode_go_sidecar_base_url: str
    opencode_go_sidecar_api_key_configured: bool
    opencode_go_sidecar_model_prefixes: list[SidecarPrefix]
    opencode_go_sidecar_full_models: list[str]
    opencode_go_sidecar_connect_timeout_seconds: float
    opencode_go_sidecar_request_timeout_seconds: float
    opencode_go_sidecar_models_cache_ttl_seconds: float
    opencode_go_sidecar_last_health_status: str | None
    opencode_go_sidecar_last_health_message: str | None
    opencode_go_sidecar_last_checked_at: datetime | None
    opencode_go_sidecar_last_model_count: int | None
    omniroute_sidecar_enabled: bool
    omniroute_sidecar_base_url: str
    omniroute_sidecar_api_key_configured: bool
    omniroute_sidecar_model_prefixes: list[SidecarPrefix]
    omniroute_sidecar_full_models: list[str]
    omniroute_sidecar_selected_models: list[str]
    omniroute_sidecar_connect_timeout_seconds: float
    omniroute_sidecar_request_timeout_seconds: float
    omniroute_sidecar_models_cache_ttl_seconds: float
    omniroute_sidecar_last_health_status: str | None
    omniroute_sidecar_last_health_message: str | None
    omniroute_sidecar_last_checked_at: datetime | None
    omniroute_sidecar_last_model_count: int | None
    omniroute_sidecar_default_reasoning_effort: str | None
    ollama_sidecar_enabled: bool
    ollama_sidecar_base_url: str
    ollama_sidecar_api_key_configured: bool
    ollama_sidecar_model_prefixes: list[SidecarPrefix]
    ollama_sidecar_full_models: list[str]
    ollama_sidecar_connect_timeout_seconds: float
    ollama_sidecar_request_timeout_seconds: float
    ollama_sidecar_models_cache_ttl_seconds: float
    ollama_sidecar_last_health_status: str | None
    ollama_sidecar_last_health_message: str | None
    ollama_sidecar_last_checked_at: datetime | None
    ollama_sidecar_last_model_count: int | None
    ollama_sidecar_default_reasoning_effort: str | None
    # Lower-cased full model -> provider key of the integration starred as the
    # model's default route.
    sidecar_full_model_stars: dict[str, str]
    guest_access_enabled: bool
    guest_password_configured: bool
    limit_warmup_staggered_idle_enabled: bool
    request_log_retention_days: int
    usage_history_retention_days: int
    hourly_rollup_retention_days: int
    request_log_retention_override_days: int | None
    usage_history_retention_override_days: int | None
<<<<<<< 22625a07e
    hourly_rollup_retention_override_days: int | None
||||||| 84fde5a1e
=======
    # C2-3 resilience toggles: effective values (dashboard column, else the
    # deprecated env alias, else the code default); provenance carries the source.
    soft_drain_enabled: bool
    deterministic_failover_enabled: bool
    circuit_breaker_enabled: bool
    # M2 background jobs: effective values (dashboard column, else the deprecated
    # env alias, else the code default); provenance carries the source. The
    # guardian additionally reports whether the static topology blocks it.
    auth_guardian_enabled: bool
    auth_guardian_blocked_by_topology: bool
    automations_scheduler_enabled: bool
    rate_limit_reset_credits_refresh_enabled: bool
    # end M2 background jobs
    # M5 conversation archive: effective toggle; provenance carries the source.
    conversation_archive_enabled: bool
    # end M5 conversation archive
    # R2 spool retention: effective retention of the durable HTTP-bridge
    # operation spool (dashboard column, else the deprecated env alias, else
    # the code default); provenance carries the source.
    http_responses_session_bridge_operation_spool_retention_seconds: float
    # end R2 spool retention
>>>>>>> 72630bbfe
    version: int
<<<<<<< 22625a07e
    cliproxy_capacity_routing_enabled: bool = True
    dashboard_layout: DashboardLayoutVisibility = field(default_factory=DashboardLayoutVisibility)
||||||| 84fde5a1e
=======
    # C2-1 timeouts: effective values (dashboard column, else environment,
    # else code default); the column values are exposed through ``provenance``.
    upstream_connect_timeout_seconds: float
    proxy_request_budget_seconds: float
    compact_request_budget_seconds: float
    transcription_request_budget_seconds: float
    stream_idle_timeout_seconds: float
    proxy_downstream_websocket_idle_timeout_seconds: float
    sse_keepalive_interval_seconds: float
    # end C2-1 timeouts
    # M1 stream/bridge budgets: effective values (dashboard column, else
    # environment, else code default); provenance carries the source.
    http_responses_stream_request_budget_seconds: float
    http_responses_session_bridge_request_budget_seconds: float
    # end M1 stream/bridge budgets
    # Effective value, source and fallbacks of every inheritable setting, keyed
    # by setting name; the settings API exposes it as ``provenance``.
    provenance: Mapping[str, InheritableValue[Any]] = field(default_factory=dict)
>>>>>>> 72630bbfe


@dataclass(frozen=True, slots=True)
class DashboardSettingsUpdateData:
    sticky_threads_enabled: bool
    upstream_stream_transport: str
    prohibit_fast_mode: bool
    http_downstream_transport_policy: str
    thread_cache_identity_mode: str | None
    clear_thread_cache_identity_mode: bool
    proxy_account_response_create_limit: int | None
    clear_proxy_account_response_create_limit: bool
    proxy_account_stream_limit: int | None
    clear_proxy_account_stream_limit: bool
    proxy_account_stream_recovery_reserve: int | None
    clear_proxy_account_stream_recovery_reserve: bool
    proxy_api_key_fair_share_congestion_threshold_pct: int | None
    clear_proxy_api_key_fair_share_congestion_threshold_pct: bool
    # C2-2 routing/overload (tri-state: value = store, clear flag = inherit)
    proxy_overload_isolation_seconds: int | None
    clear_proxy_overload_isolation_seconds: bool
    proxy_account_error_rate_weighting_enabled: bool | None
    clear_proxy_account_error_rate_weighting_enabled: bool
    proxy_account_inflight_penalty_pct: float | None
    clear_proxy_account_inflight_penalty_pct: bool
    proxy_account_lease_token_weight: float | None
    clear_proxy_account_lease_token_weight: bool
    proxy_account_lease_ttl_seconds: float | None
    clear_proxy_account_lease_ttl_seconds: bool
    # end C2-2 routing/overload
    upstream_proxy_routing_enabled: bool
    upstream_proxy_default_pool_id: str | None
    prefer_earlier_reset_accounts: bool
    prefer_earlier_reset_window: str
    show_reset_credit_badges: bool
    auto_redeem_reset_credits_before_expiry: bool
    show_reset_credit_expiry_badge: bool
    routing_strategy: str
    relative_availability_power: float
    relative_availability_top_k: int
    single_account_id: str | None
    openai_cache_affinity_max_age_seconds: int
    dashboard_session_ttl_seconds: int
    http_responses_session_bridge_prompt_cache_idle_ttl_seconds: int
    http_responses_session_bridge_gateway_safe_mode: bool
    sticky_reallocation_budget_threshold_pct: float
    sticky_reallocation_primary_budget_threshold_pct: float
    sticky_reallocation_secondary_budget_threshold_pct: float
    additional_quota_routing_policies: dict[str, str]
    model_aliases: ModelAliasPools
    custom_alias_catalog: dict[str, dict[str, int]]
    warmup_model: str
    import_without_overwrite: bool
    totp_required_on_login: bool
    totp_required_for_admin_role: bool
    local_login_policy: str | None
    api_key_auth_enabled: bool
    hide_upstream_quota_from_api_keys: bool
    limit_warmup_enabled: bool
    limit_warmup_windows: str
    limit_warmup_model: str
    limit_warmup_prompt: str
    limit_warmup_cooldown_seconds: int
    limit_warmup_exhausted_threshold_percent: float
    limit_warmup_idle_threshold_percent: float
    limit_warmup_min_available_percent: float
    weekly_pace_working_days: str
    weekly_pace_smoothing_minutes: int
    claude_sidecar_enabled: bool
    claude_sidecar_base_url: str
    claude_sidecar_api_key: str | None
    claude_sidecar_clear_api_key: bool
    claude_sidecar_model_prefixes: list[SidecarPrefix]
    claude_sidecar_full_models: list[str]
    claude_sidecar_connect_timeout_seconds: float
    claude_sidecar_request_timeout_seconds: float
    claude_sidecar_models_cache_ttl_seconds: float
    claude_sidecar_management_key: str | None
    claude_sidecar_clear_management_key: bool
    claude_sidecar_quota_poll_interval_seconds: float
    claude_sidecar_auth_plans: list[ClaudeSidecarAuthPlanData]
    claude_sidecar_usage_poll_interval_seconds: float
    claude_sidecar_usage_queue_batch_size: int
    claude_sidecar_usage_collection_enabled: bool
    claude_sidecar_default_reasoning_effort: str | None
    openrouter_sidecar_enabled: bool
    openrouter_sidecar_base_url: str
    openrouter_sidecar_api_key: str | None
    openrouter_sidecar_clear_api_key: bool
    openrouter_sidecar_model_prefixes: list[SidecarPrefix]
    openrouter_sidecar_full_models: list[str]
    openrouter_sidecar_connect_timeout_seconds: float
    openrouter_sidecar_request_timeout_seconds: float
    openrouter_sidecar_models_cache_ttl_seconds: float
    openrouter_sidecar_default_reasoning_effort: str | None
    openai_compat_endpoints: list[OpenAICompatEndpointUpdateData]
    orcarouter_sidecar_enabled: bool
    orcarouter_sidecar_base_url: str
    orcarouter_sidecar_api_key: str | None
    orcarouter_sidecar_clear_api_key: bool
    orcarouter_sidecar_model_prefixes: list[SidecarPrefix]
    orcarouter_sidecar_full_models: list[str]
    orcarouter_sidecar_connect_timeout_seconds: float
    orcarouter_sidecar_request_timeout_seconds: float
    orcarouter_sidecar_models_cache_ttl_seconds: float
    orcarouter_sidecar_default_reasoning_effort: str | None
    opencode_go_sidecar_enabled: bool
    opencode_go_sidecar_base_url: str
    opencode_go_sidecar_api_key: str | None
    opencode_go_sidecar_clear_api_key: bool
    opencode_go_sidecar_model_prefixes: list[SidecarPrefix]
    opencode_go_sidecar_full_models: list[str]
    opencode_go_sidecar_connect_timeout_seconds: float
    opencode_go_sidecar_request_timeout_seconds: float
    opencode_go_sidecar_models_cache_ttl_seconds: float
    omniroute_sidecar_enabled: bool
    omniroute_sidecar_base_url: str
    omniroute_sidecar_api_key: str | None
    omniroute_sidecar_clear_api_key: bool
    omniroute_sidecar_model_prefixes: list[SidecarPrefix]
    omniroute_sidecar_full_models: list[str]
    omniroute_sidecar_selected_models: list[str]
    omniroute_sidecar_connect_timeout_seconds: float
    omniroute_sidecar_request_timeout_seconds: float
    omniroute_sidecar_models_cache_ttl_seconds: float
    omniroute_sidecar_default_reasoning_effort: str | None
    ollama_sidecar_enabled: bool
    ollama_sidecar_base_url: str
    ollama_sidecar_api_key: str | None
    ollama_sidecar_clear_api_key: bool
    ollama_sidecar_model_prefixes: list[SidecarPrefix]
    ollama_sidecar_full_models: list[str]
    ollama_sidecar_connect_timeout_seconds: float
    ollama_sidecar_request_timeout_seconds: float
    ollama_sidecar_models_cache_ttl_seconds: float
    ollama_sidecar_default_reasoning_effort: str | None
    guest_access_enabled: bool
    limit_warmup_staggered_idle_enabled: bool
    # Tri-state retention overrides: value set = store, clear flag = reset to
    # NULL (not configured = retention disabled), neither = leave untouched.
    request_log_retention_override_days: int | None
    usage_history_retention_override_days: int | None
    clear_request_log_retention_override: bool
    clear_usage_history_retention_override: bool
<<<<<<< 22625a07e
    # Lower-cased full model -> provider key of the integration starred as the
    # model's default route. ``None`` keeps the stored stars, so a client that
    # predates stars cannot erase them by saving; a submitted map replaces the
    # stored one and is re-filtered against the cards in the same save.
    sidecar_full_model_stars: dict[str, str] | None = None
    # Hourly-rollup retention joins the tri-state retention group; defaulted
    # so existing update payloads that predate the field keep constructing
    # the dataclass unchanged (None/False = leave the stored value untouched).
    hourly_rollup_retention_override_days: int | None = None
    clear_hourly_rollup_retention_override: bool = False
    cliproxy_capacity_routing_enabled: bool | None = None
    dashboard_layout: DashboardLayoutVisibility | None = None


@dataclass(frozen=True, slots=True)
class SidecarRoutingConflict:
    kind: str
    value: str
    owner: str
    challenger: str


class SidecarRoutingConflictError(ValueError):
    def __init__(self, conflict: SidecarRoutingConflict) -> None:
        self.conflict = conflict
        super().__init__(
            f"{conflict.kind} '{conflict.value}' is already used by {conflict.owner}; "
            f"{conflict.challenger} cannot use it"
        )


class ModelAliasPoolError(ValueError):
    """An alias pool the operator submitted cannot be saved.

    Carries the alias and offending target so the dashboard can attach the
    message to the right row instead of a page-level toast.
    """

    def __init__(self, message: str, *, alias: str, target: str | None = None) -> None:
        self.alias = alias
        self.target = target
        super().__init__(message)
||||||| 84fde5a1e
=======
    # C2-3 resilience toggles: tri-state (value = store, clear flag = back to
    # NULL so the env alias / default applies again, neither = untouched).
    soft_drain_enabled: bool | None = None
    clear_soft_drain_enabled: bool = False
    deterministic_failover_enabled: bool | None = None
    clear_deterministic_failover_enabled: bool = False
    circuit_breaker_enabled: bool | None = None
    clear_circuit_breaker_enabled: bool = False
    # M2 background jobs: tri-state like the resilience toggles.
    auth_guardian_enabled: bool | None = None
    clear_auth_guardian_enabled: bool = False
    automations_scheduler_enabled: bool | None = None
    clear_automations_scheduler_enabled: bool = False
    rate_limit_reset_credits_refresh_enabled: bool | None = None
    clear_rate_limit_reset_credits_refresh_enabled: bool = False
    # end M2 background jobs
    # M5 conversation archive: tri-state like the resilience toggles.
    conversation_archive_enabled: bool | None = None
    clear_conversation_archive_enabled: bool = False
    # end M5 conversation archive
    # R2 spool retention: tri-state like the C2-1 timeouts.
    http_responses_session_bridge_operation_spool_retention_seconds: float | None = None
    clear_http_responses_session_bridge_operation_spool_retention_seconds: bool = False
    # end R2 spool retention
    # C2-1 timeouts (tri-state like the caps: value = store, clear = NULL,
    # neither = untouched).
    upstream_connect_timeout_seconds: float | None = None
    clear_upstream_connect_timeout_seconds: bool = False
    proxy_request_budget_seconds: float | None = None
    clear_proxy_request_budget_seconds: bool = False
    compact_request_budget_seconds: float | None = None
    clear_compact_request_budget_seconds: bool = False
    transcription_request_budget_seconds: float | None = None
    clear_transcription_request_budget_seconds: bool = False
    stream_idle_timeout_seconds: float | None = None
    clear_stream_idle_timeout_seconds: bool = False
    proxy_downstream_websocket_idle_timeout_seconds: float | None = None
    clear_proxy_downstream_websocket_idle_timeout_seconds: bool = False
    sse_keepalive_interval_seconds: float | None = None
    clear_sse_keepalive_interval_seconds: bool = False
    # end C2-1 timeouts
    # M3 codex prewarm (tri-state: value = store, clear flag = back to NULL so
    # the env alias / default applies again, neither = untouched).
    http_responses_session_bridge_codex_prewarm_enabled: bool | None = None
    clear_http_responses_session_bridge_codex_prewarm_enabled: bool = False
    # end M3 codex prewarm
    # M1 stream/bridge budgets (tri-state like the C2-1 timeouts).
    http_responses_stream_request_budget_seconds: float | None = None
    clear_http_responses_stream_request_budget_seconds: bool = False
    http_responses_session_bridge_request_budget_seconds: float | None = None
    clear_http_responses_session_bridge_request_budget_seconds: bool = False
    # end M1 stream/bridge budgets


@dataclass(frozen=True, slots=True)
class TotpEnrollmentSummary:
    """Who still has to enrol, and whether the acting account already did."""

    actor_configured: bool
    users_without_totp: int
    admins_without_totp: int
>>>>>>> 72630bbfe


class SettingsService:
    def __init__(self, repository: SettingsRepository) -> None:
        self._repository = repository
        self._encryptor = TokenEncryptor()

<<<<<<< 22625a07e
    async def get_settings(self) -> DashboardSettingsData:
        row = await self._repository.get_or_create()
        return self._to_data(row)
||||||| 84fde5a1e
    async def get_settings(self) -> DashboardSettingsData:
        row = await self._repository.get_or_create()
        return DashboardSettingsData(
            sticky_threads_enabled=row.sticky_threads_enabled,
            upstream_stream_transport=row.upstream_stream_transport,
            prohibit_fast_mode=row.prohibit_fast_mode,
            http_downstream_transport_policy=row.http_downstream_transport_policy,
            proxy_account_response_create_limit=_effective_response_create_limit(
                row.proxy_account_response_create_limit
            ),
            proxy_account_stream_limit=_effective_stream_limit(row.proxy_account_stream_limit),
            proxy_account_stream_recovery_reserve=_effective_stream_recovery_reserve(
                row.proxy_account_stream_recovery_reserve
            ),
            proxy_api_key_fair_share_congestion_threshold_pct=_effective_api_key_fair_share_threshold_pct(
                row.proxy_api_key_fair_share_congestion_threshold_pct
            ),
            upstream_proxy_routing_enabled=row.upstream_proxy_routing_enabled,
            upstream_proxy_default_pool_id=row.upstream_proxy_default_pool_id,
            prefer_earlier_reset_accounts=row.prefer_earlier_reset_accounts,
            prefer_earlier_reset_window=row.prefer_earlier_reset_window,
            show_reset_credit_badges=row.show_reset_credit_badges,
            auto_redeem_reset_credits_before_expiry=row.auto_redeem_reset_credits_before_expiry,
            show_reset_credit_expiry_badge=row.show_reset_credit_expiry_badge,
            routing_strategy=row.routing_strategy,
            relative_availability_power=row.relative_availability_power,
            relative_availability_top_k=row.relative_availability_top_k,
            single_account_id=row.single_account_id,
            openai_cache_affinity_max_age_seconds=row.openai_cache_affinity_max_age_seconds,
            dashboard_session_ttl_seconds=row.dashboard_session_ttl_seconds,
            http_responses_session_bridge_prompt_cache_idle_ttl_seconds=(
                row.http_responses_session_bridge_prompt_cache_idle_ttl_seconds
            ),
            http_responses_session_bridge_gateway_safe_mode=row.http_responses_session_bridge_gateway_safe_mode,
            sticky_reallocation_budget_threshold_pct=row.sticky_reallocation_budget_threshold_pct,
            sticky_reallocation_primary_budget_threshold_pct=row.sticky_reallocation_primary_budget_threshold_pct,
            sticky_reallocation_secondary_budget_threshold_pct=row.sticky_reallocation_secondary_budget_threshold_pct,
            additional_quota_routing_policies=_parse_additional_quota_routing_policies(
                row.additional_quota_routing_policies_json
            ),
            warmup_model=row.warmup_model,
            import_without_overwrite=row.import_without_overwrite,
            totp_required_on_login=row.totp_required_on_login,
            totp_configured=row.totp_secret_encrypted is not None,
            api_key_auth_enabled=row.api_key_auth_enabled,
            hide_upstream_quota_from_api_keys=row.hide_upstream_quota_from_api_keys,
            limit_warmup_enabled=row.limit_warmup_enabled,
            limit_warmup_windows=row.limit_warmup_windows,
            limit_warmup_model=row.limit_warmup_model,
            limit_warmup_prompt=row.limit_warmup_prompt,
            limit_warmup_cooldown_seconds=row.limit_warmup_cooldown_seconds,
            limit_warmup_exhausted_threshold_percent=row.limit_warmup_exhausted_threshold_percent,
            limit_warmup_idle_threshold_percent=row.limit_warmup_idle_threshold_percent,
            limit_warmup_min_available_percent=row.limit_warmup_min_available_percent,
            weekly_pace_working_days=row.weekly_pace_working_days,
            weekly_pace_smoothing_minutes=row.weekly_pace_smoothing_minutes,
            guest_access_enabled=row.guest_access_enabled,
            guest_password_configured=row.guest_password_hash is not None,
            limit_warmup_staggered_idle_enabled=row.limit_warmup_staggered_idle_enabled,
            request_log_retention_days=_effective_request_log_retention(row.request_log_retention_days),
            usage_history_retention_days=_effective_usage_history_retention(row.usage_history_retention_days),
            request_log_retention_override_days=row.request_log_retention_days,
            usage_history_retention_override_days=row.usage_history_retention_days,
            version=row.version,
        )
=======
    async def totp_enrollment(self, actor_user_id: str | None) -> TotpEnrollmentSummary:
        users = await self._repository.list_active_password_users()
        without_totp = [user for user in users if user.totp_secret_encrypted is None]
        return TotpEnrollmentSummary(
            actor_configured=any(user.id == actor_user_id and user.totp_secret_encrypted is not None for user in users),
            users_without_totp=len(without_totp),
            admins_without_totp=sum(1 for user in without_totp if is_admin_level(resolve_role_grants(user.role))),
        )
>>>>>>> 72630bbfe

    async def get_settings(self, *, actor_user_id: str | None = None) -> DashboardSettingsData:
        row = await self._repository.get_or_create()
        return _settings_data(row, await self.totp_enrollment(actor_user_id))

    async def update_settings(
        self,
        payload: DashboardSettingsUpdateData,
        *,
        actor_user_id: str | None = None,
        expected_version: int | None = None,
    ) -> DashboardSettingsData:
        # The accounts lock is taken before this service reads anything and is
        # held until ``update`` commits, so the count below and the policy write
        # are one step. Acquiring it first keeps both dialects taking the lock
        # at the same moment instead of relying on the in-transaction fallback
        # of ``acquire_write_intent``. It is only taken when the payload could
        # be a tightening, so an ordinary settings save is never queued behind
        # account mutations.
        if payload.local_login_policy not in (None, LocalLoginPolicy.ENABLED.value):
            await self._repository.acquire_account_write_intent()
        current = await self._repository.get_or_create()
<<<<<<< 22625a07e
        omniroute_is_enabled = omniroute_enabled()
        if not omniroute_is_enabled:
            stored_models = _parse_omniroute_sidecar_selected_models(current.omniroute_sidecar_selected_models_json)
            payload = replace(
                payload,
                omniroute_sidecar_enabled=current.omniroute_sidecar_enabled,
                omniroute_sidecar_base_url=current.omniroute_sidecar_base_url,
                omniroute_sidecar_api_key=None,
                omniroute_sidecar_clear_api_key=False,
                omniroute_sidecar_model_prefixes=_parse_omniroute_sidecar_model_prefixes(
                    current.omniroute_sidecar_prefixes_json
                ),
                omniroute_sidecar_full_models=stored_models,
                omniroute_sidecar_selected_models=stored_models,
                omniroute_sidecar_connect_timeout_seconds=current.omniroute_sidecar_connect_timeout_seconds,
                omniroute_sidecar_request_timeout_seconds=current.omniroute_sidecar_request_timeout_seconds,
                omniroute_sidecar_models_cache_ttl_seconds=current.omniroute_sidecar_models_cache_ttl_seconds,
                omniroute_sidecar_default_reasoning_effort=current.omniroute_sidecar_default_reasoning_effort,
            )
        if payload.totp_required_on_login and current.totp_secret_encrypted is None:
            raise ValueError("Configure TOTP before enabling login enforcement")
        effective_full_model_stars = _validate_unique_sidecar_routes(
            payload,
            stored_full_model_stars=parse_full_model_stars(current.sidecar_full_model_stars_json),
        )
        _validate_model_alias_pools(
            replace(payload, sidecar_full_model_stars=effective_full_model_stars),
            stored_aliases=_parse_model_aliases(current.model_aliases_json),
        )
        api_key_encrypted = current.claude_sidecar_api_key_encrypted
        if payload.claude_sidecar_clear_api_key:
            api_key_encrypted = None
        elif payload.claude_sidecar_api_key is not None:
            api_key_value = payload.claude_sidecar_api_key.strip()
            api_key_encrypted = self._encryptor.encrypt(api_key_value) if api_key_value else None
        management_key_encrypted = current.claude_sidecar_management_key_encrypted
        if payload.claude_sidecar_clear_management_key:
            management_key_encrypted = None
        elif payload.claude_sidecar_management_key is not None:
            management_key_value = payload.claude_sidecar_management_key.strip()
            management_key_encrypted = self._encryptor.encrypt(management_key_value) if management_key_value else None
        openrouter_api_key_encrypted = current.openrouter_sidecar_api_key_encrypted
        if payload.openrouter_sidecar_clear_api_key:
            openrouter_api_key_encrypted = None
        elif payload.openrouter_sidecar_api_key is not None:
            openrouter_api_key_value = payload.openrouter_sidecar_api_key.strip()
            openrouter_api_key_encrypted = (
                self._encryptor.encrypt(openrouter_api_key_value) if openrouter_api_key_value else None
            )
        orcarouter_api_key_encrypted = current.orcarouter_sidecar_api_key_encrypted
        if payload.orcarouter_sidecar_clear_api_key:
            orcarouter_api_key_encrypted = None
        elif payload.orcarouter_sidecar_api_key is not None:
            orcarouter_api_key_value = payload.orcarouter_sidecar_api_key.strip()
            orcarouter_api_key_encrypted = (
                self._encryptor.encrypt(orcarouter_api_key_value) if orcarouter_api_key_value else None
            )
        opencode_go_api_key_encrypted = current.opencode_go_sidecar_api_key_encrypted
        if payload.opencode_go_sidecar_clear_api_key:
            opencode_go_api_key_encrypted = None
        elif payload.opencode_go_sidecar_api_key is not None:
            opencode_go_api_key_value = payload.opencode_go_sidecar_api_key.strip()
            opencode_go_api_key_encrypted = (
                self._encryptor.encrypt(opencode_go_api_key_value) if opencode_go_api_key_value else None
            )
        omniroute_api_key_encrypted = current.omniroute_sidecar_api_key_encrypted
        if payload.omniroute_sidecar_clear_api_key:
            omniroute_api_key_encrypted = None
        elif payload.omniroute_sidecar_api_key is not None:
            omniroute_api_key_value = payload.omniroute_sidecar_api_key.strip()
            omniroute_api_key_encrypted = (
                self._encryptor.encrypt(omniroute_api_key_value) if omniroute_api_key_value else None
            )
        ollama_api_key_encrypted = current.ollama_sidecar_api_key_encrypted
        if payload.ollama_sidecar_clear_api_key:
            ollama_api_key_encrypted = None
        elif payload.ollama_sidecar_api_key is not None:
            ollama_api_key_value = payload.ollama_sidecar_api_key.strip()
            ollama_api_key_encrypted = self._encryptor.encrypt(ollama_api_key_value) if ollama_api_key_value else None
||||||| 84fde5a1e
        if payload.totp_required_on_login and current.totp_secret_encrypted is None:
            raise ValueError("Configure TOTP before enabling login enforcement")
=======
        # Requiring TOTP of others starts with the acting account: whoever turns
        # either requirement on must already hold a secret, or the next request
        # would park them at the enrolment gate they just created.
        enabling_global = payload.totp_required_on_login and not current.totp_required_on_login
        enabling_admin_role = payload.totp_required_for_admin_role and not current.totp_required_for_admin_role
        if enabling_global or enabling_admin_role:
            enrollment = await self.totp_enrollment(actor_user_id)
            if not enrollment.actor_configured:
                raise ValueError("Set up your own TOTP before requiring it at sign-in")
        # Closing the local password form is the most dangerous button in the
        # product: it is also the setting that locks the install out when the
        # identity provider is down. Only the tightening transition is gated
        # (re-saving the stored value, and relaxing back to ``enabled``, never
        # are), and the refusal names the account that would fix it. The count
        # and the settings write are one atomic step: the accounts lock above
        # is held until ``update`` commits, so no concurrent mutation can
        # remove the last qualifying account in between.
        tightening = (
            payload.local_login_policy is not None
            and payload.local_login_policy != current.local_login_policy
            and payload.local_login_policy != LocalLoginPolicy.ENABLED.value
        )
        if tightening and await self._repository.count_qualifying_break_glass() == 0:
            designated = await self._repository.list_break_glass_designations()
            username = designated[0].username if designated else None
            raise BreakGlassRequiresTotpError(
                (
                    f"Turn on two-factor for '{username}' before restricting local sign-in"
                    if username is not None
                    else "Designate an admin account with two-factor as the emergency account "
                    "before restricting local sign-in"
                ),
                username=username,
            )
>>>>>>> 72630bbfe
        row = await self._repository.update(
            expected_version=expected_version,
            sticky_threads_enabled=payload.sticky_threads_enabled,
            cliproxy_capacity_routing_enabled=payload.cliproxy_capacity_routing_enabled,
            upstream_stream_transport=payload.upstream_stream_transport,
            prohibit_fast_mode=payload.prohibit_fast_mode,
            http_downstream_transport_policy=payload.http_downstream_transport_policy,
            thread_cache_identity_mode=payload.thread_cache_identity_mode,
            clear_thread_cache_identity_mode=payload.clear_thread_cache_identity_mode,
            proxy_account_response_create_limit=payload.proxy_account_response_create_limit,
            clear_proxy_account_response_create_limit=payload.clear_proxy_account_response_create_limit,
            proxy_account_stream_limit=payload.proxy_account_stream_limit,
            clear_proxy_account_stream_limit=payload.clear_proxy_account_stream_limit,
            proxy_account_stream_recovery_reserve=payload.proxy_account_stream_recovery_reserve,
            clear_proxy_account_stream_recovery_reserve=payload.clear_proxy_account_stream_recovery_reserve,
            proxy_api_key_fair_share_congestion_threshold_pct=(
                payload.proxy_api_key_fair_share_congestion_threshold_pct
            ),
            clear_proxy_api_key_fair_share_congestion_threshold_pct=(
                payload.clear_proxy_api_key_fair_share_congestion_threshold_pct
            ),
            # C2-2 routing/overload
            proxy_overload_isolation_seconds=payload.proxy_overload_isolation_seconds,
            clear_proxy_overload_isolation_seconds=payload.clear_proxy_overload_isolation_seconds,
            proxy_account_error_rate_weighting_enabled=payload.proxy_account_error_rate_weighting_enabled,
            clear_proxy_account_error_rate_weighting_enabled=payload.clear_proxy_account_error_rate_weighting_enabled,
            proxy_account_inflight_penalty_pct=payload.proxy_account_inflight_penalty_pct,
            clear_proxy_account_inflight_penalty_pct=payload.clear_proxy_account_inflight_penalty_pct,
            proxy_account_lease_token_weight=payload.proxy_account_lease_token_weight,
            clear_proxy_account_lease_token_weight=payload.clear_proxy_account_lease_token_weight,
            proxy_account_lease_ttl_seconds=payload.proxy_account_lease_ttl_seconds,
            clear_proxy_account_lease_ttl_seconds=payload.clear_proxy_account_lease_ttl_seconds,
            # end C2-2 routing/overload
            upstream_proxy_routing_enabled=payload.upstream_proxy_routing_enabled,
            upstream_proxy_default_pool_id=payload.upstream_proxy_default_pool_id,
            prefer_earlier_reset_accounts=payload.prefer_earlier_reset_accounts,
            prefer_earlier_reset_window=payload.prefer_earlier_reset_window,
            show_reset_credit_badges=payload.show_reset_credit_badges,
            auto_redeem_reset_credits_before_expiry=payload.auto_redeem_reset_credits_before_expiry,
            show_reset_credit_expiry_badge=payload.show_reset_credit_expiry_badge,
            routing_strategy=payload.routing_strategy,
            relative_availability_power=payload.relative_availability_power,
            relative_availability_top_k=payload.relative_availability_top_k,
            single_account_id=payload.single_account_id,
            openai_cache_affinity_max_age_seconds=payload.openai_cache_affinity_max_age_seconds,
            dashboard_session_ttl_seconds=payload.dashboard_session_ttl_seconds,
            http_responses_session_bridge_prompt_cache_idle_ttl_seconds=(
                payload.http_responses_session_bridge_prompt_cache_idle_ttl_seconds
            ),
            http_responses_session_bridge_gateway_safe_mode=payload.http_responses_session_bridge_gateway_safe_mode,
            sticky_reallocation_budget_threshold_pct=payload.sticky_reallocation_budget_threshold_pct,
            sticky_reallocation_primary_budget_threshold_pct=payload.sticky_reallocation_primary_budget_threshold_pct,
            sticky_reallocation_secondary_budget_threshold_pct=payload.sticky_reallocation_secondary_budget_threshold_pct,
            additional_quota_routing_policies_json=_dump_additional_quota_routing_policies(
                payload.additional_quota_routing_policies
            ),
            model_aliases_json=_dump_model_aliases(payload.model_aliases),
            custom_alias_catalog_json=_dump_custom_alias_catalog(payload.custom_alias_catalog),
            warmup_model=payload.warmup_model,
            import_without_overwrite=payload.import_without_overwrite,
            totp_required_on_login=payload.totp_required_on_login,
            totp_required_for_admin_role=payload.totp_required_for_admin_role,
            local_login_policy=payload.local_login_policy,
            api_key_auth_enabled=payload.api_key_auth_enabled,
            hide_upstream_quota_from_api_keys=payload.hide_upstream_quota_from_api_keys,
            limit_warmup_enabled=payload.limit_warmup_enabled,
            limit_warmup_windows=payload.limit_warmup_windows,
            limit_warmup_model=payload.limit_warmup_model,
            limit_warmup_prompt=payload.limit_warmup_prompt,
            limit_warmup_cooldown_seconds=payload.limit_warmup_cooldown_seconds,
            limit_warmup_exhausted_threshold_percent=payload.limit_warmup_exhausted_threshold_percent,
            limit_warmup_idle_threshold_percent=payload.limit_warmup_idle_threshold_percent,
            limit_warmup_min_available_percent=payload.limit_warmup_min_available_percent,
            weekly_pace_working_days=payload.weekly_pace_working_days,
            weekly_pace_smoothing_minutes=payload.weekly_pace_smoothing_minutes,
            claude_sidecar_enabled=payload.claude_sidecar_enabled,
            claude_sidecar_base_url=payload.claude_sidecar_base_url,
            claude_sidecar_api_key_encrypted=api_key_encrypted,
            claude_sidecar_model_prefixes_json=_dump_claude_sidecar_model_prefixes(
                payload.claude_sidecar_model_prefixes
            ),
            claude_sidecar_full_models_json=_dump_sidecar_full_models(payload.claude_sidecar_full_models),
            claude_sidecar_connect_timeout_seconds=payload.claude_sidecar_connect_timeout_seconds,
            claude_sidecar_request_timeout_seconds=payload.claude_sidecar_request_timeout_seconds,
            claude_sidecar_models_cache_ttl_seconds=payload.claude_sidecar_models_cache_ttl_seconds,
            claude_sidecar_management_key_encrypted=management_key_encrypted,
            claude_sidecar_quota_poll_interval_seconds=payload.claude_sidecar_quota_poll_interval_seconds,
            claude_sidecar_auth_plans_json=_dump_claude_sidecar_auth_plans(payload.claude_sidecar_auth_plans),
            claude_sidecar_usage_poll_interval_seconds=payload.claude_sidecar_usage_poll_interval_seconds,
            claude_sidecar_usage_queue_batch_size=payload.claude_sidecar_usage_queue_batch_size,
            claude_sidecar_usage_collection_enabled=payload.claude_sidecar_usage_collection_enabled,
            claude_sidecar_default_reasoning_effort=payload.claude_sidecar_default_reasoning_effort,
            openrouter_sidecar_enabled=payload.openrouter_sidecar_enabled,
            openrouter_sidecar_base_url=payload.openrouter_sidecar_base_url,
            openrouter_sidecar_api_key_encrypted=openrouter_api_key_encrypted,
            openrouter_sidecar_model_prefixes_json=_dump_openrouter_sidecar_model_prefixes(
                payload.openrouter_sidecar_model_prefixes
            ),
            openrouter_sidecar_full_models_json=_dump_sidecar_full_models(payload.openrouter_sidecar_full_models),
            openrouter_sidecar_connect_timeout_seconds=payload.openrouter_sidecar_connect_timeout_seconds,
            openrouter_sidecar_request_timeout_seconds=payload.openrouter_sidecar_request_timeout_seconds,
            openrouter_sidecar_models_cache_ttl_seconds=payload.openrouter_sidecar_models_cache_ttl_seconds,
            openrouter_sidecar_default_reasoning_effort=payload.openrouter_sidecar_default_reasoning_effort,
            openai_compat_endpoints_json=dump_openai_compat_endpoints(
                merge_openai_compat_endpoints(
                    current.openai_compat_endpoints_json,
                    payload.openai_compat_endpoints,
                    self._encryptor,
                )
            ),
            orcarouter_sidecar_enabled=payload.orcarouter_sidecar_enabled,
            orcarouter_sidecar_base_url=payload.orcarouter_sidecar_base_url,
            orcarouter_sidecar_api_key_encrypted=orcarouter_api_key_encrypted,
            orcarouter_sidecar_model_prefixes_json=_dump_orcarouter_sidecar_model_prefixes(
                payload.orcarouter_sidecar_model_prefixes
            ),
            orcarouter_sidecar_full_models_json=_dump_sidecar_full_models(payload.orcarouter_sidecar_full_models),
            orcarouter_sidecar_connect_timeout_seconds=payload.orcarouter_sidecar_connect_timeout_seconds,
            orcarouter_sidecar_request_timeout_seconds=payload.orcarouter_sidecar_request_timeout_seconds,
            orcarouter_sidecar_models_cache_ttl_seconds=payload.orcarouter_sidecar_models_cache_ttl_seconds,
            orcarouter_sidecar_default_reasoning_effort=payload.orcarouter_sidecar_default_reasoning_effort,
            opencode_go_sidecar_enabled=payload.opencode_go_sidecar_enabled,
            opencode_go_sidecar_base_url=payload.opencode_go_sidecar_base_url,
            opencode_go_sidecar_api_key_encrypted=opencode_go_api_key_encrypted,
            opencode_go_sidecar_model_prefixes_json=_dump_sidecar_model_prefixes(
                payload.opencode_go_sidecar_model_prefixes
            ),
            opencode_go_sidecar_full_models_json=_dump_sidecar_full_models(payload.opencode_go_sidecar_full_models),
            opencode_go_sidecar_connect_timeout_seconds=payload.opencode_go_sidecar_connect_timeout_seconds,
            opencode_go_sidecar_request_timeout_seconds=payload.opencode_go_sidecar_request_timeout_seconds,
            opencode_go_sidecar_models_cache_ttl_seconds=payload.opencode_go_sidecar_models_cache_ttl_seconds,
            omniroute_sidecar_enabled=payload.omniroute_sidecar_enabled,
            omniroute_sidecar_base_url=payload.omniroute_sidecar_base_url,
            omniroute_sidecar_api_key_encrypted=omniroute_api_key_encrypted,
            omniroute_sidecar_selected_models_json=(
                _dump_omniroute_sidecar_selected_models(payload.omniroute_sidecar_full_models)
                if omniroute_is_enabled
                else current.omniroute_sidecar_selected_models_json
            ),
            omniroute_sidecar_prefixes_json=(
                _dump_omniroute_sidecar_model_prefixes(payload.omniroute_sidecar_model_prefixes)
                if omniroute_is_enabled
                else current.omniroute_sidecar_prefixes_json
            ),
            omniroute_sidecar_connect_timeout_seconds=payload.omniroute_sidecar_connect_timeout_seconds,
            omniroute_sidecar_request_timeout_seconds=payload.omniroute_sidecar_request_timeout_seconds,
            omniroute_sidecar_models_cache_ttl_seconds=payload.omniroute_sidecar_models_cache_ttl_seconds,
            omniroute_sidecar_default_reasoning_effort=payload.omniroute_sidecar_default_reasoning_effort,
            ollama_sidecar_enabled=payload.ollama_sidecar_enabled,
            ollama_sidecar_base_url=payload.ollama_sidecar_base_url,
            ollama_sidecar_api_key_encrypted=ollama_api_key_encrypted,
            ollama_sidecar_model_prefixes_json=_dump_ollama_sidecar_model_prefixes(
                payload.ollama_sidecar_model_prefixes
            ),
            ollama_sidecar_full_models_json=_dump_sidecar_full_models(payload.ollama_sidecar_full_models),
            ollama_sidecar_connect_timeout_seconds=payload.ollama_sidecar_connect_timeout_seconds,
            ollama_sidecar_request_timeout_seconds=payload.ollama_sidecar_request_timeout_seconds,
            ollama_sidecar_models_cache_ttl_seconds=payload.ollama_sidecar_models_cache_ttl_seconds,
            ollama_sidecar_default_reasoning_effort=payload.ollama_sidecar_default_reasoning_effort,
            guest_access_enabled=payload.guest_access_enabled,
            limit_warmup_staggered_idle_enabled=payload.limit_warmup_staggered_idle_enabled,
            request_log_retention_days=payload.request_log_retention_override_days,
            usage_history_retention_days=payload.usage_history_retention_override_days,
            hourly_rollup_retention_days=payload.hourly_rollup_retention_override_days,
            clear_request_log_retention=payload.clear_request_log_retention_override,
            clear_usage_history_retention=payload.clear_usage_history_retention_override,
<<<<<<< 22625a07e
            clear_hourly_rollup_retention=payload.clear_hourly_rollup_retention_override,
            sidecar_full_model_stars_json=_dump_full_model_stars(effective_full_model_stars),
            dashboard_layout_json=(
                dump_dashboard_layout(payload.dashboard_layout) if payload.dashboard_layout is not None else None
            ),
||||||| 84fde5a1e
=======
            # C2-3 resilience toggles
            soft_drain_enabled=payload.soft_drain_enabled,
            clear_soft_drain_enabled=payload.clear_soft_drain_enabled,
            # M5 conversation archive
            conversation_archive_enabled=payload.conversation_archive_enabled,
            clear_conversation_archive_enabled=payload.clear_conversation_archive_enabled,
            # end M5 conversation archive
            # R2 spool retention
            http_responses_session_bridge_operation_spool_retention_seconds=(
                payload.http_responses_session_bridge_operation_spool_retention_seconds
            ),
            clear_http_responses_session_bridge_operation_spool_retention_seconds=(
                payload.clear_http_responses_session_bridge_operation_spool_retention_seconds
            ),
            # end R2 spool retention
            deterministic_failover_enabled=payload.deterministic_failover_enabled,
            clear_deterministic_failover_enabled=payload.clear_deterministic_failover_enabled,
            circuit_breaker_enabled=payload.circuit_breaker_enabled,
            clear_circuit_breaker_enabled=payload.clear_circuit_breaker_enabled,
            # M2 background jobs
            auth_guardian_enabled=payload.auth_guardian_enabled,
            clear_auth_guardian_enabled=payload.clear_auth_guardian_enabled,
            automations_scheduler_enabled=payload.automations_scheduler_enabled,
            clear_automations_scheduler_enabled=payload.clear_automations_scheduler_enabled,
            rate_limit_reset_credits_refresh_enabled=payload.rate_limit_reset_credits_refresh_enabled,
            clear_rate_limit_reset_credits_refresh_enabled=payload.clear_rate_limit_reset_credits_refresh_enabled,
            # end M2 background jobs
            # C2-1 timeouts
            upstream_connect_timeout_seconds=payload.upstream_connect_timeout_seconds,
            clear_upstream_connect_timeout_seconds=payload.clear_upstream_connect_timeout_seconds,
            proxy_request_budget_seconds=payload.proxy_request_budget_seconds,
            clear_proxy_request_budget_seconds=payload.clear_proxy_request_budget_seconds,
            compact_request_budget_seconds=payload.compact_request_budget_seconds,
            clear_compact_request_budget_seconds=payload.clear_compact_request_budget_seconds,
            transcription_request_budget_seconds=payload.transcription_request_budget_seconds,
            clear_transcription_request_budget_seconds=payload.clear_transcription_request_budget_seconds,
            stream_idle_timeout_seconds=payload.stream_idle_timeout_seconds,
            clear_stream_idle_timeout_seconds=payload.clear_stream_idle_timeout_seconds,
            proxy_downstream_websocket_idle_timeout_seconds=payload.proxy_downstream_websocket_idle_timeout_seconds,
            clear_proxy_downstream_websocket_idle_timeout_seconds=(
                payload.clear_proxy_downstream_websocket_idle_timeout_seconds
            ),
            sse_keepalive_interval_seconds=payload.sse_keepalive_interval_seconds,
            clear_sse_keepalive_interval_seconds=payload.clear_sse_keepalive_interval_seconds,
            # end C2-1 timeouts
            # M3 codex prewarm
            http_responses_session_bridge_codex_prewarm_enabled=(
                payload.http_responses_session_bridge_codex_prewarm_enabled
            ),
            clear_http_responses_session_bridge_codex_prewarm_enabled=(
                payload.clear_http_responses_session_bridge_codex_prewarm_enabled
            ),
            # end M3 codex prewarm
            # M1 stream/bridge budgets
            http_responses_stream_request_budget_seconds=payload.http_responses_stream_request_budget_seconds,
            clear_http_responses_stream_request_budget_seconds=(
                payload.clear_http_responses_stream_request_budget_seconds
            ),
            http_responses_session_bridge_request_budget_seconds=(
                payload.http_responses_session_bridge_request_budget_seconds
            ),
            clear_http_responses_session_bridge_request_budget_seconds=(
                payload.clear_http_responses_session_bridge_request_budget_seconds
            ),
            # end M1 stream/bridge budgets
>>>>>>> 72630bbfe
        )
<<<<<<< 22625a07e
        return self._to_data(row)

    def decrypt_claude_sidecar_api_key(self, encrypted: bytes | None) -> str | None:
        if encrypted is None:
            return None
        return self._encryptor.decrypt(encrypted)

    def decrypt_claude_sidecar_management_key(self, encrypted: bytes | None) -> str | None:
        if encrypted is None:
            return None
        return self._encryptor.decrypt(encrypted)

    def _to_data(self, row) -> DashboardSettingsData:
        return DashboardSettingsData(
            sticky_threads_enabled=row.sticky_threads_enabled,
            upstream_stream_transport=row.upstream_stream_transport,
            prohibit_fast_mode=row.prohibit_fast_mode,
            http_downstream_transport_policy=row.http_downstream_transport_policy,
            proxy_account_response_create_limit=_effective_response_create_limit(
                row.proxy_account_response_create_limit
            ),
            proxy_account_stream_limit=_effective_stream_limit(row.proxy_account_stream_limit),
            proxy_account_stream_recovery_reserve=_effective_stream_recovery_reserve(
                row.proxy_account_stream_recovery_reserve
            ),
            proxy_api_key_fair_share_congestion_threshold_pct=_effective_api_key_fair_share_threshold_pct(
                row.proxy_api_key_fair_share_congestion_threshold_pct
            ),
            upstream_proxy_routing_enabled=row.upstream_proxy_routing_enabled,
            upstream_proxy_default_pool_id=row.upstream_proxy_default_pool_id,
            prefer_earlier_reset_accounts=row.prefer_earlier_reset_accounts,
            prefer_earlier_reset_window=row.prefer_earlier_reset_window,
            show_reset_credit_badges=row.show_reset_credit_badges,
            auto_redeem_reset_credits_before_expiry=row.auto_redeem_reset_credits_before_expiry,
            show_reset_credit_expiry_badge=row.show_reset_credit_expiry_badge,
            routing_strategy=row.routing_strategy,
            relative_availability_power=row.relative_availability_power,
            relative_availability_top_k=row.relative_availability_top_k,
            single_account_id=row.single_account_id,
            openai_cache_affinity_max_age_seconds=row.openai_cache_affinity_max_age_seconds,
            dashboard_session_ttl_seconds=row.dashboard_session_ttl_seconds,
            http_responses_session_bridge_prompt_cache_idle_ttl_seconds=(
                row.http_responses_session_bridge_prompt_cache_idle_ttl_seconds
            ),
            http_responses_session_bridge_gateway_safe_mode=row.http_responses_session_bridge_gateway_safe_mode,
            sticky_reallocation_budget_threshold_pct=row.sticky_reallocation_budget_threshold_pct,
            sticky_reallocation_primary_budget_threshold_pct=row.sticky_reallocation_primary_budget_threshold_pct,
            sticky_reallocation_secondary_budget_threshold_pct=row.sticky_reallocation_secondary_budget_threshold_pct,
            additional_quota_routing_policies=_parse_additional_quota_routing_policies(
                row.additional_quota_routing_policies_json
            ),
            model_aliases=_parse_model_aliases(row.model_aliases_json),
            custom_alias_catalog=_parse_custom_alias_catalog(row.custom_alias_catalog_json),
            warmup_model=row.warmup_model,
            import_without_overwrite=row.import_without_overwrite,
            totp_required_on_login=row.totp_required_on_login,
            totp_configured=row.totp_secret_encrypted is not None,
            api_key_auth_enabled=row.api_key_auth_enabled,
            hide_upstream_quota_from_api_keys=row.hide_upstream_quota_from_api_keys,
            limit_warmup_enabled=row.limit_warmup_enabled,
            limit_warmup_windows=row.limit_warmup_windows,
            limit_warmup_model=row.limit_warmup_model,
            limit_warmup_prompt=row.limit_warmup_prompt,
            limit_warmup_cooldown_seconds=row.limit_warmup_cooldown_seconds,
            limit_warmup_exhausted_threshold_percent=row.limit_warmup_exhausted_threshold_percent,
            limit_warmup_idle_threshold_percent=row.limit_warmup_idle_threshold_percent,
            limit_warmup_min_available_percent=row.limit_warmup_min_available_percent,
            weekly_pace_working_days=row.weekly_pace_working_days,
            weekly_pace_smoothing_minutes=row.weekly_pace_smoothing_minutes,
            claude_sidecar_enabled=row.claude_sidecar_enabled,
            claude_sidecar_base_url=row.claude_sidecar_base_url,
            claude_sidecar_api_key_configured=row.claude_sidecar_api_key_encrypted is not None,
            claude_sidecar_model_prefixes=_parse_claude_sidecar_model_prefixes(row.claude_sidecar_model_prefixes_json),
            claude_sidecar_full_models=_parse_sidecar_full_models(row.claude_sidecar_full_models_json),
            claude_sidecar_connect_timeout_seconds=row.claude_sidecar_connect_timeout_seconds,
            claude_sidecar_request_timeout_seconds=row.claude_sidecar_request_timeout_seconds,
            claude_sidecar_models_cache_ttl_seconds=row.claude_sidecar_models_cache_ttl_seconds,
            claude_sidecar_last_health_status=row.claude_sidecar_last_health_status,
            claude_sidecar_last_health_message=row.claude_sidecar_last_health_message,
            claude_sidecar_last_checked_at=row.claude_sidecar_last_checked_at,
            claude_sidecar_last_model_count=row.claude_sidecar_last_model_count,
            claude_sidecar_management_key_configured=row.claude_sidecar_management_key_encrypted is not None,
            claude_sidecar_quota_poll_interval_seconds=row.claude_sidecar_quota_poll_interval_seconds,
            claude_sidecar_auth_plans=_parse_claude_sidecar_auth_plans(row.claude_sidecar_auth_plans_json),
            claude_sidecar_usage_poll_interval_seconds=row.claude_sidecar_usage_poll_interval_seconds,
            claude_sidecar_usage_queue_batch_size=row.claude_sidecar_usage_queue_batch_size,
            claude_sidecar_usage_collection_enabled=row.claude_sidecar_usage_collection_enabled,
            claude_sidecar_default_reasoning_effort=row.claude_sidecar_default_reasoning_effort,
            openrouter_sidecar_enabled=row.openrouter_sidecar_enabled,
            openrouter_sidecar_base_url=row.openrouter_sidecar_base_url,
            openrouter_sidecar_api_key_configured=row.openrouter_sidecar_api_key_encrypted is not None,
            openrouter_sidecar_model_prefixes=_parse_openrouter_sidecar_model_prefixes(
                row.openrouter_sidecar_model_prefixes_json
            ),
            openrouter_sidecar_full_models=_parse_sidecar_full_models(row.openrouter_sidecar_full_models_json),
            openrouter_sidecar_connect_timeout_seconds=row.openrouter_sidecar_connect_timeout_seconds,
            openrouter_sidecar_request_timeout_seconds=row.openrouter_sidecar_request_timeout_seconds,
            openrouter_sidecar_models_cache_ttl_seconds=row.openrouter_sidecar_models_cache_ttl_seconds,
            openrouter_sidecar_last_health_status=row.openrouter_sidecar_last_health_status,
            openrouter_sidecar_last_health_message=row.openrouter_sidecar_last_health_message,
            openrouter_sidecar_last_checked_at=row.openrouter_sidecar_last_checked_at,
            openrouter_sidecar_last_model_count=row.openrouter_sidecar_last_model_count,
            openrouter_sidecar_default_reasoning_effort=row.openrouter_sidecar_default_reasoning_effort,
            openai_compat_endpoints=list(parse_openai_compat_endpoints(row.openai_compat_endpoints_json)),
            orcarouter_sidecar_enabled=row.orcarouter_sidecar_enabled,
            orcarouter_sidecar_base_url=row.orcarouter_sidecar_base_url,
            orcarouter_sidecar_api_key_configured=row.orcarouter_sidecar_api_key_encrypted is not None,
            orcarouter_sidecar_model_prefixes=_parse_orcarouter_sidecar_model_prefixes(
                row.orcarouter_sidecar_model_prefixes_json
            ),
            orcarouter_sidecar_full_models=_parse_sidecar_full_models(row.orcarouter_sidecar_full_models_json),
            orcarouter_sidecar_connect_timeout_seconds=row.orcarouter_sidecar_connect_timeout_seconds,
            orcarouter_sidecar_request_timeout_seconds=row.orcarouter_sidecar_request_timeout_seconds,
            orcarouter_sidecar_models_cache_ttl_seconds=row.orcarouter_sidecar_models_cache_ttl_seconds,
            orcarouter_sidecar_last_health_status=row.orcarouter_sidecar_last_health_status,
            orcarouter_sidecar_last_health_message=row.orcarouter_sidecar_last_health_message,
            orcarouter_sidecar_last_checked_at=row.orcarouter_sidecar_last_checked_at,
            orcarouter_sidecar_last_model_count=row.orcarouter_sidecar_last_model_count,
            orcarouter_sidecar_default_reasoning_effort=row.orcarouter_sidecar_default_reasoning_effort,
            opencode_go_sidecar_enabled=row.opencode_go_sidecar_enabled,
            opencode_go_sidecar_base_url=row.opencode_go_sidecar_base_url,
            opencode_go_sidecar_api_key_configured=row.opencode_go_sidecar_api_key_encrypted is not None,
            opencode_go_sidecar_model_prefixes=_parse_sidecar_model_prefixes(
                row.opencode_go_sidecar_model_prefixes_json
            ),
            opencode_go_sidecar_full_models=_parse_sidecar_full_models(row.opencode_go_sidecar_full_models_json),
            opencode_go_sidecar_connect_timeout_seconds=row.opencode_go_sidecar_connect_timeout_seconds,
            opencode_go_sidecar_request_timeout_seconds=row.opencode_go_sidecar_request_timeout_seconds,
            opencode_go_sidecar_models_cache_ttl_seconds=row.opencode_go_sidecar_models_cache_ttl_seconds,
            opencode_go_sidecar_last_health_status=row.opencode_go_sidecar_last_health_status,
            opencode_go_sidecar_last_health_message=row.opencode_go_sidecar_last_health_message,
            opencode_go_sidecar_last_checked_at=row.opencode_go_sidecar_last_checked_at,
            opencode_go_sidecar_last_model_count=row.opencode_go_sidecar_last_model_count,
            omniroute_sidecar_enabled=row.omniroute_sidecar_enabled,
            omniroute_sidecar_base_url=row.omniroute_sidecar_base_url,
            omniroute_sidecar_api_key_configured=row.omniroute_sidecar_api_key_encrypted is not None,
            omniroute_sidecar_model_prefixes=_parse_omniroute_sidecar_model_prefixes(
                row.omniroute_sidecar_prefixes_json
            ),
            omniroute_sidecar_full_models=_parse_omniroute_sidecar_selected_models(
                row.omniroute_sidecar_selected_models_json
            ),
            omniroute_sidecar_selected_models=_parse_omniroute_sidecar_selected_models(
                row.omniroute_sidecar_selected_models_json
            ),
            omniroute_sidecar_connect_timeout_seconds=row.omniroute_sidecar_connect_timeout_seconds,
            omniroute_sidecar_request_timeout_seconds=row.omniroute_sidecar_request_timeout_seconds,
            omniroute_sidecar_models_cache_ttl_seconds=row.omniroute_sidecar_models_cache_ttl_seconds,
            omniroute_sidecar_last_health_status=row.omniroute_sidecar_last_health_status,
            omniroute_sidecar_last_health_message=row.omniroute_sidecar_last_health_message,
            omniroute_sidecar_last_checked_at=row.omniroute_sidecar_last_checked_at,
            omniroute_sidecar_last_model_count=row.omniroute_sidecar_last_model_count,
            omniroute_sidecar_default_reasoning_effort=row.omniroute_sidecar_default_reasoning_effort,
            ollama_sidecar_enabled=row.ollama_sidecar_enabled,
            ollama_sidecar_base_url=row.ollama_sidecar_base_url,
            ollama_sidecar_api_key_configured=row.ollama_sidecar_api_key_encrypted is not None,
            ollama_sidecar_model_prefixes=_parse_ollama_sidecar_model_prefixes(row.ollama_sidecar_model_prefixes_json),
            ollama_sidecar_full_models=_parse_sidecar_full_models(row.ollama_sidecar_full_models_json),
            ollama_sidecar_connect_timeout_seconds=row.ollama_sidecar_connect_timeout_seconds,
            ollama_sidecar_request_timeout_seconds=row.ollama_sidecar_request_timeout_seconds,
            ollama_sidecar_models_cache_ttl_seconds=row.ollama_sidecar_models_cache_ttl_seconds,
            ollama_sidecar_last_health_status=row.ollama_sidecar_last_health_status,
            ollama_sidecar_last_health_message=row.ollama_sidecar_last_health_message,
            ollama_sidecar_last_checked_at=row.ollama_sidecar_last_checked_at,
            ollama_sidecar_last_model_count=row.ollama_sidecar_last_model_count,
            ollama_sidecar_default_reasoning_effort=row.ollama_sidecar_default_reasoning_effort,
            sidecar_full_model_stars=parse_full_model_stars(row.sidecar_full_model_stars_json),
            guest_access_enabled=row.guest_access_enabled,
            guest_password_configured=row.guest_password_hash is not None,
            limit_warmup_staggered_idle_enabled=row.limit_warmup_staggered_idle_enabled,
            request_log_retention_days=_effective_request_log_retention(row.request_log_retention_days),
            usage_history_retention_days=_effective_usage_history_retention(row.usage_history_retention_days),
            hourly_rollup_retention_days=_effective_hourly_rollup_retention(row.hourly_rollup_retention_days),
            request_log_retention_override_days=row.request_log_retention_days,
            usage_history_retention_override_days=row.usage_history_retention_days,
            hourly_rollup_retention_override_days=row.hourly_rollup_retention_days,
            version=row.version,
            cliproxy_capacity_routing_enabled=row.cliproxy_capacity_routing_enabled,
            dashboard_layout=parse_dashboard_layout(row.dashboard_layout_json),
        )
||||||| 84fde5a1e
        return DashboardSettingsData(
            sticky_threads_enabled=row.sticky_threads_enabled,
            upstream_stream_transport=row.upstream_stream_transport,
            prohibit_fast_mode=row.prohibit_fast_mode,
            http_downstream_transport_policy=row.http_downstream_transport_policy,
            proxy_account_response_create_limit=_effective_response_create_limit(
                row.proxy_account_response_create_limit
            ),
            proxy_account_stream_limit=_effective_stream_limit(row.proxy_account_stream_limit),
            proxy_account_stream_recovery_reserve=_effective_stream_recovery_reserve(
                row.proxy_account_stream_recovery_reserve
            ),
            proxy_api_key_fair_share_congestion_threshold_pct=_effective_api_key_fair_share_threshold_pct(
                row.proxy_api_key_fair_share_congestion_threshold_pct
            ),
            upstream_proxy_routing_enabled=row.upstream_proxy_routing_enabled,
            upstream_proxy_default_pool_id=row.upstream_proxy_default_pool_id,
            prefer_earlier_reset_accounts=row.prefer_earlier_reset_accounts,
            prefer_earlier_reset_window=row.prefer_earlier_reset_window,
            show_reset_credit_badges=row.show_reset_credit_badges,
            auto_redeem_reset_credits_before_expiry=row.auto_redeem_reset_credits_before_expiry,
            show_reset_credit_expiry_badge=row.show_reset_credit_expiry_badge,
            routing_strategy=row.routing_strategy,
            relative_availability_power=row.relative_availability_power,
            relative_availability_top_k=row.relative_availability_top_k,
            single_account_id=row.single_account_id,
            openai_cache_affinity_max_age_seconds=row.openai_cache_affinity_max_age_seconds,
            dashboard_session_ttl_seconds=row.dashboard_session_ttl_seconds,
            http_responses_session_bridge_prompt_cache_idle_ttl_seconds=(
                row.http_responses_session_bridge_prompt_cache_idle_ttl_seconds
            ),
            http_responses_session_bridge_gateway_safe_mode=row.http_responses_session_bridge_gateway_safe_mode,
            sticky_reallocation_budget_threshold_pct=row.sticky_reallocation_budget_threshold_pct,
            sticky_reallocation_primary_budget_threshold_pct=row.sticky_reallocation_primary_budget_threshold_pct,
            sticky_reallocation_secondary_budget_threshold_pct=row.sticky_reallocation_secondary_budget_threshold_pct,
            additional_quota_routing_policies=_parse_additional_quota_routing_policies(
                row.additional_quota_routing_policies_json
            ),
            warmup_model=row.warmup_model,
            import_without_overwrite=row.import_without_overwrite,
            totp_required_on_login=row.totp_required_on_login,
            totp_configured=row.totp_secret_encrypted is not None,
            api_key_auth_enabled=row.api_key_auth_enabled,
            hide_upstream_quota_from_api_keys=row.hide_upstream_quota_from_api_keys,
            limit_warmup_enabled=row.limit_warmup_enabled,
            limit_warmup_windows=row.limit_warmup_windows,
            limit_warmup_model=row.limit_warmup_model,
            limit_warmup_prompt=row.limit_warmup_prompt,
            limit_warmup_cooldown_seconds=row.limit_warmup_cooldown_seconds,
            limit_warmup_exhausted_threshold_percent=row.limit_warmup_exhausted_threshold_percent,
            limit_warmup_idle_threshold_percent=row.limit_warmup_idle_threshold_percent,
            limit_warmup_min_available_percent=row.limit_warmup_min_available_percent,
            weekly_pace_working_days=row.weekly_pace_working_days,
            weekly_pace_smoothing_minutes=row.weekly_pace_smoothing_minutes,
            guest_access_enabled=row.guest_access_enabled,
            guest_password_configured=row.guest_password_hash is not None,
            limit_warmup_staggered_idle_enabled=row.limit_warmup_staggered_idle_enabled,
            request_log_retention_days=_effective_request_log_retention(row.request_log_retention_days),
            usage_history_retention_days=_effective_usage_history_retention(row.usage_history_retention_days),
            request_log_retention_override_days=row.request_log_retention_days,
            usage_history_retention_override_days=row.usage_history_retention_days,
            version=row.version,
        )
=======
        return _settings_data(row, await self.totp_enrollment(actor_user_id))
        return _settings_data(row, await self.totp_enrollment(actor_user_id))


# Retention has no environment fallback: NULL = never set from the dashboard =
# disabled; 0 = explicitly disabled.
_RETENTION_DISABLED_DAYS = 0
>>>>>>> 72630bbfe


_ROUTING_POLICIES = frozenset({"inherit", "normal", "burn_first", "preserve"})
_DEFAULT_CLAUDE_SIDECAR_PREFIXES = [
    SidecarPrefix(prefix="claude", strip=False),
    SidecarPrefix(prefix="cp-", strip=True),
    SidecarPrefix(prefix="cp_", strip=True),
]

# Inheritable settings with an environment fallback: the ``dashboard_settings``
# column, the ``Settings`` field and the provenance key share one name.
_ENVIRONMENT_INHERITABLE_SETTINGS = (
    # Thread cache identity mode (str): NULL inherits the env value, then "shared".
    "thread_cache_identity_mode",
    "proxy_account_response_create_limit",
    "proxy_account_stream_limit",
    "proxy_account_stream_recovery_reserve",
    "proxy_api_key_fair_share_congestion_threshold_pct",
    *DASHBOARD_TIMEOUT_SETTINGS,  # C2-1 timeouts
    # C2-2 routing/overload
    "proxy_overload_isolation_seconds",
    "proxy_account_error_rate_weighting_enabled",
    "proxy_account_inflight_penalty_pct",
    "proxy_account_lease_token_weight",
    "proxy_account_lease_ttl_seconds",
    # end C2-2 routing/overload
    # M3 codex prewarm: bool; a NULL column inherits the deprecated env alias.
    "http_responses_session_bridge_codex_prewarm_enabled",
    # end M3 codex prewarm
    CONVERSATION_ARCHIVE_SETTING,  # M5 conversation archive (bool, env alias)
    # R2 spool retention: float; a NULL column inherits the deprecated env alias.
    OPERATION_SPOOL_RETENTION_SETTING,
)
# Retention has no environment fallback: NULL = never set from the dashboard =
# disabled; 0 = explicitly disabled.
_RETENTION_DISABLED_DAYS = 0


def _resolve_environment_inheritable(row: DashboardSettings, name: str) -> InheritableValue[Any]:
    default = Settings.model_fields[name].default
    # ``Settings`` always carries every field; startup-settings fakes in tests
    # may carry only the fields they exercise, so fall back to the code default.
    return resolve_inheritable(getattr(row, name), getattr(get_settings(), name, default), default)


def _resolve_environment_toggle(row: DashboardSettings, name: str) -> InheritableValue[bool]:
    # C2-3 resilience toggles: same precedence as the integer caps, typed bool.
    default = bool(Settings.model_fields[name].default)
    return resolve_inheritable(getattr(row, name), bool(getattr(get_settings(), name, default)), default)


def _auth_guardian_blocked_by_topology() -> bool:
    # M2 background jobs: read the two topology fields defensively, the way
    # ``_resolve_environment_toggle`` reads its field, so a stub startup-settings
    # object without them reads as "not blocked" instead of raising.
    startup = get_settings()
    ring = getattr(startup, "http_responses_session_bridge_instance_ring", ())
    leader_election_enabled = bool(getattr(startup, "leader_election_enabled", True))
    return len(ring) > 1 and not leader_election_enabled


def warn_environment_shadowed_by_dashboard(row: DashboardSettings, settings: Settings | None = None) -> list[str]:
    """Log one startup WARN naming env vars that are set but ignored because the dashboard owns the value.

    Only settings whose environment variable is explicitly set (``model_fields_set``)
    AND whose dashboard column is non-NULL are reported, so an operator who
    edits the variable learns why nothing changed. Returns the names for tests.
    """
    environment = settings if settings is not None else get_settings()
    shadowed = [
        name
        # M2 background jobs: their env aliases are shadowed the same way.
        for name in (*_ENVIRONMENT_INHERITABLE_SETTINGS, *BACKGROUND_JOB_SETTINGS)
        if name in environment.model_fields_set and getattr(row, name, None) is not None
    ]
    if shadowed:
        logger.warning(
            "environment value(s) ignored because the dashboard owns the setting: %s "
            "(Settings -> Advanced; clear the dashboard value to inherit the environment again)",
            ", ".join(f"CODEX_LB_{name.upper()}" for name in shadowed),
        )
    return shadowed


def _resolve_inheritable_settings(
    row: DashboardSettings,
) -> dict[str, InheritableValue[Any]]:
    resolved: dict[str, InheritableValue[Any]] = {
        name: _resolve_environment_inheritable(row, name) for name in _ENVIRONMENT_INHERITABLE_SETTINGS
    }
    # A stale or hand-edited column value is not a valid decision, so it is
    # normalized away before it can reach the pattern-constrained settings
    # response and fail ``GET /api/settings`` for every setting at once. A
    # NULL-equivalent column simply falls back to the environment/default legs.
    resolved["thread_cache_identity_mode"] = resolve_inheritable(
        normalize_thread_cache_identity_mode(row.thread_cache_identity_mode),
        normalize_thread_cache_identity_mode(getattr(get_settings(), "thread_cache_identity_mode", None))
        or THREAD_CACHE_IDENTITY_MODE_DEFAULT,
        THREAD_CACHE_IDENTITY_MODE_DEFAULT,
    )
    resolved["request_log_retention_days"] = resolve_inheritable(
        row.request_log_retention_days, None, _RETENTION_DISABLED_DAYS
    )
    resolved["usage_history_retention_days"] = resolve_inheritable(
        row.usage_history_retention_days, None, _RETENTION_DISABLED_DAYS
    )
    for name in RESILIENCE_TOGGLE_SETTINGS:  # C2-3 resilience toggles
        resolved[name] = _resolve_environment_toggle(row, name)
    for name in BACKGROUND_JOB_SETTINGS:  # M2 background jobs
        resolved[name] = _resolve_environment_toggle(row, name)
    return resolved


<<<<<<< 22625a07e
def _effective_hourly_rollup_retention(value: int | None) -> int:
    return get_settings().hourly_rollup_retention_days if value is None else value


def _normalize_additional_quota_key(raw_quota_key: str) -> str | None:
    canonical_key = canonicalize_additional_quota_key(quota_key=raw_quota_key, limit_name=raw_quota_key)
    if canonical_key is None:
        return None
    if get_additional_quota_definition(canonical_key) is None:
        return None
    return canonical_key
||||||| 84fde5a1e
def _normalize_additional_quota_key(raw_quota_key: str) -> str | None:
    canonical_key = canonicalize_additional_quota_key(quota_key=raw_quota_key, limit_name=raw_quota_key)
    if canonical_key is None:
        return None
    if get_additional_quota_definition(canonical_key) is None:
        return None
    return canonical_key
=======
def _settings_data(row: DashboardSettings, totp: TotpEnrollmentSummary) -> DashboardSettingsData:
    resolved = _resolve_inheritable_settings(row)
    return DashboardSettingsData(
        sticky_threads_enabled=row.sticky_threads_enabled,
        upstream_stream_transport=row.upstream_stream_transport,
        prohibit_fast_mode=row.prohibit_fast_mode,
        http_downstream_transport_policy=row.http_downstream_transport_policy,
        thread_cache_identity_mode=resolved["thread_cache_identity_mode"].value,
        thread_cache_identity_mode_override=normalize_thread_cache_identity_mode(row.thread_cache_identity_mode),
        proxy_account_response_create_limit=resolved["proxy_account_response_create_limit"].value,
        proxy_account_response_create_limit_override=row.proxy_account_response_create_limit,
        proxy_account_stream_limit=resolved["proxy_account_stream_limit"].value,
        proxy_account_stream_limit_override=row.proxy_account_stream_limit,
        proxy_account_stream_recovery_reserve=resolved["proxy_account_stream_recovery_reserve"].value,
        proxy_account_stream_recovery_reserve_override=row.proxy_account_stream_recovery_reserve,
        proxy_api_key_fair_share_congestion_threshold_pct=(
            resolved["proxy_api_key_fair_share_congestion_threshold_pct"].value
        ),
        proxy_api_key_fair_share_congestion_threshold_pct_override=(
            row.proxy_api_key_fair_share_congestion_threshold_pct
        ),
        # C2-2 routing/overload
        proxy_overload_isolation_seconds=resolved["proxy_overload_isolation_seconds"].value,
        proxy_account_error_rate_weighting_enabled=resolved["proxy_account_error_rate_weighting_enabled"].value,
        proxy_account_inflight_penalty_pct=resolved["proxy_account_inflight_penalty_pct"].value,
        proxy_account_lease_token_weight=resolved["proxy_account_lease_token_weight"].value,
        proxy_account_lease_ttl_seconds=resolved["proxy_account_lease_ttl_seconds"].value,
        # end C2-2 routing/overload
        upstream_proxy_routing_enabled=row.upstream_proxy_routing_enabled,
        upstream_proxy_default_pool_id=row.upstream_proxy_default_pool_id,
        prefer_earlier_reset_accounts=row.prefer_earlier_reset_accounts,
        prefer_earlier_reset_window=row.prefer_earlier_reset_window,
        show_reset_credit_badges=row.show_reset_credit_badges,
        auto_redeem_reset_credits_before_expiry=row.auto_redeem_reset_credits_before_expiry,
        show_reset_credit_expiry_badge=row.show_reset_credit_expiry_badge,
        routing_strategy=row.routing_strategy,
        relative_availability_power=row.relative_availability_power,
        relative_availability_top_k=row.relative_availability_top_k,
        single_account_id=row.single_account_id,
        openai_cache_affinity_max_age_seconds=row.openai_cache_affinity_max_age_seconds,
        dashboard_session_ttl_seconds=row.dashboard_session_ttl_seconds,
        http_responses_session_bridge_prompt_cache_idle_ttl_seconds=(
            row.http_responses_session_bridge_prompt_cache_idle_ttl_seconds
        ),
        http_responses_session_bridge_gateway_safe_mode=row.http_responses_session_bridge_gateway_safe_mode,
        # M3 codex prewarm
        http_responses_session_bridge_codex_prewarm_enabled=bool(
            resolved["http_responses_session_bridge_codex_prewarm_enabled"].value
        ),
        # end M3 codex prewarm
        sticky_reallocation_budget_threshold_pct=row.sticky_reallocation_budget_threshold_pct,
        sticky_reallocation_primary_budget_threshold_pct=row.sticky_reallocation_primary_budget_threshold_pct,
        sticky_reallocation_secondary_budget_threshold_pct=row.sticky_reallocation_secondary_budget_threshold_pct,
        additional_quota_routing_policies=_parse_additional_quota_routing_policies(
            row.additional_quota_routing_policies_json
        ),
        warmup_model=row.warmup_model,
        import_without_overwrite=row.import_without_overwrite,
        totp_required_on_login=row.totp_required_on_login,
        totp_required_for_admin_role=row.totp_required_for_admin_role,
        local_login_policy=row.local_login_policy,
        users_without_totp_count=totp.users_without_totp,
        admins_without_totp_count=totp.admins_without_totp,
        api_key_auth_enabled=row.api_key_auth_enabled,
        hide_upstream_quota_from_api_keys=row.hide_upstream_quota_from_api_keys,
        limit_warmup_enabled=row.limit_warmup_enabled,
        limit_warmup_windows=row.limit_warmup_windows,
        limit_warmup_model=row.limit_warmup_model,
        limit_warmup_prompt=row.limit_warmup_prompt,
        limit_warmup_cooldown_seconds=row.limit_warmup_cooldown_seconds,
        limit_warmup_exhausted_threshold_percent=row.limit_warmup_exhausted_threshold_percent,
        limit_warmup_idle_threshold_percent=row.limit_warmup_idle_threshold_percent,
        limit_warmup_min_available_percent=row.limit_warmup_min_available_percent,
        weekly_pace_working_days=row.weekly_pace_working_days,
        weekly_pace_smoothing_minutes=row.weekly_pace_smoothing_minutes,
        guest_access_enabled=row.guest_access_enabled,
        guest_password_configured=row.guest_password_hash is not None,
        limit_warmup_staggered_idle_enabled=row.limit_warmup_staggered_idle_enabled,
        request_log_retention_days=resolved["request_log_retention_days"].value,
        usage_history_retention_days=resolved["usage_history_retention_days"].value,
        request_log_retention_override_days=row.request_log_retention_days,
        usage_history_retention_override_days=row.usage_history_retention_days,
        # C2-3 resilience toggles
        soft_drain_enabled=bool(resolved["soft_drain_enabled"].value),
        deterministic_failover_enabled=bool(resolved["deterministic_failover_enabled"].value),
        circuit_breaker_enabled=bool(resolved["circuit_breaker_enabled"].value),
        # M2 background jobs
        auth_guardian_enabled=bool(resolved["auth_guardian_enabled"].value),
        auth_guardian_blocked_by_topology=_auth_guardian_blocked_by_topology(),
        automations_scheduler_enabled=bool(resolved["automations_scheduler_enabled"].value),
        rate_limit_reset_credits_refresh_enabled=bool(resolved["rate_limit_reset_credits_refresh_enabled"].value),
        # end M2 background jobs
        # M5 conversation archive
        conversation_archive_enabled=bool(resolved[CONVERSATION_ARCHIVE_SETTING].value),
        # end M5 conversation archive
        # R2 spool retention
        http_responses_session_bridge_operation_spool_retention_seconds=float(
            resolved[OPERATION_SPOOL_RETENTION_SETTING].value
        ),
        # end R2 spool retention
        version=row.version,
        # C2-1 timeouts
        upstream_connect_timeout_seconds=float(resolved["upstream_connect_timeout_seconds"].value),
        proxy_request_budget_seconds=float(resolved["proxy_request_budget_seconds"].value),
        compact_request_budget_seconds=float(resolved["compact_request_budget_seconds"].value),
        transcription_request_budget_seconds=float(resolved["transcription_request_budget_seconds"].value),
        stream_idle_timeout_seconds=float(resolved["stream_idle_timeout_seconds"].value),
        proxy_downstream_websocket_idle_timeout_seconds=float(
            resolved["proxy_downstream_websocket_idle_timeout_seconds"].value
        ),
        sse_keepalive_interval_seconds=float(resolved["sse_keepalive_interval_seconds"].value),
        # end C2-1 timeouts
        # M1 stream/bridge budgets
        http_responses_stream_request_budget_seconds=float(
            resolved["http_responses_stream_request_budget_seconds"].value
        ),
        http_responses_session_bridge_request_budget_seconds=float(
            resolved["http_responses_session_bridge_request_budget_seconds"].value
        ),
        # end M1 stream/bridge budgets
        provenance=resolved,
    )
>>>>>>> 72630bbfe


def _parse_additional_quota_routing_policies(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    policies: dict[str, str] = {}
    for quota_key, policy in parsed.items():
        if not isinstance(quota_key, str) or not isinstance(policy, str):
            continue
        normalized_quota_key = normalize_additional_quota_key(quota_key)
        policy = policy.strip().lower()
        if normalized_quota_key and policy in _ROUTING_POLICIES:
            policies[normalized_quota_key] = policy
    return policies


def _dump_additional_quota_routing_policies(policies: dict[str, str]) -> str:
    normalized = {}
    for quota_key, policy in policies.items():
        if not isinstance(quota_key, str) or not isinstance(policy, str):
            continue
        normalized_quota_key = normalize_additional_quota_key(quota_key)
        normalized_policy = policy.strip().lower()
        if normalized_quota_key is not None and normalized_policy in _ROUTING_POLICIES:
            normalized[normalized_quota_key] = normalized_policy
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"))


def _parse_model_aliases(raw: str | None) -> ModelAliasPools:
    """Parse the stored alias map ``{alias: {"targets": [model, ...]}}``.

    Keyed by the alias the client sends (e.g. ``custom_r1``); the value is the
    ordered list of real upstream model ids it resolves to. The legacy
    ``{alias: "model"}`` shape is read as a one-target pool.
    """

    return parse_alias_pools_json(raw)


def parse_model_aliases(raw: str | None) -> ModelAliasPools:
    return _parse_model_aliases(raw)


def _parse_custom_alias_catalog(raw: str | None) -> dict[str, dict[str, int]]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    catalog: dict[str, dict[str, int]] = {}
    for alias, entry in parsed.items():
        if not isinstance(alias, str) or not isinstance(entry, dict):
            continue
        normalized_alias = alias.strip()
        if not normalized_alias:
            continue
        context_length = entry.get("context_length", entry.get("contextLength"))
        if not isinstance(context_length, int) or isinstance(context_length, bool) or context_length <= 0:
            continue
        catalog[normalized_alias] = {"context_length": context_length}
    return catalog


def parse_custom_alias_catalog(raw: str | None) -> dict[str, dict[str, int]]:
    return _parse_custom_alias_catalog(raw)


def _dump_custom_alias_catalog(catalog: dict[str, dict[str, int]]) -> str:
    normalized: dict[str, dict[str, int]] = {}
    for alias, entry in catalog.items():
        if not isinstance(alias, str) or not isinstance(entry, dict):
            continue
        normalized_alias = alias.strip()
        if not normalized_alias:
            continue
        context_length = entry.get("context_length", entry.get("contextLength"))
        if not isinstance(context_length, int) or isinstance(context_length, bool) or context_length <= 0:
            continue
        normalized[normalized_alias] = {"context_length": context_length}
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"))


def _dump_model_aliases(aliases: Mapping[str, ModelAliasPool]) -> str:
    return dump_alias_pools_json(aliases)


# Providers whose chat dispatch can open the upstream before committing the
# client response, which is what makes a failed attempt retryable on another
# target. A pool with two or more targets may only contain these. Native Codex
# and the other sidecars remain valid as a pool's single target.
POOL_CAPABLE_PROVIDERS: frozenset[str] = frozenset({"orcarouter", "openrouter"})
_POOL_CAPABLE_PROVIDER_PREFIXES: tuple[str, ...] = ("openai_compat:",)

_PROVIDER_LABELS: dict[str, str] = {
    "claude": "CLIProxyAPI",
    "openrouter": "OpenRouter",
    "orcarouter": "OrcaRouter",
    "opencode_go": "OpenCode Go",
    "omniroute": "OmniRoute",
    "ollama": "Ollama",
}


def is_pool_capable_provider(provider: str) -> bool:
    if provider in POOL_CAPABLE_PROVIDERS:
        return True
    return any(provider.startswith(prefix) for prefix in _POOL_CAPABLE_PROVIDER_PREFIXES)


def _provider_label(provider: str, payload: DashboardSettingsUpdateData) -> str:
    label = _PROVIDER_LABELS.get(provider)
    if label is not None:
        return label
    for endpoint in payload.openai_compat_endpoints:
        if endpoint.id is not None and provider == f"openai_compat:{endpoint.id}":
            return endpoint.name
    return provider


@dataclass(frozen=True, slots=True)
class _PayloadRouting:
    """Routing entries for the settings being saved.

    ``enabled`` holds the integrations turned on, which is what the proxy
    routes with; ``configured`` adds the ones turned off. Both are built from
    the payload rather than the stored row, so validation sees the prefixes
    and full models the request is about to persist.
    """

    enabled: tuple[SidecarRoutingEntry, ...]
    configured: tuple[SidecarRoutingEntry, ...]

    def pool_target_route(self, target: str) -> SidecarRoutingDecision | None:
        """The route ``target`` takes now, else the one its turned-off owner gives it.

        Turning an integration off is an operational switch (it ran out of
        credit, say): a pool may keep, reorder, or gain a target on it, and
        the proxy skips that target until it is back on. Only when no enabled
        integration routes the target is the turned-off owner consulted, so a
        target routed now is judged by that route. Integrations the product
        itself disables stay out, by ``resolve_sidecar_pool_target``'s
        capability filter.
        """

        return resolve_sidecar_pool_target(target, self.enabled) or resolve_sidecar_pool_target(target, self.configured)


def _routing_entries_from_payload(payload: DashboardSettingsUpdateData) -> _PayloadRouting:
    enabled_entries: list[SidecarRoutingEntry] = []
    configured_entries: list[SidecarRoutingEntry] = []

    def add(provider: str, enabled: bool, prefixes: list[SidecarPrefix], full_models: list[str]) -> None:
        entry = SidecarRoutingEntry(
            provider=provider,
            prefixes=tuple(prefixes),
            full_models=tuple(full_models),
        )
        configured_entries.append(entry)
        if enabled:
            enabled_entries.append(entry)

    add(
        "claude",
        payload.claude_sidecar_enabled,
        payload.claude_sidecar_model_prefixes,
        payload.claude_sidecar_full_models,
    )
    add(
        "openrouter",
        payload.openrouter_sidecar_enabled,
        payload.openrouter_sidecar_model_prefixes,
        payload.openrouter_sidecar_full_models,
    )
    for endpoint in payload.openai_compat_endpoints:
        if endpoint.id is None:
            continue
        add(f"openai_compat:{endpoint.id}", endpoint.enabled, endpoint.prefixes, endpoint.full_models)
    add(
        "orcarouter",
        payload.orcarouter_sidecar_enabled,
        payload.orcarouter_sidecar_model_prefixes,
        payload.orcarouter_sidecar_full_models,
    )
    add(
        "opencode_go",
        payload.opencode_go_sidecar_enabled,
        payload.opencode_go_sidecar_model_prefixes,
        payload.opencode_go_sidecar_full_models,
    )
    if omniroute_enabled():
        add(
            "omniroute",
            payload.omniroute_sidecar_enabled,
            payload.omniroute_sidecar_model_prefixes,
            payload.omniroute_sidecar_full_models,
        )
    add(
        "ollama",
        payload.ollama_sidecar_enabled,
        payload.ollama_sidecar_model_prefixes,
        payload.ollama_sidecar_full_models,
    )
    enabled = tuple(enabled_entries)
    configured = tuple(configured_entries)
    # The star map decides which card a bare full model routes to when several
    # list it; stars arrive on the payload already filtered to these cards (the
    # caller replaces it with the effective map before validating pools).
    stars = payload.sidecar_full_model_stars
    if stars:
        enabled = apply_full_model_stars(enabled, stars)
        configured = apply_full_model_stars(configured, stars)
    return _PayloadRouting(enabled=enabled, configured=configured)


def _validate_model_alias_pools(
    payload: DashboardSettingsUpdateData,
    *,
    stored_aliases: Mapping[str, ModelAliasPool],
) -> None:
    """Reject the alias problems this save introduces.

    Rules, each naming the alias and the offending target in the error:

    1. no targets;
    2. a repeated target (case-insensitive);
    3. a target that is itself a configured alias (no chains, so no cycles);
    4. two or more targets where any target routes to native Codex or to a
       sidecar that is not pool-capable (see ``_PayloadRouting.pool_target_route``
       for targets on an integration that is turned off);
    5. more than ``MAX_POOL_TARGETS`` targets, or an alias/target over the
       length cap.

    Only what the save changes is judged: every save sends the whole alias map
    back, so re-judging stored aliases would let old data block unrelated
    saves. An alias whose targets match ``stored_aliases`` is skipped, and a
    chain link is allowed only when it was stored and its alias is unchanged.
    That keeps legacy single-step chains (legacy aliases could name another
    alias, harmlessly, and the migration carries them over) while rejecting
    any link a save creates, including one made by adding an alias under a
    name another alias already targets. A stored pool target that a later
    routing change leaves unroutable is skipped by the proxy at request time.

    A one-target pool may point anywhere a legacy alias could, including native
    Codex, so the migration cannot invalidate an existing alias.
    """

    pools = normalize_alias_pools(payload.model_aliases)
    stored_targets = {alias.lower(): pool.targets for alias, pool in stored_aliases.items()}
    changed_aliases: set[str] = set()
    for alias, submitted in payload.model_aliases.items():
        normalized_alias = alias.strip() if isinstance(alias, str) else ""
        if normalized_alias and tuple(_submitted_targets(submitted)) != stored_targets.get(normalized_alias.lower()):
            changed_aliases.add(normalized_alias.lower())

    stored_links = _alias_chain_links(stored_aliases)
    for (alias_key, target_key), (alias, target) in _alias_chain_links(pools).items():
        if alias_key not in changed_aliases and (alias_key, target_key) in stored_links:
            continue
        raise ModelAliasPoolError(
            f"Alias '{alias}' target '{target}' is itself an alias; aliases cannot chain",
            alias=alias,
            target=target,
        )

    routing = _routing_entries_from_payload(payload)
    for alias, submitted in payload.model_aliases.items():
        normalized_alias = alias.strip() if isinstance(alias, str) else ""
        if normalized_alias.lower() not in changed_aliases:
            continue
        raw_targets = _submitted_targets(submitted)
        if len(normalized_alias) > MAX_ALIAS_LENGTH:
            raise ModelAliasPoolError(
                f"Alias '{normalized_alias[:32]}...' is longer than {MAX_ALIAS_LENGTH} characters",
                alias=normalized_alias,
            )
        pool = pools.get(normalized_alias)
        if pool is None:
            # ``normalize_alias_pools`` dropped it: no usable targets. A blank
            # submission is a mistake worth reporting, not silently discarding.
            raise ModelAliasPoolError(f"Alias '{normalized_alias}' has no targets", alias=normalized_alias)
        if len(raw_targets) != len(pool.targets):
            duplicate = _first_duplicate_target(raw_targets)
            raise ModelAliasPoolError(
                f"Alias '{normalized_alias}' lists target '{duplicate}' more than once",
                alias=normalized_alias,
                target=duplicate,
            )
        if len(pool.targets) > MAX_POOL_TARGETS:
            raise ModelAliasPoolError(
                f"Alias '{normalized_alias}' has more than {MAX_POOL_TARGETS} targets",
                alias=normalized_alias,
            )
        for target in pool.targets:
            if len(target) > MAX_TARGET_LENGTH:
                raise ModelAliasPoolError(
                    f"Alias '{normalized_alias}' target is longer than {MAX_TARGET_LENGTH} characters",
                    alias=normalized_alias,
                    target=target,
                )
        if not pool.is_pool:
            continue
        for target in pool.targets:
            decision = routing.pool_target_route(target)
            if decision is None:
                raise ModelAliasPoolError(
                    f"Alias '{normalized_alias}' target '{target}' routes to native Codex, "
                    "which cannot be pooled; use it as the only target instead",
                    alias=normalized_alias,
                    target=target,
                )
            if not is_pool_capable_provider(decision.provider):
                raise ModelAliasPoolError(
                    f"Alias '{normalized_alias}' target '{target}' routes to "
                    f"{_provider_label(decision.provider, payload)}, which does not support pooling yet; "
                    "use it as the only target instead",
                    alias=normalized_alias,
                    target=target,
                )


def _alias_chain_links(pools: Mapping[str, ModelAliasPool]) -> dict[tuple[str, str], tuple[str, str]]:
    """Every ``alias -> target`` link whose target is itself an alias.

    Keyed case-insensitively, valued with the spelling to report.
    """

    alias_keys = {alias.lower() for alias in pools}
    links: dict[tuple[str, str], tuple[str, str]] = {}
    for alias, pool in pools.items():
        for target in pool.targets:
            if target.lower() in alias_keys:
                links.setdefault((alias.lower(), target.lower()), (alias, target))
    return links


def _submitted_targets(value: object) -> list[str]:
    if isinstance(value, ModelAliasPool):
        return [target.strip() for target in value.targets if target.strip()]
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, Mapping):
        raw = value.get("targets")
        if isinstance(raw, list):
            return [target.strip() for target in raw if isinstance(target, str) and target.strip()]
    return []


def _first_duplicate_target(targets: list[str]) -> str:
    seen: set[str] = set()
    for target in targets:
        key = target.lower()
        if key in seen:
            return target
        seen.add(key)
    return targets[-1] if targets else ""


def _parse_sidecar_model_prefixes(
    raw: str | None,
    *,
    default: list[SidecarPrefix] | None = None,
) -> list[SidecarPrefix]:
    if not raw:
        return list(default or [])
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return list(default or [])
    if not isinstance(parsed, list):
        return list(default or [])
    prefixes: list[SidecarPrefix] = []
    seen: set[str] = set()
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        prefix_value = entry.get("prefix")
        if not isinstance(prefix_value, str):
            continue
        normalized = prefix_value.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        prefixes.append(SidecarPrefix(prefix=normalized, strip=bool(entry.get("strip", False))))
    return prefixes or list(default or [])


def _dump_sidecar_model_prefixes(prefixes: list[SidecarPrefix], *, require_one: bool = False) -> str:
    normalized: list[dict[str, object]] = []
    seen: set[str] = set()
    for entry in prefixes:
        prefix = entry.prefix.strip().lower()
        if not prefix or prefix in seen:
            continue
        seen.add(prefix)
        normalized.append({"prefix": prefix, "strip": bool(entry.strip)})
    if require_one and not normalized:
        raise ValueError("claude_sidecar_model_prefixes must include at least one prefix")
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"))


def _parse_claude_sidecar_model_prefixes(raw: str | None) -> list[SidecarPrefix]:
    return _parse_sidecar_model_prefixes(raw, default=list(_DEFAULT_CLAUDE_SIDECAR_PREFIXES))


def _dump_claude_sidecar_model_prefixes(prefixes: list[SidecarPrefix]) -> str:
    normalized = _parse_sidecar_model_prefixes(_dump_sidecar_model_prefixes(prefixes))
    if not normalized:
        raise ValueError("claude_sidecar_model_prefixes must include at least one prefix")
    return _dump_sidecar_model_prefixes(normalized, require_one=True)


def _parse_openrouter_sidecar_model_prefixes(raw: str | None) -> list[SidecarPrefix]:
    return _parse_sidecar_model_prefixes(raw)


def _dump_openrouter_sidecar_model_prefixes(prefixes: list[SidecarPrefix]) -> str:
    return _dump_sidecar_model_prefixes(prefixes)


def _parse_orcarouter_sidecar_model_prefixes(raw: str | None) -> list[SidecarPrefix]:
    return _parse_sidecar_model_prefixes(raw)


def _dump_orcarouter_sidecar_model_prefixes(prefixes: list[SidecarPrefix]) -> str:
    return _dump_sidecar_model_prefixes(prefixes)


def _parse_omniroute_sidecar_model_prefixes(raw: str | None) -> list[SidecarPrefix]:
    return _parse_sidecar_model_prefixes(raw)


def _dump_omniroute_sidecar_model_prefixes(prefixes: list[SidecarPrefix]) -> str:
    return _dump_sidecar_model_prefixes(prefixes)


def _parse_ollama_sidecar_model_prefixes(raw: str | None) -> list[SidecarPrefix]:
    return _parse_sidecar_model_prefixes(raw)


def _dump_ollama_sidecar_model_prefixes(prefixes: list[SidecarPrefix]) -> str:
    return _dump_sidecar_model_prefixes(prefixes)


def _parse_sidecar_full_models(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    models: list[str] = []
    seen: set[str] = set()
    for entry in parsed:
        if not isinstance(entry, str):
            continue
        normalized = entry.strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        models.append(normalized)
    return models


def _dump_sidecar_full_models(models: list[str]) -> str:
    normalized: list[str] = []
    seen: set[str] = set()
    for entry in models:
        stripped = entry.strip()
        if not stripped:
            continue
        key = stripped.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(stripped)
    return json.dumps(normalized, separators=(",", ":"))


def _validate_unique_sidecar_routes(
    payload: DashboardSettingsUpdateData,
    *,
    stored_full_model_stars: dict[str, str],
) -> dict[str, str]:
    omniroute_prefixes = (("OmniRoute", payload.omniroute_sidecar_model_prefixes),) if omniroute_enabled() else ()
    _validate_unique_sidecar_prefixes(
        (
            ("CLIProxyAPI", payload.claude_sidecar_model_prefixes),
            ("OpenRouter", payload.openrouter_sidecar_model_prefixes),
            *((endpoint.name, endpoint.prefixes) for endpoint in payload.openai_compat_endpoints),
            ("OrcaRouter", payload.orcarouter_sidecar_model_prefixes),
            ("OpenCode Go", payload.opencode_go_sidecar_model_prefixes),
            *omniroute_prefixes,
            ("Ollama", payload.ollama_sidecar_model_prefixes),
        )
    )
    # Full models may repeat across integrations; the star map, not uniqueness,
    # decides which card a bare full-model request routes to.
    return _validate_full_model_stars(
        stars=stored_full_model_stars if payload.sidecar_full_model_stars is None else payload.sidecar_full_model_stars,
        payload=payload,
    )


def _validate_full_model_stars(
    *,
    stars: Mapping[str, str],
    payload: DashboardSettingsUpdateData,
) -> dict[str, str]:
    """Filter the star map against the cards this save configures.

    A star survives only when the provider it names is a card in the payload
    that still lists the model. Everything else is dropped rather than
    rejected: the star is advisory routing state, and dropping implements the
    documented removal rule - deleting the starred entry leaves the model
    unrouted-by-default, and a stale star (another client removed the card in
    between) decays instead of blocking an unrelated save. Uniqueness per
    model is structural: the map holds one provider per model by construction.
    """

    cards = _full_models_by_provider(payload)
    filtered: dict[str, str] = {}
    for raw_model, raw_provider in stars.items():
        model = raw_model.strip().lower()
        provider = raw_provider.strip()
        if not model or not provider:
            continue
        models = cards.get(provider)
        if models is None or not any(model == candidate.strip().lower() for candidate in models):
            continue
        filtered[model] = provider
    return filtered


def _full_models_by_provider(payload: DashboardSettingsUpdateData) -> dict[str, list[str]]:
    providers: dict[str, list[str]] = {
        "claude": payload.claude_sidecar_full_models,
        "openrouter": payload.openrouter_sidecar_full_models,
        "orcarouter": payload.orcarouter_sidecar_full_models,
        "opencode_go": payload.opencode_go_sidecar_full_models,
        "ollama": payload.ollama_sidecar_full_models,
    }
    if omniroute_enabled():
        providers["omniroute"] = payload.omniroute_sidecar_full_models
    for endpoint in payload.openai_compat_endpoints:
        if endpoint.id is not None:
            providers[f"openai_compat:{endpoint.id}"] = endpoint.full_models
    return providers


def _dump_full_model_stars(stars: Mapping[str, str]) -> str:
    normalized = {key.strip().lower(): value.strip() for key, value in stars.items() if key.strip() and value.strip()}
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"))


def _validate_unique_sidecar_prefixes(entries: tuple[tuple[str, list[SidecarPrefix]], ...]) -> None:
    owners: dict[str, str] = {}
    for integration, prefixes in entries:
        for prefix in prefixes:
            value = prefix.prefix.strip().lower()
            if not value:
                continue
            owner = owners.get(value)
            if owner is not None and owner != integration:
                raise SidecarRoutingConflictError(
                    SidecarRoutingConflict(
                        kind="prefix",
                        value=value,
                        owner=owner,
                        challenger=integration,
                    )
                )
            owners[value] = integration


def _parse_omniroute_sidecar_selected_models(raw: str | None) -> list[str]:
    return _parse_sidecar_full_models(raw)


def _dump_omniroute_sidecar_selected_models(models: list[str]) -> str:
    return _dump_sidecar_full_models(models)


def _parse_claude_sidecar_auth_plans(raw: str | None) -> list[ClaudeSidecarAuthPlanData]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    plans: list[ClaudeSidecarAuthPlanData] = []
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        auth_index = _optional_str(entry.get("auth_index"))
        email = _optional_str(entry.get("email"))
        source = _optional_str(entry.get("source"))
        plan_type = _optional_str(entry.get("plan_type"))
        if plan_type not in {"pro", "max5", "max20", "custom"}:
            continue
        if not (auth_index or email or source):
            continue
        primary_budget = _optional_positive_int(entry.get("primary_token_budget"))
        secondary_budget = _optional_positive_int(entry.get("secondary_token_budget"))
        if plan_type == "custom" and (primary_budget is None or secondary_budget is None):
            continue
        plans.append(
            ClaudeSidecarAuthPlanData(
                auth_index=auth_index,
                email=email,
                source=source,
                plan_type=plan_type,
                primary_token_budget=primary_budget,
                secondary_token_budget=secondary_budget,
            )
        )
    return plans


def parse_claude_sidecar_auth_plans(raw: str | None) -> list[ClaudeSidecarAuthPlanData]:
    return _parse_claude_sidecar_auth_plans(raw)


def _dump_claude_sidecar_auth_plans(plans: list[ClaudeSidecarAuthPlanData]) -> str:
    payload: list[dict[str, int | str | None]] = []
    seen: set[tuple[str | None, str | None, str | None]] = set()
    for plan in plans:
        key = (plan.auth_index, plan.email, plan.source)
        if key in seen:
            continue
        seen.add(key)
        if not (plan.auth_index or plan.email or plan.source):
            continue
        if plan.plan_type not in {"pro", "max5", "max20", "custom"}:
            continue
        if plan.plan_type == "custom" and (plan.primary_token_budget is None or plan.secondary_token_budget is None):
            raise ValueError("custom Claude auth plan requires both token budgets")
        payload.append(
            {
                "auth_index": plan.auth_index,
                "email": plan.email,
                "source": plan.source,
                "plan_type": plan.plan_type,
                "primary_token_budget": plan.primary_token_budget,
                "secondary_token_budget": plan.secondary_token_budget,
            }
        )
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _optional_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _optional_positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    return None
