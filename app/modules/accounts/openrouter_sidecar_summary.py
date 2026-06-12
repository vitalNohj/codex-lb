from __future__ import annotations

from app.db.models import DashboardSettings
from app.modules.accounts.schemas import AccountRequestUsage, AccountSummary


def build_openrouter_sidecar_summary(
    settings: DashboardSettings,
    request_usage: AccountRequestUsage | None,
) -> AccountSummary | None:
    """Return a synthetic AccountSummary for the OpenRouter sidecar, or None when hidden."""
    configured = (
        settings.openrouter_sidecar_api_key_encrypted is not None
        or bool(settings.openrouter_sidecar_base_url)
    )
    if not configured and not settings.openrouter_sidecar_enabled:
        return None

    health_status = settings.openrouter_sidecar_last_health_status or (
        "disabled"
        if not settings.openrouter_sidecar_enabled
        else "missing_api_key"
        if settings.openrouter_sidecar_api_key_encrypted is None
        else "unknown"
    )
    account_status = "active" if health_status == "healthy" else "paused"

    return AccountSummary(
        account_id="openrouter-sidecar",
        email="openrouter.ai",
        alias=None,
        display_name="OpenRouter",
        workspace_id=None,
        workspace_label="External sidecar",
        seat_type="sidecar",
        plan_type="openrouter",
        routing_policy="normal",
        status=account_status,
        security_work_authorized=False,
        usage=None,
        request_usage=request_usage,
        additional_quotas=[],
        auth=None,
        limit_warmup_enabled=False,
        kind="sidecar",
        provider="openrouter",
        read_only=True,
        synthetic=True,
        health_status=health_status,
        health_message=settings.openrouter_sidecar_last_health_message,
        model_count=settings.openrouter_sidecar_last_model_count,
        base_url=settings.openrouter_sidecar_base_url,
        last_checked_at=settings.openrouter_sidecar_last_checked_at,
        sidecar_auths=[],
    )
