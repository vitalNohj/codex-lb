from __future__ import annotations

from datetime import datetime
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator

from app.modules.shared.schemas import DashboardModel

_DEFAULT_WEEKLY_PACE_WORKING_DAYS = "0,1,2,3,4,5,6"


def _normalize_weekly_pace_working_days(value: str | None) -> str | None:
    if value is None:
        return None
    tokens = [part.strip() for part in value.split(",") if part.strip()]
    if not tokens:
        raise ValueError("weekly_pace_working_days must include at least one day")
    try:
        days = sorted({int(token) for token in tokens})
    except ValueError as exc:
        raise ValueError("weekly_pace_working_days must contain weekday numbers") from exc
    if any(day < 0 or day > 6 for day in days):
        raise ValueError("weekly_pace_working_days must use 0-6 weekday numbers")
    return ",".join(str(day) for day in days)


def _normalize_claude_sidecar_base_url(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().rstrip("/")
    if not normalized:
        raise ValueError("claude_sidecar_base_url must not be blank")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("claude_sidecar_base_url must be an http(s) URL")
    return normalized


def _normalize_claude_sidecar_model_prefixes(value: list[str] | None) -> list[str] | None:
    if value is None:
        return None
    prefixes = list(dict.fromkeys(prefix.strip().lower() for prefix in value if prefix.strip()))
    if not prefixes:
        raise ValueError("claude_sidecar_model_prefixes must include at least one prefix")
    if any(len(prefix) > 64 for prefix in prefixes):
        raise ValueError("claude_sidecar_model_prefixes entries must be 64 characters or fewer")
    return prefixes


class AdditionalQuotaPolicy(DashboardModel):
    quota_key: str
    display_label: str
    routing_policy: str = Field(pattern=r"^(inherit|burn_first|normal|preserve)$")
    model_ids: list[str] = Field(default_factory=list)


class ClaudeSidecarAuthPlan(DashboardModel):
    auth_index: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    source: str | None = Field(default=None, max_length=255)
    plan_type: str = Field(pattern=r"^(pro|max5|max20|custom)$")
    primary_token_budget: int | None = Field(default=None, gt=0)
    secondary_token_budget: int | None = Field(default=None, gt=0)

    @field_validator("auth_index", "email", "source")
    @classmethod
    def _normalize_optional_identity(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def _validate_identity_and_budget(self) -> "ClaudeSidecarAuthPlan":
        if not (self.auth_index or self.email or self.source):
            raise ValueError("Claude auth plan must include auth_index, email, or source")
        if self.plan_type == "custom" and (
            self.primary_token_budget is None or self.secondary_token_budget is None
        ):
            raise ValueError("custom Claude auth plan requires both token budgets")
        return self


class DashboardSettingsResponse(DashboardModel):
    sticky_threads_enabled: bool
    upstream_stream_transport: str = Field(pattern=r"^(default|auto|http|websocket)$")
    upstream_proxy_routing_enabled: bool
    upstream_proxy_default_pool_id: str | None = None
    prefer_earlier_reset_accounts: bool
    prefer_earlier_reset_window: str = Field(pattern=r"^(primary|secondary)$")
    routing_strategy: str = Field(
        pattern=r"^(usage_weighted|round_robin|capacity_weighted|relative_availability|fill_first|sequential_drain|reset_drain|single_account)$"
    )
    relative_availability_power: float = Field(gt=0.0)
    relative_availability_top_k: int = Field(ge=1, le=20)
    single_account_id: str | None = None
    openai_cache_affinity_max_age_seconds: int = Field(gt=0)
    dashboard_session_ttl_seconds: int = Field(ge=3600)
    http_responses_session_bridge_prompt_cache_idle_ttl_seconds: int = Field(gt=0)
    http_responses_session_bridge_gateway_safe_mode: bool
    sticky_reallocation_budget_threshold_pct: float = Field(ge=0.0, le=100.0)
    sticky_reallocation_primary_budget_threshold_pct: float = Field(ge=0.0, le=100.0)
    sticky_reallocation_secondary_budget_threshold_pct: float = Field(ge=0.0, le=100.0)
    warmup_model: str = Field(min_length=1)
    import_without_overwrite: bool
    totp_required_on_login: bool
    totp_configured: bool
    api_key_auth_enabled: bool
    limit_warmup_enabled: bool
    limit_warmup_windows: str = Field(pattern=r"^(primary|secondary|both)$")
    limit_warmup_model: str = Field(min_length=1, max_length=128)
    limit_warmup_prompt: str = Field(min_length=1, max_length=512)
    limit_warmup_cooldown_seconds: int = Field(ge=60)
    limit_warmup_min_available_percent: float = Field(gt=0.0, le=100.0)
    weekly_pace_working_days: str = _DEFAULT_WEEKLY_PACE_WORKING_DAYS
    additional_quota_routing_policies: dict[str, str] = Field(default_factory=dict)
    additional_quota_policies: list[AdditionalQuotaPolicy] = Field(default_factory=list)
    claude_sidecar_enabled: bool = False
    claude_sidecar_base_url: str = Field(default="http://127.0.0.1:8317", min_length=1)
    claude_sidecar_api_key_configured: bool = False
    claude_sidecar_model_prefixes: list[str] = Field(default_factory=lambda: ["claude"], min_length=1)
    claude_sidecar_connect_timeout_seconds: float = Field(default=8.0, gt=0)
    claude_sidecar_request_timeout_seconds: float = Field(default=600.0, gt=0)
    claude_sidecar_models_cache_ttl_seconds: float = Field(default=60.0, ge=0)
    claude_sidecar_last_health_status: str | None = None
    claude_sidecar_last_health_message: str | None = None
    claude_sidecar_last_checked_at: datetime | None = None
    claude_sidecar_last_model_count: int | None = Field(default=None, ge=0)
    claude_sidecar_management_key_configured: bool = False
    claude_sidecar_quota_poll_interval_seconds: float = Field(default=60.0, gt=0)
    claude_sidecar_auth_plans: list[ClaudeSidecarAuthPlan] = Field(default_factory=list)
    claude_sidecar_usage_poll_interval_seconds: float = Field(default=15.0, gt=0)
    claude_sidecar_usage_queue_batch_size: int = Field(default=100, gt=0)
    claude_sidecar_usage_collection_enabled: bool = True



class DashboardSettingsUpdateRequest(DashboardModel):
    sticky_threads_enabled: bool | None = None
    upstream_stream_transport: str | None = Field(
        default=None,
        pattern=r"^(default|auto|http|websocket)$",
    )
    upstream_proxy_routing_enabled: bool | None = None
    upstream_proxy_default_pool_id: str | None = None
    prefer_earlier_reset_accounts: bool | None = None
    prefer_earlier_reset_window: str | None = Field(default=None, pattern=r"^(primary|secondary)$")
    routing_strategy: str | None = Field(
        default=None,
        pattern=r"^(usage_weighted|round_robin|capacity_weighted|relative_availability|fill_first|sequential_drain|reset_drain|single_account)$",
    )
    relative_availability_power: float | None = Field(default=None, gt=0.0)
    relative_availability_top_k: int | None = Field(default=None, ge=1, le=20)
    single_account_id: str | None = Field(default=None, max_length=255)
    openai_cache_affinity_max_age_seconds: int | None = Field(default=None, gt=0)
    dashboard_session_ttl_seconds: int | None = Field(default=None, ge=3600)
    http_responses_session_bridge_prompt_cache_idle_ttl_seconds: int | None = Field(default=None, gt=0)
    http_responses_session_bridge_gateway_safe_mode: bool | None = None
    sticky_reallocation_budget_threshold_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    sticky_reallocation_primary_budget_threshold_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    sticky_reallocation_secondary_budget_threshold_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    additional_quota_routing_policies: dict[str, str] | None = None
    warmup_model: str | None = Field(default=None, min_length=1)
    import_without_overwrite: bool | None = None
    totp_required_on_login: bool | None = None
    api_key_auth_enabled: bool | None = None
    limit_warmup_enabled: bool | None = None
    limit_warmup_windows: str | None = Field(default=None, pattern=r"^(primary|secondary|both)$")
    limit_warmup_model: str | None = Field(default=None, min_length=1, max_length=128)
    limit_warmup_prompt: str | None = Field(default=None, min_length=1, max_length=512)
    limit_warmup_cooldown_seconds: int | None = Field(default=None, ge=60)
    limit_warmup_min_available_percent: float | None = Field(default=None, gt=0.0, le=100.0)
    weekly_pace_working_days: str | None = None
    claude_sidecar_enabled: bool | None = None
    claude_sidecar_base_url: str | None = Field(default=None, max_length=2048)
    claude_sidecar_api_key: str | None = Field(default=None, max_length=4096)
    claude_sidecar_clear_api_key: bool | None = None
    claude_sidecar_model_prefixes: list[str] | None = Field(default=None, min_length=1, max_length=32)
    claude_sidecar_connect_timeout_seconds: float | None = Field(default=None, gt=0)
    claude_sidecar_request_timeout_seconds: float | None = Field(default=None, gt=0)
    claude_sidecar_models_cache_ttl_seconds: float | None = Field(default=None, ge=0)
    claude_sidecar_management_key: str | None = Field(default=None, max_length=4096)
    claude_sidecar_clear_management_key: bool | None = None
    claude_sidecar_quota_poll_interval_seconds: float | None = Field(default=None, gt=0)
    claude_sidecar_auth_plans: list[ClaudeSidecarAuthPlan] | None = None
    claude_sidecar_usage_poll_interval_seconds: float | None = Field(default=None, gt=0)
    claude_sidecar_usage_queue_batch_size: int | None = Field(default=None, gt=0, le=1000)
    claude_sidecar_usage_collection_enabled: bool | None = None

    @field_validator("warmup_model")
    @classmethod
    def _normalize_warmup_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("warmup_model must not be blank")
        return normalized

    @field_validator("weekly_pace_working_days")
    @classmethod
    def _normalize_weekly_pace_days(cls, value: str | None) -> str | None:
        return _normalize_weekly_pace_working_days(value)


    @field_validator("claude_sidecar_base_url")
    @classmethod
    def _normalize_sidecar_base_url(cls, value: str | None) -> str | None:
        return _normalize_claude_sidecar_base_url(value)

    @field_validator("claude_sidecar_model_prefixes")
    @classmethod
    def _normalize_sidecar_prefixes(cls, value: list[str] | None) -> list[str] | None:
        return _normalize_claude_sidecar_model_prefixes(value)

    @field_validator("claude_sidecar_api_key")
    @classmethod
    def _normalize_sidecar_api_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()

    @field_validator("claude_sidecar_management_key")
    @classmethod
    def _normalize_sidecar_management_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()


class RuntimeConnectAddressResponse(DashboardModel):
    connect_address: str


class UpstreamProxyEndpointCreateRequest(DashboardModel):
    name: str = Field(min_length=1, max_length=128)
    scheme: str = Field(pattern=r"^(http|https|socks5|socks5h)$")
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    username: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, max_length=1024)
    is_active: bool = True


class UpstreamProxyEndpointResponse(DashboardModel):
    id: str
    name: str
    scheme: str
    host: str
    port: int
    username: str | None
    is_active: bool


class UpstreamProxyPoolCreateRequest(DashboardModel):
    name: str = Field(min_length=1, max_length=128)
    endpoint_ids: list[str] = Field(default_factory=list)
    is_active: bool = True


class UpstreamProxyPoolMemberRequest(DashboardModel):
    endpoint_id: str = Field(min_length=1)
    sort_order: int = 0
    weight: int = Field(default=1, ge=1)
    is_active: bool = True


class UpstreamProxyPoolResponse(DashboardModel):
    id: str
    name: str
    is_active: bool
    endpoint_ids: list[str]


class AccountProxyBindingRequest(DashboardModel):
    pool_id: str = Field(min_length=1)
    is_active: bool = True


class AccountProxyBindingResponse(DashboardModel):
    account_id: str
    pool_id: str
    is_active: bool


class UpstreamProxyAdminResponse(DashboardModel):
    routing_enabled: bool
    default_pool_id: str | None
    endpoints: list[UpstreamProxyEndpointResponse]
    pools: list[UpstreamProxyPoolResponse]
    bindings: list[AccountProxyBindingResponse]
