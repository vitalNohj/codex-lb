from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from app.core.clients.claude_sidecar import SidecarPrefix
from app.core.crypto import TokenEncryptor
from app.modules.settings.repository import SettingsRepository
from app.modules.usage.additional_quota_keys import (
    canonicalize_additional_quota_key,
    get_additional_quota_definition,
)


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
    upstream_proxy_routing_enabled: bool
    upstream_proxy_default_pool_id: str | None
    prefer_earlier_reset_accounts: bool
    prefer_earlier_reset_window: str
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
    warmup_model: str
    import_without_overwrite: bool
    totp_required_on_login: bool
    totp_configured: bool
    api_key_auth_enabled: bool
    limit_warmup_enabled: bool
    limit_warmup_windows: str
    limit_warmup_model: str
    limit_warmup_prompt: str
    limit_warmup_cooldown_seconds: int
    limit_warmup_min_available_percent: float
    weekly_pace_working_days: str
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


@dataclass(frozen=True, slots=True)
class DashboardSettingsUpdateData:
    sticky_threads_enabled: bool
    upstream_stream_transport: str
    upstream_proxy_routing_enabled: bool
    upstream_proxy_default_pool_id: str | None
    prefer_earlier_reset_accounts: bool
    prefer_earlier_reset_window: str
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
    warmup_model: str
    import_without_overwrite: bool
    totp_required_on_login: bool
    api_key_auth_enabled: bool
    limit_warmup_enabled: bool
    limit_warmup_windows: str
    limit_warmup_model: str
    limit_warmup_prompt: str
    limit_warmup_cooldown_seconds: int
    limit_warmup_min_available_percent: float
    weekly_pace_working_days: str
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
    openrouter_sidecar_enabled: bool
    openrouter_sidecar_base_url: str
    openrouter_sidecar_api_key: str | None
    openrouter_sidecar_clear_api_key: bool
    openrouter_sidecar_model_prefixes: list[SidecarPrefix]
    openrouter_sidecar_full_models: list[str]
    openrouter_sidecar_connect_timeout_seconds: float
    openrouter_sidecar_request_timeout_seconds: float
    openrouter_sidecar_models_cache_ttl_seconds: float
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


class SettingsService:
    def __init__(self, repository: SettingsRepository) -> None:
        self._repository = repository
        self._encryptor = TokenEncryptor()

    async def get_settings(self) -> DashboardSettingsData:
        row = await self._repository.get_or_create()
        return self._to_data(row)

    async def update_settings(self, payload: DashboardSettingsUpdateData) -> DashboardSettingsData:
        current = await self._repository.get_or_create()
        if payload.totp_required_on_login and current.totp_secret_encrypted is None:
            raise ValueError("Configure TOTP before enabling login enforcement")
        _validate_unique_sidecar_routes(payload)
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
            management_key_encrypted = (
                self._encryptor.encrypt(management_key_value) if management_key_value else None
            )
        openrouter_api_key_encrypted = current.openrouter_sidecar_api_key_encrypted
        if payload.openrouter_sidecar_clear_api_key:
            openrouter_api_key_encrypted = None
        elif payload.openrouter_sidecar_api_key is not None:
            openrouter_api_key_value = payload.openrouter_sidecar_api_key.strip()
            openrouter_api_key_encrypted = (
                self._encryptor.encrypt(openrouter_api_key_value) if openrouter_api_key_value else None
            )
        omniroute_api_key_encrypted = current.omniroute_sidecar_api_key_encrypted
        if payload.omniroute_sidecar_clear_api_key:
            omniroute_api_key_encrypted = None
        elif payload.omniroute_sidecar_api_key is not None:
            omniroute_api_key_value = payload.omniroute_sidecar_api_key.strip()
            omniroute_api_key_encrypted = (
                self._encryptor.encrypt(omniroute_api_key_value) if omniroute_api_key_value else None
            )
        row = await self._repository.update(
            sticky_threads_enabled=payload.sticky_threads_enabled,
            upstream_stream_transport=payload.upstream_stream_transport,
            upstream_proxy_routing_enabled=payload.upstream_proxy_routing_enabled,
            upstream_proxy_default_pool_id=payload.upstream_proxy_default_pool_id,
            prefer_earlier_reset_accounts=payload.prefer_earlier_reset_accounts,
            prefer_earlier_reset_window=payload.prefer_earlier_reset_window,
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
            warmup_model=payload.warmup_model,
            import_without_overwrite=payload.import_without_overwrite,
            totp_required_on_login=payload.totp_required_on_login,
            api_key_auth_enabled=payload.api_key_auth_enabled,
            limit_warmup_enabled=payload.limit_warmup_enabled,
            limit_warmup_windows=payload.limit_warmup_windows,
            limit_warmup_model=payload.limit_warmup_model,
            limit_warmup_prompt=payload.limit_warmup_prompt,
            limit_warmup_cooldown_seconds=payload.limit_warmup_cooldown_seconds,
            limit_warmup_min_available_percent=payload.limit_warmup_min_available_percent,
            weekly_pace_working_days=payload.weekly_pace_working_days,
            claude_sidecar_enabled=payload.claude_sidecar_enabled,
            claude_sidecar_base_url=payload.claude_sidecar_base_url,
            claude_sidecar_api_key_encrypted=api_key_encrypted,
            claude_sidecar_model_prefixes_json=_dump_claude_sidecar_model_prefixes(payload.claude_sidecar_model_prefixes),
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
            omniroute_sidecar_enabled=payload.omniroute_sidecar_enabled,
            omniroute_sidecar_base_url=payload.omniroute_sidecar_base_url,
            omniroute_sidecar_api_key_encrypted=omniroute_api_key_encrypted,
            omniroute_sidecar_selected_models_json=_dump_omniroute_sidecar_selected_models(
                payload.omniroute_sidecar_full_models
            ),
            omniroute_sidecar_prefixes_json=_dump_omniroute_sidecar_model_prefixes(
                payload.omniroute_sidecar_model_prefixes
            ),
            omniroute_sidecar_connect_timeout_seconds=payload.omniroute_sidecar_connect_timeout_seconds,
            omniroute_sidecar_request_timeout_seconds=payload.omniroute_sidecar_request_timeout_seconds,
            omniroute_sidecar_models_cache_ttl_seconds=payload.omniroute_sidecar_models_cache_ttl_seconds,
        )
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
            upstream_proxy_routing_enabled=row.upstream_proxy_routing_enabled,
            upstream_proxy_default_pool_id=row.upstream_proxy_default_pool_id,
            prefer_earlier_reset_accounts=row.prefer_earlier_reset_accounts,
            prefer_earlier_reset_window=row.prefer_earlier_reset_window,
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
            limit_warmup_enabled=row.limit_warmup_enabled,
            limit_warmup_windows=row.limit_warmup_windows,
            limit_warmup_model=row.limit_warmup_model,
            limit_warmup_prompt=row.limit_warmup_prompt,
            limit_warmup_cooldown_seconds=row.limit_warmup_cooldown_seconds,
            limit_warmup_min_available_percent=row.limit_warmup_min_available_percent,
            weekly_pace_working_days=row.weekly_pace_working_days,
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
        )


