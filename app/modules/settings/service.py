from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

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
    claude_sidecar_model_prefixes: list[str]
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
    claude_sidecar_model_prefixes: list[str]
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
            claude_sidecar_connect_timeout_seconds=payload.claude_sidecar_connect_timeout_seconds,
            claude_sidecar_request_timeout_seconds=payload.claude_sidecar_request_timeout_seconds,
            claude_sidecar_models_cache_ttl_seconds=payload.claude_sidecar_models_cache_ttl_seconds,
            claude_sidecar_management_key_encrypted=management_key_encrypted,
            claude_sidecar_quota_poll_interval_seconds=payload.claude_sidecar_quota_poll_interval_seconds,
            claude_sidecar_auth_plans_json=_dump_claude_sidecar_auth_plans(payload.claude_sidecar_auth_plans),
            claude_sidecar_usage_poll_interval_seconds=payload.claude_sidecar_usage_poll_interval_seconds,
            claude_sidecar_usage_queue_batch_size=payload.claude_sidecar_usage_queue_batch_size,
            claude_sidecar_usage_collection_enabled=payload.claude_sidecar_usage_collection_enabled,
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
        )


_ROUTING_POLICIES = frozenset({"inherit", "normal", "burn_first", "preserve"})
_DEFAULT_CLAUDE_SIDECAR_PREFIXES = ["claude"]


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


def _parse_claude_sidecar_model_prefixes(raw: str | None) -> list[str]:
    if not raw:
        return list(_DEFAULT_CLAUDE_SIDECAR_PREFIXES)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return list(_DEFAULT_CLAUDE_SIDECAR_PREFIXES)
    if not isinstance(parsed, list):
        return list(_DEFAULT_CLAUDE_SIDECAR_PREFIXES)
    prefixes = [entry.strip() for entry in parsed if isinstance(entry, str) and entry.strip()]
    return prefixes or list(_DEFAULT_CLAUDE_SIDECAR_PREFIXES)


def _dump_claude_sidecar_model_prefixes(prefixes: list[str]) -> str:
    normalized = list(dict.fromkeys(prefix.strip().lower() for prefix in prefixes if prefix.strip()))
    if not normalized:
        raise ValueError("claude_sidecar_model_prefixes must include at least one prefix")
    return json.dumps(normalized, separators=(",", ":"))


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
