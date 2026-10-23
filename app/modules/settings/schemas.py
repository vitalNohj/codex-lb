from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import Field, StrictInt, field_validator, model_validator

from app.core.config.opencode_go_endpoint import OPENCODE_GO_BASE_URL_ERROR, is_opencode_go_base_url
from app.modules.settings.model_alias_pools import (
    MAX_ALIAS_LENGTH,
    MAX_POOL_TARGETS,
    MAX_TARGET_LENGTH,
    normalize_pool_targets,
)
from app.modules.shared.schemas import DashboardModel

_DEFAULT_WEEKLY_PACE_WORKING_DAYS = "0,1,2,3,4,5,6"
_WEEKLY_PACE_SMOOTHING_MINUTES = (15, 30, 60, 120, 240)
_HTTP_DOWNSTREAM_TRANSPORT_POLICY_PATTERN = r"^(smart|always_http|always_websocket|pinned)$"
_THREAD_CACHE_IDENTITY_MODE_PATTERN = r"^(shared|isolated)$"


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


def _normalize_sidecar_model_prefixes(
    value: list[SidecarModelPrefix] | None,
    *,
    field_name: str,
    require_one: bool = False,
) -> list[SidecarModelPrefix] | None:
    if value is None:
        return None
    prefixes: list[SidecarModelPrefix] = []
    seen: set[str] = set()
    for entry in value:
        prefix = entry.prefix.strip().lower()
        if not prefix or prefix in seen:
            continue
        seen.add(prefix)
        prefixes.append(SidecarModelPrefix(prefix=prefix, strip=entry.strip))
    if require_one and not prefixes:
        raise ValueError(f"{field_name} must include at least one prefix")
    return prefixes