_ROUTING_POLICIES = frozenset({"inherit", "normal", "burn_first", "preserve"})
_DEFAULT_CLAUDE_SIDECAR_PREFIXES = [
    SidecarPrefix(prefix="claude", strip=False),
    SidecarPrefix(prefix="cp-", strip=True),
    SidecarPrefix(prefix="cp_", strip=True),
]


def _normalize_additional_quota_key(raw_quota_key: str) -> str | None:
    canonical_key = canonicalize_additional_quota_key(quota_key=raw_quota_key, limit_name=raw_quota_key)
    if canonical_key is None:
        return None
    if get_additional_quota_definition(canonical_key) is None:
        return None
    return canonical_key


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
        normalized_quota_key = _normalize_additional_quota_key(quota_key)
        policy = policy.strip().lower()
        if normalized_quota_key and policy in _ROUTING_POLICIES:
            policies[normalized_quota_key] = policy
    return policies


def _dump_additional_quota_routing_policies(policies: dict[str, str]) -> str:
    normalized = {}
    for quota_key, policy in policies.items():
        if not isinstance(quota_key, str) or not isinstance(policy, str):
            continue
        normalized_quota_key = _normalize_additional_quota_key(quota_key)
        normalized_policy = policy.strip().lower()
        if normalized_quota_key is not None and normalized_policy in _ROUTING_POLICIES:
            normalized[normalized_quota_key] = normalized_policy
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"))


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


def _parse_omniroute_sidecar_model_prefixes(raw: str | None) -> list[SidecarPrefix]:
    return _parse_sidecar_model_prefixes(raw)


def _dump_omniroute_sidecar_model_prefixes(prefixes: list[SidecarPrefix]) -> str:
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


def _validate_unique_sidecar_routes(payload: DashboardSettingsUpdateData) -> None:
    _validate_unique_sidecar_prefixes(
        (
            ("CLIProxyAPI", payload.claude_sidecar_model_prefixes),
            ("OpenRouter", payload.openrouter_sidecar_model_prefixes),
            ("OmniRoute", payload.omniroute_sidecar_model_prefixes),
        )
    )
    _validate_unique_sidecar_full_models(
        (
            ("CLIProxyAPI", payload.claude_sidecar_full_models),
            ("OpenRouter", payload.openrouter_sidecar_full_models),
            ("OmniRoute", payload.omniroute_sidecar_full_models),
        )
    )


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


def _validate_unique_sidecar_full_models(entries: tuple[tuple[str, list[str]], ...]) -> None:
    owners: dict[str, tuple[str, str]] = {}
    for integration, models in entries:
        for model in models:
            value = model.strip()
            if not value:
                continue
            key = value.lower()
            owner = owners.get(key)
            if owner is not None and owner[0] != integration:
                raise SidecarRoutingConflictError(
                    SidecarRoutingConflict(
                        kind="full_model",
                        value=value,
                        owner=owner[0],
                        challenger=integration,
                    )
                )
            owners[key] = (integration, value)


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
        if plan.plan_type == "custom" and (
            plan.primary_token_budget is None or plan.secondary_token_budget is None
        ):
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
