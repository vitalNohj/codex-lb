from __future__ import annotations

from urllib.parse import urlparse

from app.modules.accounts.schemas import AccountRequestUsage, AccountSummary
from app.modules.openai_compat.endpoints import StoredOpenAICompatEndpoint


def build_openai_compat_summary(
    endpoint: StoredOpenAICompatEndpoint,
    request_usage: AccountRequestUsage | None,
) -> AccountSummary:
    health_status = _resolve_health(endpoint)
    host = urlparse(endpoint.base_url).netloc or endpoint.base_url
    return AccountSummary(
        account_id=endpoint.account_id,
        email=host,
        alias=None,
        display_name=endpoint.name,
        workspace_id=None,
        workspace_label="External sidecar",
        seat_type="sidecar",
        plan_type="openai_compat",
        routing_policy="normal",
        status="active" if endpoint.enabled else "paused",
        security_work_authorized=False,
        usage=None,
        request_usage=request_usage,
        additional_quotas=[],
        auth=None,
        limit_warmup_enabled=False,
        kind="sidecar",
        provider="openai_compat",
        read_only=True,
        synthetic=True,
        health_status=health_status,
        health_message=endpoint.last_health_message,
        model_count=endpoint.last_model_count,
        base_url=endpoint.base_url,
        last_checked_at=endpoint.last_checked_at,
        sidecar_auths=[],
    )


def _resolve_health(endpoint: StoredOpenAICompatEndpoint) -> str:
    if not endpoint.enabled:
        return "disabled"
    recorded = endpoint.last_health_status
    if recorded in {"unreachable", "unauthorized", "healthy", "error"}:
        return recorded
    return "healthy"