def _normalize_openrouter_sidecar_base_url(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().rstrip("/")
    if not normalized:
        raise ValueError("openrouter_sidecar_base_url must not be blank")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("openrouter_sidecar_base_url must be an http(s) URL")
    return normalized


def _normalize_orcarouter_sidecar_base_url(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().rstrip("/")
    if not normalized:
        raise ValueError("orcarouter_sidecar_base_url must not be blank")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("orcarouter_sidecar_base_url must be an http(s) URL")
    return normalized


def _normalize_opencode_go_sidecar_base_url(value: str | None) -> str | None:
    """Validate an OpenCode **Go** base URL.

    Beyond the usual http(s) check this rejects an OpenCode **Zen** URL. The two
    are different products: Go is the $10/month subscription on ``/zen/go/v1``,
    Zen is pay-as-you-go credits on ``/zen/v1``. Pointing a Go key at the Zen
    path silently bills PAYG credits instead of the subscription, and the two
    paths do not even share per-endpoint authentication conventions, so this is
    a wrong-product error rather than a preference.
    """

    if value is None:
        return None
    normalized = value.strip().rstrip("/")
    if not normalized:
        raise ValueError("opencode_go_sidecar_base_url must not be blank")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("opencode_go_sidecar_base_url must be an http(s) URL")
    if not is_opencode_go_base_url(normalized):
        raise ValueError(f"opencode_go_sidecar_base_url {OPENCODE_GO_BASE_URL_ERROR}")
    return normalized


def _normalize_sidecar_full_models(value: list[str] | None, *, field_name: str) -> list[str] | None:
    if value is None:
        return None
    # Preserve case for the forwarded model; normalize only for comparison in
    # the routing resolver and uniqueness validator.
    models: list[str] = []
    seen: set[str] = set()
    for entry in value:
        normalized = entry.strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        models.append(normalized)
    if any(len(entry) > 256 for entry in models):
        raise ValueError(f"{field_name} entries must be 256 characters or fewer")
    return models


def _coerce_sidecar_model_prefixes(value: object) -> object:
    if not isinstance(value, list):
        return value
    coerced: list[object] = []
    for entry in value:
        if isinstance(entry, str):
            normalized = entry.strip().lower()
            coerced.append({"prefix": normalized, "strip": normalized.endswith(("-", "_"))})
            continue
        coerced.append(entry)
    return coerced


def _normalize_omniroute_sidecar_base_url(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().rstrip("/")
    if not normalized:
        raise ValueError("omniroute_sidecar_base_url must not be blank")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("omniroute_sidecar_base_url must be an http(s) URL")
    return normalized


def _normalize_ollama_sidecar_base_url(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().rstrip("/")
    if not normalized:
        raise ValueError("ollama_sidecar_base_url must not be blank")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("ollama_sidecar_base_url must be an http(s) URL")
    return normalized


_SIDECAR_REASONING_EFFORT_VALUES: frozenset[str] = frozenset({"none", "minimal", "low", "medium", "high", "xhigh"})


def _normalize_sidecar_default_reasoning_effort(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    if normalized not in _SIDECAR_REASONING_EFFORT_VALUES:
        raise ValueError("default_reasoning_effort must be one of none, minimal, low, medium, high, xhigh")
    return normalized


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
        if self.plan_type == "custom" and (self.primary_token_budget is None or self.secondary_token_budget is None):
            raise ValueError("custom Claude auth plan requires both token budgets")
        return self


class SidecarModelPrefix(DashboardModel):
    prefix: str = Field(min_length=1, max_length=64)
    strip: bool = False

    @field_validator("prefix")
    @classmethod
    def _normalize_prefix(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("prefix must not be blank")
        return normalized


class OpenAICompatEndpointResponse(DashboardModel):
    id: str
    name: str
    enabled: bool = False
    base_url: str
    api_key_configured: bool = False
    model_prefixes: list[SidecarModelPrefix] = Field(default_factory=list, max_length=32)
    full_models: list[str] = Field(default_factory=list, max_length=256)
    connect_timeout_seconds: float = Field(default=8.0, gt=0)
    request_timeout_seconds: float = Field(default=600.0, gt=0)
    models_cache_ttl_seconds: float = Field(default=60.0, ge=0)
    default_reasoning_effort: str | None = None
    last_health_status: str | None = None
    last_health_message: str | None = None
    last_checked_at: datetime | None = None
    last_model_count: int | None = Field(default=None, ge=0)


class OpenAICompatEndpointUpdate(DashboardModel):
    id: str | None = Field(default=None, max_length=36)
    name: str = Field(min_length=1, max_length=64)
    enabled: bool = False
    base_url: str = Field(min_length=1, max_length=2048)
    api_key: str | None = Field(default=None, max_length=4096)
    clear_api_key: bool = False
    model_prefixes: list[SidecarModelPrefix] = Field(default_factory=list, max_length=32)
    full_models: list[str] = Field(default_factory=list, max_length=256)
    connect_timeout_seconds: float = Field(default=8.0, gt=0)
    request_timeout_seconds: float = Field(default=600.0, gt=0)
    models_cache_ttl_seconds: float = Field(default=60.0, ge=0)
    default_reasoning_effort: str | None = Field(default=None, max_length=16)

    @field_validator("api_key")
    @classmethod
    def _normalize_api_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("base_url")
    @classmethod
    def _normalize_base_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if not normalized:
            raise ValueError("openai_compat_endpoints base_url must not be blank")
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("openai_compat_endpoints base_url must be an http(s) URL")
        return normalized

    @field_validator("default_reasoning_effort")
    @classmethod
    def _normalize_effort(cls, value: str | None) -> str | None:
        return _normalize_sidecar_default_reasoning_effort(value)


class CustomAliasCatalogEntrySchema(DashboardModel):
    context_length: int | None = Field(default=None, gt=0)


class ModelAliasPoolSchema(DashboardModel):
    """Ordered targets for one alias; ``targets[0]`` is preferred.

    Emptiness is checked by ``_normalize_model_alias_pools`` rather than a
    ``min_length`` here so ``[]`` and ``[""]`` produce the same alias-naming
    error instead of one generic pydantic message and one friendly one.
    """

    targets: list[str] = Field(max_length=MAX_POOL_TARGETS)


def _normalize_model_alias_pools(value: dict[str, Any] | None) -> dict[str, ModelAliasPoolSchema] | None:
    """Accept ``{alias: "model"}`` or ``{alias: {"targets": [...]}}``; return the pool shape.

    Blank aliases and empty pools are dropped here to match the stored-shape
    parser; a pool that is *submitted* empty is reported by the service so the
    operator learns about it rather than watching the alias vanish.
    """

    if value is None:
        return None
    pools: dict[str, ModelAliasPoolSchema] = {}
    seen: set[str] = set()
    for alias, raw in value.items():
        normalized_alias = alias.strip()
        if not normalized_alias:
            continue
        if len(normalized_alias) > MAX_ALIAS_LENGTH:
            raise ValueError(f"model_aliases keys must be {MAX_ALIAS_LENGTH} characters or fewer")
        key = normalized_alias.lower()
        if key in seen:
            continue
        if isinstance(raw, ModelAliasPoolSchema):
            targets = normalize_pool_targets(raw.targets)
        elif isinstance(raw, str):
            targets = normalize_pool_targets((raw,))
        elif isinstance(raw, dict):
            raw_targets = raw.get("targets")
            if not isinstance(raw_targets, list):
                raise ValueError(f"model_aliases['{normalized_alias}'] must be a model id or {{\"targets\": [...]}}")
            targets = normalize_pool_targets(raw_targets)
        else:
            raise ValueError(f"model_aliases['{normalized_alias}'] must be a model id or {{\"targets\": [...]}}")
        if not targets:
            raise ValueError(f"model_aliases['{normalized_alias}'] has no targets")
        for target in targets:
            if len(target) > MAX_TARGET_LENGTH:
                raise ValueError(f"model_aliases targets must be {MAX_TARGET_LENGTH} characters or fewer")
        seen.add(key)
        pools[normalized_alias] = ModelAliasPoolSchema(targets=list(targets))
    return pools


class DashboardLayoutVisibilitySchema(DashboardModel):
    requests: bool = True
    tokens: bool = True
    estimated_cost: bool = True
    conversations: bool = False
    error_rate: bool = True
    usage: bool = True
    accounts: bool = True
    request_logs: bool = True


class DashboardLayoutVisibilityUpdate(DashboardModel):
    requests: bool | None = None
    tokens: bool | None = None
    estimated_cost: bool | None = None
    conversations: bool | None = None
    error_rate: bool | None = None
    usage: bool | None = None
    accounts: bool | None = None
    request_logs: bool | None = None


class SettingProvenance(DashboardModel):
    """Where an inheritable setting's effective value comes from.

    ``source`` is ``"dashboard"`` (the dashboard column is set), ``"env"`` (the
    column is NULL and the environment value differs from the code default) or
    ``"default"``. ``env_value`` is the environment value that applies while
    the column is NULL (``None`` for database-only settings); ``default`` is
    the code default. Both carry the setting's own scalar type.
    """

    source: Literal["dashboard", "env", "default"]
    env_value: int | float | str | bool | None = None
    default: int | float | str | bool | None = None


#: ``dashboard_settings.local_login_policy`` on the wire (PLAN §4.6).
LocalLoginPolicyLiteral = Literal["enabled", "admins_only", "break_glass_only"]


class DashboardSettingsResponse(DashboardModel):
    sticky_threads_enabled: bool
    cliproxy_capacity_routing_enabled: bool = True
    upstream_stream_transport: str = Field(pattern=r"^(auto|http|websocket)$")
    prohibit_fast_mode: bool
    http_downstream_transport_policy: str = Field(pattern=_HTTP_DOWNSTREAM_TRANSPORT_POLICY_PATTERN)
    # Effective mode; ``provenance.thread_cache_identity_mode`` says whether it
    # came from the dashboard column, the environment or the code default.
    thread_cache_identity_mode: str = Field(pattern=_THREAD_CACHE_IDENTITY_MODE_PATTERN)
    thread_cache_identity_mode_override: str | None = Field(default=None, pattern=_THREAD_CACHE_IDENTITY_MODE_PATTERN)
    proxy_account_response_create_limit: int = Field(ge=0)
    proxy_account_response_create_limit_environment_value: int = Field(ge=0)
    proxy_account_response_create_limit_override: int | None = Field(default=None, ge=0)
    proxy_account_stream_limit: int = Field(ge=0)
    proxy_account_stream_limit_environment_value: int = Field(ge=0)
    proxy_account_stream_limit_override: int | None = Field(default=None, ge=0)
    proxy_account_stream_recovery_reserve: int = Field(ge=0)
    proxy_account_stream_recovery_reserve_environment_value: int = Field(ge=0)
    proxy_account_stream_recovery_reserve_override: int | None = Field(default=None, ge=0)
    proxy_api_key_fair_share_congestion_threshold_pct: int = Field(ge=0, le=100)
    proxy_api_key_fair_share_congestion_threshold_pct_environment_value: int = Field(ge=0, le=100)
    proxy_api_key_fair_share_congestion_threshold_pct_override: int | None = Field(default=None, ge=0, le=100)
    # C2-2 routing/overload: effective values (dashboard column, else the
    # environment, else the code default); ``provenance[<name>]`` says which.
    # Only the ``Settings`` bounds apply here: an inherited environment value
    # above the dashboard write cap (penalty > 100) must still be readable.
    proxy_overload_isolation_seconds: int = Field(ge=0)
    proxy_account_error_rate_weighting_enabled: bool
    proxy_account_inflight_penalty_pct: float = Field(ge=0)
    proxy_account_lease_token_weight: float = Field(ge=0)
    proxy_account_lease_ttl_seconds: float = Field(gt=0)
    # end C2-2 routing/overload
    upstream_proxy_routing_enabled: bool
    upstream_proxy_default_pool_id: str | None = None
    prefer_earlier_reset_accounts: bool
    prefer_earlier_reset_window: str = Field(pattern=r"^(primary|secondary)$")
    show_reset_credit_badges: bool
    auto_redeem_reset_credits_before_expiry: bool
    show_reset_credit_expiry_badge: bool
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
    # M3 codex prewarm: effective value; ``provenance[<name>]`` says whether it
    # comes from the dashboard, the deprecated env alias or the code default.
    http_responses_session_bridge_codex_prewarm_enabled: bool
    # end M3 codex prewarm
    sticky_reallocation_budget_threshold_pct: float = Field(ge=0.0, le=100.0)
    sticky_reallocation_primary_budget_threshold_pct: float = Field(ge=0.0, le=100.0)
    sticky_reallocation_secondary_budget_threshold_pct: float = Field(ge=0.0, le=100.0)
    warmup_model: str = Field(min_length=1)
    import_without_overwrite: bool
    totp_required_on_login: bool
    totp_required_for_admin_role: bool
    #: Who may still sign in with a local password (PLAN §4.6). Database
    #: only: no environment variable can silently re-open a closed door.
    local_login_policy: LocalLoginPolicyLiteral
    #: Active password accounts without a TOTP secret; the second counts only
    #: admin-level ones. Both say "N accounts will have to enrol at next sign-in".
    users_without_totp_count: int = Field(ge=0)
    admins_without_totp_count: int = Field(ge=0)
    api_key_auth_enabled: bool
    hide_upstream_quota_from_api_keys: bool
    limit_warmup_enabled: bool
    limit_warmup_windows: str = Field(pattern=r"^(primary|secondary|both)$")
    limit_warmup_model: str = Field(min_length=1, max_length=128)
    limit_warmup_prompt: str = Field(min_length=1, max_length=512)
    limit_warmup_cooldown_seconds: int = Field(ge=60)
    limit_warmup_exhausted_threshold_percent: float = Field(gt=0.0, le=100.0)
    limit_warmup_idle_threshold_percent: float = Field(gt=0.0, le=100.0)
    limit_warmup_min_available_percent: float = Field(gt=0.0, le=100.0)
    weekly_pace_working_days: str = _DEFAULT_WEEKLY_PACE_WORKING_DAYS
    weekly_pace_smoothing_minutes: int = Field(default=30)
    limit_warmup_staggered_idle_enabled: bool
    request_log_retention_days: int = Field(ge=0, le=3650)
    usage_history_retention_days: int = Field(ge=0, le=3650)
    hourly_rollup_retention_days: int = Field(ge=0, le=3650)
    request_log_retention_override_days: int | None = Field(default=None, ge=0, le=3650)
    usage_history_retention_override_days: int | None = Field(default=None, ge=0, le=3650)
    hourly_rollup_retention_override_days: int | None = Field(default=None, ge=0, le=3650)
    additional_quota_routing_policies: dict[str, str] = Field(default_factory=dict)
    model_aliases: dict[str, ModelAliasPoolSchema] = Field(default_factory=dict)
    custom_alias_catalog: dict[str, CustomAliasCatalogEntrySchema] = Field(default_factory=dict)
    additional_quota_policies: list[AdditionalQuotaPolicy] = Field(default_factory=list)
    claude_sidecar_enabled: bool = False
    claude_sidecar_base_url: str = Field(default="http://127.0.0.1:8317", min_length=1)
    claude_sidecar_api_key_configured: bool = False
    claude_sidecar_model_prefixes: list[SidecarModelPrefix] = Field(
        default_factory=lambda: [
            SidecarModelPrefix(prefix="claude", strip=False),
            SidecarModelPrefix(prefix="cp-", strip=True),
            SidecarModelPrefix(prefix="cp_", strip=True),
        ],
        min_length=1,
    )
    claude_sidecar_full_models: list[str] = Field(default_factory=list, max_length=256)
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
    claude_sidecar_default_reasoning_effort: str | None = None
    openrouter_sidecar_enabled: bool = False
    openrouter_sidecar_base_url: str = Field(default="https://openrouter.ai/api/v1", min_length=1)
    openrouter_sidecar_api_key_configured: bool = False
    openrouter_sidecar_model_prefixes: list[SidecarModelPrefix] = Field(default_factory=list, max_length=32)
    openrouter_sidecar_full_models: list[str] = Field(default_factory=list, max_length=256)
    openrouter_sidecar_connect_timeout_seconds: float = Field(default=8.0, gt=0)
    openrouter_sidecar_request_timeout_seconds: float = Field(default=600.0, gt=0)
    openrouter_sidecar_models_cache_ttl_seconds: float = Field(default=60.0, ge=0)
    openrouter_sidecar_last_health_status: str | None = None
    openrouter_sidecar_last_health_message: str | None = None
    openrouter_sidecar_last_checked_at: datetime | None = None
    openrouter_sidecar_last_model_count: int | None = Field(default=None, ge=0)
    openrouter_sidecar_default_reasoning_effort: str | None = None
    openai_compat_endpoints: list[OpenAICompatEndpointResponse] = Field(default_factory=list, max_length=32)
    orcarouter_sidecar_enabled: bool = False
    orcarouter_sidecar_base_url: str = Field(default="https://api.orcarouter.ai/v1", min_length=1)
    orcarouter_sidecar_api_key_configured: bool = False
    orcarouter_sidecar_model_prefixes: list[SidecarModelPrefix] = Field(
        default_factory=lambda: [SidecarModelPrefix(prefix="orcarouter/", strip=False)],
        max_length=32,
    )
    orcarouter_sidecar_full_models: list[str] = Field(default_factory=list, max_length=256)
    orcarouter_sidecar_connect_timeout_seconds: float = Field(default=8.0, gt=0)
    orcarouter_sidecar_request_timeout_seconds: float = Field(default=600.0, gt=0)
    orcarouter_sidecar_models_cache_ttl_seconds: float = Field(default=60.0, ge=0)
    orcarouter_sidecar_last_health_status: str | None = None
    orcarouter_sidecar_last_health_message: str | None = None
    orcarouter_sidecar_last_checked_at: datetime | None = None
    orcarouter_sidecar_last_model_count: int | None = Field(default=None, ge=0)
    orcarouter_sidecar_default_reasoning_effort: str | None = None
    opencode_go_sidecar_enabled: bool = False
    opencode_go_sidecar_base_url: str = Field(default="https://opencode.ai/zen/go/v1", min_length=1)
    opencode_go_sidecar_api_key_configured: bool = False
    opencode_go_sidecar_model_prefixes: list[SidecarModelPrefix] = Field(
        # ``strip=True``: OpenCode's own config format is ``opencode-go/<id>``,
        # so the prefix is an alias that must come off before the wire model is
        # sent, not part of the upstream model id.
        default_factory=lambda: [SidecarModelPrefix(prefix="opencode-go/", strip=True)],
        max_length=32,
    )
    opencode_go_sidecar_full_models: list[str] = Field(default_factory=list, max_length=256)
    opencode_go_sidecar_connect_timeout_seconds: float = Field(default=8.0, gt=0)
    opencode_go_sidecar_request_timeout_seconds: float = Field(default=600.0, gt=0)
    opencode_go_sidecar_models_cache_ttl_seconds: float = Field(default=60.0, ge=0)
    opencode_go_sidecar_last_health_status: str | None = None
    opencode_go_sidecar_last_health_message: str | None = None
    opencode_go_sidecar_last_checked_at: datetime | None = None
    opencode_go_sidecar_last_model_count: int | None = Field(default=None, ge=0)
    omniroute_sidecar_enabled: bool = False
    omniroute_sidecar_base_url: str = Field(default="http://127.0.0.1:20128/v1", min_length=1)
    omniroute_sidecar_api_key_configured: bool = False
    omniroute_sidecar_model_prefixes: list[SidecarModelPrefix] = Field(default_factory=list, max_length=32)
    omniroute_sidecar_full_models: list[str] = Field(default_factory=list, max_length=256)
    omniroute_sidecar_selected_models: list[str] = Field(default_factory=list, max_length=256)
    omniroute_sidecar_connect_timeout_seconds: float = Field(default=8.0, gt=0)
    omniroute_sidecar_request_timeout_seconds: float = Field(default=600.0, gt=0)
    omniroute_sidecar_models_cache_ttl_seconds: float = Field(default=60.0, ge=0)
    omniroute_sidecar_last_health_status: str | None = None
    omniroute_sidecar_last_health_message: str | None = None
    omniroute_sidecar_last_checked_at: datetime | None = None
    omniroute_sidecar_last_model_count: int | None = Field(default=None, ge=0)
    omniroute_sidecar_default_reasoning_effort: str | None = None
    ollama_sidecar_enabled: bool = False
    ollama_sidecar_base_url: str = Field(default="https://ollama.com", min_length=1)
    ollama_sidecar_api_key_configured: bool = False
    ollama_sidecar_model_prefixes: list[SidecarModelPrefix] = Field(default_factory=list, max_length=32)
    ollama_sidecar_full_models: list[str] = Field(default_factory=list, max_length=256)
    ollama_sidecar_connect_timeout_seconds: float = Field(default=8.0, gt=0)
    ollama_sidecar_request_timeout_seconds: float = Field(default=600.0, gt=0)
    ollama_sidecar_models_cache_ttl_seconds: float = Field(default=60.0, ge=0)
    ollama_sidecar_last_health_status: str | None = None
    ollama_sidecar_last_health_message: str | None = None
    ollama_sidecar_last_checked_at: datetime | None = None
    ollama_sidecar_last_model_count: int | None = Field(default=None, ge=0)
    ollama_sidecar_default_reasoning_effort: str | None = None
    # Lower-cased full model -> provider key of the integration starred as the
    # model's default route. Same full model may sit on several cards; the star
    # decides which one owns the bare model id.
    sidecar_full_model_stars: dict[str, str] = Field(default_factory=dict)
    dashboard_layout: DashboardLayoutVisibilitySchema = Field(default_factory=DashboardLayoutVisibilitySchema)
    guest_access_enabled: bool
    guest_password_configured: bool
    # C2-3 resilience toggles: effective values; ``provenance[<name>]`` says
    # whether each comes from the dashboard, the deprecated env alias or the
    # code default.
    soft_drain_enabled: bool
    deterministic_failover_enabled: bool
    circuit_breaker_enabled: bool
    # M2 background jobs: effective values; ``provenance[<name>]`` says whether
    # each comes from the dashboard, the deprecated env alias or the code
    # default. ``auth_guardian_blocked_by_topology`` is True when a multi-replica
    # ring without leader election keeps the guardian idle whatever the toggle.
    auth_guardian_enabled: bool
    auth_guardian_blocked_by_topology: bool
    automations_scheduler_enabled: bool
    rate_limit_reset_credits_refresh_enabled: bool
    # end M2 background jobs
    # M5 conversation archive: effective toggle (``provenance`` says whether it
    # comes from the dashboard, the deprecated env alias or the default) and
    # the read-only T1 archive directory of *this* replica (each replica writes
    # its own local shard; ``None`` for read-only guests).
    conversation_archive_enabled: bool
    conversation_archive_dir: str | None = None
    # end M5 conversation archive
    # R2 spool retention: effective retention of the durable HTTP-bridge
    # operation spool (raw request payloads + spooled response events);
    # ``provenance[<name>]`` says whether the dashboard, the deprecated env
    # alias or the code default supplied it. Unbounded here for the same reason
    # as the C2-1 timeouts: an environment value ``Settings`` accepts must
    # never make ``GET /api/settings`` fail.
    http_responses_session_bridge_operation_spool_retention_seconds: float
    # Lowest value the API would accept for the field above, derived from the
    # longest window in which a spooled operation may still be replayed. The
    # dashboard mirrors this floor client-side.
    http_responses_session_bridge_operation_spool_retention_floor_seconds: float
    # end R2 spool retention
    version: int = Field(ge=1)
    # C2-1 timeouts: effective values; ``provenance[<name>]`` says whether the
    # dashboard, the environment or the code default supplied each one. No
    # bounds here: an environment value the ``Settings`` model accepts must
    # never make ``GET /api/settings`` fail (the update request is bounded).
    upstream_connect_timeout_seconds: float
    proxy_request_budget_seconds: float
    compact_request_budget_seconds: float
    transcription_request_budget_seconds: float
    stream_idle_timeout_seconds: float
    proxy_downstream_websocket_idle_timeout_seconds: float
    sse_keepalive_interval_seconds: float
    # end C2-1 timeouts
    # M1 stream/bridge budgets: effective values, unbounded like the C2-1
    # timeouts above; ``provenance[<name>]`` names the source.
    http_responses_stream_request_budget_seconds: float
    http_responses_session_bridge_request_budget_seconds: float
    # end M1 stream/bridge budgets
    # Provenance of every inheritable setting keyed by its setting name (the
    # ``dashboard_settings`` column / ``Settings`` field name). Additive: the
    # flat ``<name>``, ``<name>_environment_value`` and ``<name>_override``
    # fields above stay as they are.
    provenance: dict[str, SettingProvenance] = Field(default_factory=dict)


#: ``DashboardSettingsUpdateRequest`` fields that change the security posture of
#: the install. A request that changes any of them (value differs from the
#: stored setting) requires ``security:write`` on top of the generic write gate.
SECURITY_SETTINGS_FIELDS: frozenset[str] = frozenset(
    {
        "totp_required_on_login",
        "totp_required_for_admin_role",
        "local_login_policy",
        "api_key_auth_enabled",
        "guest_access_enabled",
        "dashboard_session_ttl_seconds",
        "hide_upstream_quota_from_api_keys",
    }
)


class DashboardSettingsUpdateRequest(DashboardModel):
    """Partial update of the dashboard settings.

    Inheritable settings (the four account-capacity caps, the two retention
    overrides, the three resilience toggles, the Codex prewarm switch and the
    three background job toggles) are tri-state, decided by
    ``model_fields_set``: a field that is
    omitted is left unchanged, an explicit ``null`` clears the dashboard value
    so the setting returns to inheriting the environment value or code default
    (``provenance[<name>].source`` becomes ``"env"`` or ``"default"``), and a
    concrete value is stored and wins over both.
    """

    expected_version: int | None = Field(default=None, ge=1)
    sticky_threads_enabled: bool | None = None
    cliproxy_capacity_routing_enabled: bool | None = None
    upstream_stream_transport: str | None = Field(
        default=None,
        pattern=r"^(auto|http|websocket)$",
    )
    prohibit_fast_mode: bool | None = None
    http_downstream_transport_policy: str | None = Field(
        default=None,
        pattern=_HTTP_DOWNSTREAM_TRANSPORT_POLICY_PATTERN,
    )
    # Tri-state like the caps below: omitted = unchanged, null = inherit the
    # environment value or the ``shared`` code default, value = store.
    thread_cache_identity_mode: str | None = Field(
        default=None,
        pattern=_THREAD_CACHE_IDENTITY_MODE_PATTERN,
    )
    proxy_account_response_create_limit: int | None = Field(default=None, ge=0)
    proxy_account_stream_limit: int | None = Field(default=None, ge=0)
    proxy_account_stream_recovery_reserve: int | None = Field(default=None, ge=0)
    proxy_api_key_fair_share_congestion_threshold_pct: int | None = Field(default=None, ge=0, le=100)
    # C2-2 routing/overload: tri-state like the caps above (omitted = unchanged,
    # null = inherit, value = store). Bounds mirror the ``Settings`` fields; the
    # in-flight penalty is additionally capped at 100 because it is added to a
    # percentage that saturates there.
    proxy_overload_isolation_seconds: int | None = Field(default=None, ge=0)
    proxy_account_error_rate_weighting_enabled: bool | None = None
    proxy_account_inflight_penalty_pct: float | None = Field(default=None, ge=0, le=100)
    proxy_account_lease_token_weight: float | None = Field(default=None, ge=0)
    proxy_account_lease_ttl_seconds: float | None = Field(default=None, gt=0)
    # end C2-2 routing/overload
    upstream_proxy_routing_enabled: bool | None = None
    upstream_proxy_default_pool_id: str | None = None
    prefer_earlier_reset_accounts: bool | None = None
    prefer_earlier_reset_window: str | None = Field(default=None, pattern=r"^(primary|secondary)$")
    show_reset_credit_badges: bool | None = None
    auto_redeem_reset_credits_before_expiry: bool | None = None
    show_reset_credit_expiry_badge: bool | None = None
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
    # M3 codex prewarm: tri-state via ``model_fields_set`` (absent = unchanged,
    # null = clear the dashboard value and inherit the deprecated env alias /
    # code default, value = store).
    http_responses_session_bridge_codex_prewarm_enabled: bool | None = None
    # end M3 codex prewarm
    sticky_reallocation_budget_threshold_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    sticky_reallocation_primary_budget_threshold_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    sticky_reallocation_secondary_budget_threshold_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    additional_quota_routing_policies: dict[str, str] | None = None
    # Either value shape is accepted on write; ``_normalize_model_aliases``
    # always yields the pool shape.
    model_aliases: dict[str, str | ModelAliasPoolSchema] | None = Field(default=None, max_length=256)
    custom_alias_catalog: dict[str, CustomAliasCatalogEntrySchema] | None = Field(default=None, max_length=256)
    warmup_model: str | None = Field(default=None, min_length=1)
    import_without_overwrite: bool | None = None
    totp_required_on_login: bool | None = None
    totp_required_for_admin_role: bool | None = None
    local_login_policy: LocalLoginPolicyLiteral | None = None
    api_key_auth_enabled: bool | None = None
    hide_upstream_quota_from_api_keys: bool | None = None
    limit_warmup_enabled: bool | None = None
    limit_warmup_windows: str | None = Field(default=None, pattern=r"^(primary|secondary|both)$")
    limit_warmup_model: str | None = Field(default=None, min_length=1, max_length=128)
    limit_warmup_prompt: str | None = Field(default=None, min_length=1, max_length=512)
    limit_warmup_cooldown_seconds: int | None = Field(default=None, ge=60)
    limit_warmup_exhausted_threshold_percent: float | None = Field(default=None, gt=0.0, le=100.0)
    limit_warmup_idle_threshold_percent: float | None = Field(default=None, gt=0.0, le=100.0)
    limit_warmup_min_available_percent: float | None = Field(default=None, gt=0.0, le=100.0)
    weekly_pace_working_days: str | None = None
    weekly_pace_smoothing_minutes: int | None = None
    claude_sidecar_enabled: bool | None = None
    claude_sidecar_base_url: str | None = Field(default=None, max_length=2048)
    claude_sidecar_api_key: str | None = Field(default=None, max_length=4096)
    claude_sidecar_clear_api_key: bool | None = None
    claude_sidecar_model_prefixes: list[SidecarModelPrefix] | None = Field(default=None, min_length=1, max_length=32)
    claude_sidecar_full_models: list[str] | None = Field(default=None, max_length=256)
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
    claude_sidecar_default_reasoning_effort: str | None = Field(default=None, max_length=16)
    openrouter_sidecar_enabled: bool | None = None
    openrouter_sidecar_base_url: str | None = Field(default=None, max_length=2048)
    openrouter_sidecar_api_key: str | None = Field(default=None, max_length=4096)
    openrouter_sidecar_clear_api_key: bool | None = None
    openrouter_sidecar_model_prefixes: list[SidecarModelPrefix] | None = Field(default=None, max_length=32)
    openrouter_sidecar_full_models: list[str] | None = Field(default=None, max_length=256)
    openrouter_sidecar_connect_timeout_seconds: float | None = Field(default=None, gt=0)
    openrouter_sidecar_request_timeout_seconds: float | None = Field(default=None, gt=0)
    openrouter_sidecar_models_cache_ttl_seconds: float | None = Field(default=None, ge=0)
    openrouter_sidecar_default_reasoning_effort: str | None = Field(default=None, max_length=16)
    openai_compat_endpoints: list[OpenAICompatEndpointUpdate] | None = Field(default=None, max_length=32)
    orcarouter_sidecar_enabled: bool | None = None
    orcarouter_sidecar_base_url: str | None = Field(default=None, max_length=2048)
    orcarouter_sidecar_api_key: str | None = Field(default=None, max_length=4096)
    orcarouter_sidecar_clear_api_key: bool | None = None
    orcarouter_sidecar_model_prefixes: list[SidecarModelPrefix] | None = Field(default=None, max_length=32)
    orcarouter_sidecar_full_models: list[str] | None = Field(default=None, max_length=256)
    orcarouter_sidecar_connect_timeout_seconds: float | None = Field(default=None, gt=0)
    orcarouter_sidecar_request_timeout_seconds: float | None = Field(default=None, gt=0)
    orcarouter_sidecar_models_cache_ttl_seconds: float | None = Field(default=None, ge=0)
    orcarouter_sidecar_default_reasoning_effort: str | None = Field(default=None, max_length=16)
    opencode_go_sidecar_enabled: bool | None = None
    opencode_go_sidecar_base_url: str | None = Field(default=None, max_length=2048)
    opencode_go_sidecar_api_key: str | None = Field(default=None, max_length=4096)
    opencode_go_sidecar_clear_api_key: bool | None = None
    opencode_go_sidecar_model_prefixes: list[SidecarModelPrefix] | None = Field(default=None, max_length=32)
    opencode_go_sidecar_full_models: list[str] | None = Field(default=None, max_length=256)
    opencode_go_sidecar_connect_timeout_seconds: float | None = Field(default=None, gt=0)
    opencode_go_sidecar_request_timeout_seconds: float | None = Field(default=None, gt=0)
    opencode_go_sidecar_models_cache_ttl_seconds: float | None = Field(default=None, ge=0)
    omniroute_sidecar_enabled: bool | None = None
    omniroute_sidecar_base_url: str | None = Field(default=None, max_length=2048)
    omniroute_sidecar_api_key: str | None = Field(default=None, max_length=4096)
    omniroute_sidecar_clear_api_key: bool | None = None
    omniroute_sidecar_model_prefixes: list[SidecarModelPrefix] | None = Field(default=None, max_length=32)
    omniroute_sidecar_full_models: list[str] | None = Field(default=None, max_length=256)
    omniroute_sidecar_selected_models: list[str] | None = Field(default=None, max_length=256)
    omniroute_sidecar_connect_timeout_seconds: float | None = Field(default=None, gt=0)
    omniroute_sidecar_request_timeout_seconds: float | None = Field(default=None, gt=0)
    omniroute_sidecar_models_cache_ttl_seconds: float | None = Field(default=None, ge=0)
    omniroute_sidecar_default_reasoning_effort: str | None = Field(default=None, max_length=16)
    ollama_sidecar_enabled: bool | None = None
    ollama_sidecar_base_url: str | None = Field(default=None, max_length=2048)
    ollama_sidecar_api_key: str | None = Field(default=None, max_length=4096)
    ollama_sidecar_clear_api_key: bool | None = None
    ollama_sidecar_model_prefixes: list[SidecarModelPrefix] | None = Field(default=None, max_length=32)
    ollama_sidecar_full_models: list[str] | None = Field(default=None, max_length=256)
    ollama_sidecar_connect_timeout_seconds: float | None = Field(default=None, gt=0)
    ollama_sidecar_request_timeout_seconds: float | None = Field(default=None, gt=0)
    ollama_sidecar_models_cache_ttl_seconds: float | None = Field(default=None, ge=0)
    ollama_sidecar_default_reasoning_effort: str | None = Field(default=None, max_length=16)
    guest_access_enabled: bool | None = None
    limit_warmup_staggered_idle_enabled: bool | None = None
    # Tri-state retention overrides: absent = unchanged, present null = clear
    # the override (back to inheriting the deprecated env alias), present
    # value = store the override.
    request_log_retention_override_days: int | None = Field(default=None, ge=0, le=3650)
    usage_history_retention_override_days: int | None = Field(default=None, ge=0, le=3650)
    # No floor validator for the hourly window: anything below the raw
    # request-log window is clamped up at resolution time (max of the two).
    hourly_rollup_retention_override_days: int | None = Field(default=None, ge=0, le=3650)
    # Tri-state star map: absent = keep the stored stars (an older client
    # saving without star knowledge cannot erase them), present map = replace
    # the stored one, filtered against the cards this save configures.
    sidecar_full_model_stars: dict[str, str] | None = Field(default=None, max_length=256)
    dashboard_layout: DashboardLayoutVisibilityUpdate | None = None
    # C2-3 resilience toggles: tri-state via ``model_fields_set`` (absent =
    # unchanged, null = clear the dashboard value and inherit the deprecated
    # env alias / code default, value = store).
    soft_drain_enabled: bool | None = None
    deterministic_failover_enabled: bool | None = None
    circuit_breaker_enabled: bool | None = None
    # M2 background jobs: tri-state via ``model_fields_set`` like the
    # resilience toggles.
    auth_guardian_enabled: bool | None = None
    automations_scheduler_enabled: bool | None = None
    rate_limit_reset_credits_refresh_enabled: bool | None = None
    # end M2 background jobs
    # M5 conversation archive: tri-state like the resilience toggles. ``true``
    # turns the proxy into a full prompt/response recorder; the dashboard asks
    # for confirmation first and the API audits every effective on/off change.
    conversation_archive_enabled: bool | None = None
    # end M5 conversation archive
    # R2 spool retention: tri-state like the C2-1 timeouts (absent = unchanged,
    # null = clear and inherit the deprecated env alias / code default, value =
    # store). The replay floor is enforced in the API layer against the
    # effective value, because it depends on the other dashboard reuse windows.
    http_responses_session_bridge_operation_spool_retention_seconds: float | None = Field(
        default=None, gt=0, le=315360000
    )
    # end R2 spool retention
    # C2-1 timeouts: tri-state like the caps (absent = unchanged, null = clear
    # to inherit the environment / default, value = store). Cross-field timeout
    # invariants are checked against the effective values in the API handler.
    upstream_connect_timeout_seconds: float | None = Field(default=None, gt=0, le=86400)
    proxy_request_budget_seconds: float | None = Field(default=None, gt=0, le=86400)
    compact_request_budget_seconds: float | None = Field(default=None, gt=0, le=86400)
    transcription_request_budget_seconds: float | None = Field(default=None, gt=0, le=86400)
    stream_idle_timeout_seconds: float | None = Field(default=None, gt=0, le=86400)
    proxy_downstream_websocket_idle_timeout_seconds: float | None = Field(default=None, gt=0, le=86400)
    sse_keepalive_interval_seconds: float | None = Field(default=None, ge=0, le=86400)
    # end C2-1 timeouts
    # M1 stream/bridge budgets: same tri-state contract and bounds as the
    # C2-1 timeouts; the connect-within-stream-budget and stuck-gate-within-
    # bridge-budget invariants are checked on the effective values.
    http_responses_stream_request_budget_seconds: float | None = Field(default=None, gt=0, le=86400)
    http_responses_session_bridge_request_budget_seconds: float | None = Field(default=None, gt=0, le=86400)
    # end M1 stream/bridge budgets

    @field_validator("request_log_retention_override_days")
    @classmethod
    def _validate_request_log_retention_override(cls, value: int | None) -> int | None:
        if value is not None and value != 0 and value < 30:
            raise ValueError("request_log_retention_override_days must be 0 (disabled) or >= 30")
        return value

    @field_validator("usage_history_retention_override_days")
    @classmethod
    def _validate_usage_history_retention_override(cls, value: int | None) -> int | None:
        if value is not None and value != 0 and value < 45:
            raise ValueError("usage_history_retention_override_days must be 0 (disabled) or >= 45")
        return value

    @field_validator("sidecar_full_model_stars")
    @classmethod
    def _normalize_sidecar_full_model_stars(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if value is None:
            return None
        return {
            model.strip().lower(): provider.strip()
            for model, provider in value.items()
            if model.strip() and provider.strip()
        }

    @field_validator("model_aliases")
    @classmethod
    def _normalize_model_aliases(
        cls, value: dict[str, str | ModelAliasPoolSchema] | None
    ) -> dict[str, ModelAliasPoolSchema] | None:
        return _normalize_model_alias_pools(value)

    @field_validator("custom_alias_catalog")
    @classmethod
    def _normalize_custom_alias_catalog(
        cls, value: dict[str, CustomAliasCatalogEntrySchema] | None
    ) -> dict[str, CustomAliasCatalogEntrySchema] | None:
        if value is None:
            return None
        catalog: dict[str, CustomAliasCatalogEntrySchema] = {}
        for alias, entry in value.items():
            normalized_alias = alias.strip()
            if not normalized_alias:
                continue
            if len(normalized_alias) > 256:
                raise ValueError("custom_alias_catalog keys must be 256 characters or fewer")
            if entry.context_length is None:
                continue
            catalog[normalized_alias] = entry
        return catalog

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

    @field_validator("weekly_pace_smoothing_minutes")
    @classmethod
    def _validate_weekly_pace_smoothing_minutes(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if value not in _WEEKLY_PACE_SMOOTHING_MINUTES:
            raise ValueError("weekly_pace_smoothing_minutes must be one of 15, 30, 60, 120, 240")
        return value

    @field_validator("claude_sidecar_base_url")
    @classmethod
    def _normalize_sidecar_base_url(cls, value: str | None) -> str | None:
        return _normalize_claude_sidecar_base_url(value)

    @field_validator("claude_sidecar_model_prefixes")
    @classmethod
    def _normalize_sidecar_prefixes(cls, value: list[SidecarModelPrefix] | None) -> list[SidecarModelPrefix] | None:
        return _normalize_sidecar_model_prefixes(
            value,
            field_name="claude_sidecar_model_prefixes",
            require_one=True,
        )

    @field_validator("claude_sidecar_model_prefixes", mode="before")
    @classmethod
    def _coerce_sidecar_prefixes(cls, value: object) -> object:
        return _coerce_sidecar_model_prefixes(value)

    @field_validator("claude_sidecar_full_models")
    @classmethod
    def _normalize_claude_sidecar_full_models(cls, value: list[str] | None) -> list[str] | None:
        return _normalize_sidecar_full_models(value, field_name="claude_sidecar_full_models")

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

    @field_validator("openrouter_sidecar_base_url")
    @classmethod
    def _normalize_openrouter_sidecar_base_url(cls, value: str | None) -> str | None:
        return _normalize_openrouter_sidecar_base_url(value)

    @field_validator("openrouter_sidecar_model_prefixes")
    @classmethod
    def _normalize_openrouter_sidecar_prefixes(
        cls,
        value: list[SidecarModelPrefix] | None,
    ) -> list[SidecarModelPrefix] | None:
        return _normalize_sidecar_model_prefixes(value, field_name="openrouter_sidecar_model_prefixes")

    @field_validator("openrouter_sidecar_model_prefixes", mode="before")
    @classmethod
    def _coerce_openrouter_sidecar_prefixes(cls, value: object) -> object:
        return _coerce_sidecar_model_prefixes(value)

    @field_validator("openrouter_sidecar_full_models")
    @classmethod
    def _normalize_openrouter_sidecar_full_models(cls, value: list[str] | None) -> list[str] | None:
        return _normalize_sidecar_full_models(value, field_name="openrouter_sidecar_full_models")

    @field_validator("openrouter_sidecar_api_key")
    @classmethod
    def _normalize_openrouter_sidecar_api_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()

    @field_validator("orcarouter_sidecar_base_url")
    @classmethod
    def _normalize_orcarouter_sidecar_base_url(cls, value: str | None) -> str | None:
        return _normalize_orcarouter_sidecar_base_url(value)

    @field_validator("orcarouter_sidecar_model_prefixes")
    @classmethod
    def _normalize_orcarouter_sidecar_prefixes(
        cls,
        value: list[SidecarModelPrefix] | None,
    ) -> list[SidecarModelPrefix] | None:
        return _normalize_sidecar_model_prefixes(value, field_name="orcarouter_sidecar_model_prefixes")

    @field_validator("orcarouter_sidecar_model_prefixes", mode="before")
    @classmethod
    def _coerce_orcarouter_sidecar_prefixes(cls, value: object) -> object:
        return _coerce_sidecar_model_prefixes(value)

    @field_validator("orcarouter_sidecar_full_models")
    @classmethod
    def _normalize_orcarouter_sidecar_full_models(cls, value: list[str] | None) -> list[str] | None:
        return _normalize_sidecar_full_models(value, field_name="orcarouter_sidecar_full_models")

    @field_validator("orcarouter_sidecar_api_key")
    @classmethod
    def _normalize_orcarouter_sidecar_api_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()

    @field_validator("opencode_go_sidecar_base_url")
    @classmethod
    def _normalize_opencode_go_sidecar_base_url(cls, value: str | None) -> str | None:
        return _normalize_opencode_go_sidecar_base_url(value)

    @field_validator("opencode_go_sidecar_model_prefixes")
    @classmethod
    def _normalize_opencode_go_sidecar_prefixes(
        cls,
        value: list[SidecarModelPrefix] | None,
    ) -> list[SidecarModelPrefix] | None:
        return _normalize_sidecar_model_prefixes(value, field_name="opencode_go_sidecar_model_prefixes")

    @field_validator("opencode_go_sidecar_model_prefixes", mode="before")
    @classmethod
    def _coerce_opencode_go_sidecar_prefixes(cls, value: object) -> object:
        return _coerce_sidecar_model_prefixes(value)

    @field_validator("opencode_go_sidecar_full_models")
    @classmethod
    def _normalize_opencode_go_sidecar_full_models(cls, value: list[str] | None) -> list[str] | None:
        return _normalize_sidecar_full_models(value, field_name="opencode_go_sidecar_full_models")

    @field_validator("opencode_go_sidecar_api_key")
    @classmethod
    def _normalize_opencode_go_sidecar_api_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()

    @field_validator("omniroute_sidecar_base_url")
    @classmethod
    def _normalize_omniroute_sidecar_base_url(cls, value: str | None) -> str | None:
        return _normalize_omniroute_sidecar_base_url(value)

    @field_validator("omniroute_sidecar_model_prefixes")
    @classmethod
    def _normalize_omniroute_sidecar_prefixes(
        cls,
        value: list[SidecarModelPrefix] | None,
    ) -> list[SidecarModelPrefix] | None:
        return _normalize_sidecar_model_prefixes(value, field_name="omniroute_sidecar_model_prefixes")

    @field_validator("omniroute_sidecar_model_prefixes", mode="before")
    @classmethod
    def _coerce_omniroute_sidecar_prefixes(cls, value: object) -> object:
        return _coerce_sidecar_model_prefixes(value)

    @field_validator("omniroute_sidecar_full_models")
    @classmethod
    def _normalize_omniroute_sidecar_full_models(cls, value: list[str] | None) -> list[str] | None:
        return _normalize_sidecar_full_models(value, field_name="omniroute_sidecar_full_models")

    @field_validator("omniroute_sidecar_selected_models")
    @classmethod
    def _normalize_omniroute_sidecar_models(cls, value: list[str] | None) -> list[str] | None:
        return _normalize_sidecar_full_models(value, field_name="omniroute_sidecar_selected_models")

    @field_validator("omniroute_sidecar_api_key")
    @classmethod
    def _normalize_omniroute_sidecar_api_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()

    @field_validator("ollama_sidecar_base_url")
    @classmethod
    def _normalize_ollama_sidecar_base_url(cls, value: str | None) -> str | None:
        return _normalize_ollama_sidecar_base_url(value)

    @field_validator("ollama_sidecar_model_prefixes")
    @classmethod
    def _normalize_ollama_sidecar_prefixes(
        cls,
        value: list[SidecarModelPrefix] | None,
    ) -> list[SidecarModelPrefix] | None:
        return _normalize_sidecar_model_prefixes(value, field_name="ollama_sidecar_model_prefixes")

    @field_validator("ollama_sidecar_model_prefixes", mode="before")
    @classmethod
    def _coerce_ollama_sidecar_prefixes(cls, value: object) -> object:
        return _coerce_sidecar_model_prefixes(value)

    @field_validator("ollama_sidecar_full_models")
    @classmethod
    def _normalize_ollama_sidecar_full_models(cls, value: list[str] | None) -> list[str] | None:
        return _normalize_sidecar_full_models(value, field_name="ollama_sidecar_full_models")

    @field_validator("ollama_sidecar_api_key")
    @classmethod
    def _normalize_ollama_sidecar_api_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()

    @field_validator(
        "claude_sidecar_default_reasoning_effort",
        "openrouter_sidecar_default_reasoning_effort",
        "orcarouter_sidecar_default_reasoning_effort",
        "omniroute_sidecar_default_reasoning_effort",
        "ollama_sidecar_default_reasoning_effort",
    )
    @classmethod
    def _normalize_default_reasoning_effort(cls, value: str | None) -> str | None:
        return _normalize_sidecar_default_reasoning_effort(value)


class RuntimeConnectAddressResponse(DashboardModel):
    connect_address: str


class AliasPoolTargetHealth(DashboardModel):
    """Failover state of one alias pool target on this replica.

    ``state`` is ``healthy`` or ``cooling``; the remaining fields are set only
    while cooling. Cooldowns are process-local, so a multi-replica deployment
    reports the state of the replica that answered.
    """

    state: str
    until: datetime | None = None
    last_status: int | None = None
    last_error: str | None = None


class AliasPoolsHealthResponse(DashboardModel):
    """``{alias: {target: health}}`` for every configured alias, pool or not."""

    aliases: dict[str, dict[str, AliasPoolTargetHealth]]


# M4 model catalogue: per-model context window overrides. ``source`` is
# ``"dashboard"`` when a dashboard row exists for the slug and ``"env"`` when
# only the ``CODEX_LB_MODEL_CONTEXT_WINDOW_OVERRIDES`` entry applies;
# ``env_value`` is that entry (``None`` when the environment has none).
class ModelContextWindowOverrideResponse(DashboardModel):
    slug: str
    context_window: int
    source: Literal["dashboard", "env"]
    env_value: int | None = None


class ModelContextWindowOverridesResponse(DashboardModel):
    overrides: list[ModelContextWindowOverrideResponse]


# The column is a database ``Integer``, so PostgreSQL rejects anything wider at
# commit time; bounding the request turns that 500 into a 422.
MAX_MODEL_CONTEXT_WINDOW = 2_147_483_647


class ModelContextWindowOverrideUpsertRequest(DashboardModel):
    # StrictInt, not ``int``: a reported context window is a token count, so a
    # bool, a float or a numeric string is an operator mistake to surface as a
    # 422 rather than silently coerce into a stored window.
    context_window: StrictInt = Field(ge=1, le=MAX_MODEL_CONTEXT_WINDOW)


# end M4 model catalogue


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
    # Credentials cross the LB-to-proxy hop unencrypted (http/socks5/socks5h
    # with a username or password); the dashboard renders a warning.
    plaintext_credentials: bool = False


class UpstreamProxyEndpointTestResponse(DashboardModel):
    endpoint_id: str
    ok: bool
    status_code: int | None = None
    elapsed_ms: int | None = None
    error: str | None = None


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
