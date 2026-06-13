from __future__ import annotations

from app.db.models import DashboardSettings
from app.modules.accounts.schemas import AccountRequestUsage, AccountSummary
from app.modules.accounts.sidecar_health import resolve_sidecar_health_status


def build_omniroute_sidecar_summary(
    settings: DashboardSettings,
    request_usage: AccountRequestUsage | None,
) -> AccountSummary | None:
    """Return a synthetic AccountSummary for the OmniRoute sidecar, or None when hidden."""
    configured = settings.omniroute_sidecar_api_key_encrypted is not None or bool(settings.omniroute_sidecar_base_url)
    if not configured and not settings.omniroute_sidecar_enabled:
        return None

    enabled_and_configured = (
        settings.omniroute_sidecar_enabled
        and settings.omniroute_sidecar_api_key_encrypted is not None
    )
    health_status = resolve_sidecar_health_status(
        enabled=bool(settings.omniroute_sidecar_enabled),
        api_key_configured=settings.omniroute_sidecar_api_key_encrypted is not None,
        recorded_status=settings.omniroute_sidecar_last_health_status,
    )
    account_status = "active" if enabled_and_configured else "paused"

    return AccountSummary(
        account_id="omniroute-sidecar",
        email="omniroute.local",
        alias=None,
        display_name="OmniRoute",
        workspace_id=None,
        workspace_label="External sidecar",
        seat_type="sidecar",
        plan_type="omniroute",
        routing_policy="normal",
        status=account_status,
        security_work_authorized=False,
        usage=None,
        request_usage=request_usage,
        additional_quotas=[],
        auth=None,
        limit_warmup_enabled=False,
        kind="sidecar",
        provider="omniroute",
        read_only=True,
        synthetic=True,
        health_status=health_status,
        health_message=settings.omniroute_sidecar_last_health_message,
        model_count=settings.omniroute_sidecar_last_model_count,
        base_url=settings.omniroute_sidecar_base_url,
        last_checked_at=settings.omniroute_sidecar_last_checked_at,
        sidecar_auths=[],
    )
