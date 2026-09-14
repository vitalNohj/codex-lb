from __future__ import annotations

from app.db.models import DashboardSettings
from app.modules.accounts.schemas import AccountRequestUsage, AccountSummary
from app.modules.accounts.sidecar_health import resolve_sidecar_health_status


def build_opencode_go_sidecar_summary(
    settings: DashboardSettings,
    request_usage: AccountRequestUsage | None,
) -> AccountSummary | None:
    """Return a synthetic AccountSummary for OpenCode Go, or None when hidden.

    ``usage`` is deliberately ``None``. That field models a subscription's
    rate-limit windows as codex-lb learns them from a ChatGPT OAuth account, and
    OpenCode Go is a different thing: a $10/month API subscription whose limits
    are per-model dollar caps published as 5-hour / weekly / monthly percentages
    of a monthly budget. Filling ``usage`` with something adjacent would model a
    Go subscription as a fake OAuth account and put numbers on the Accounts page
    that do not mean what the surrounding UI says they mean.

    The five-hour and weekly figures belong to the quota lane's own contract and
    are fetched by the Accounts card as a separate query alongside this summary.
    """

    configured = settings.opencode_go_sidecar_api_key_encrypted is not None or bool(
        settings.opencode_go_sidecar_base_url
    )
    if not configured and not settings.opencode_go_sidecar_enabled:
        return None

    enabled_and_configured = (
        settings.opencode_go_sidecar_enabled and settings.opencode_go_sidecar_api_key_encrypted is not None
    )
    health_status = resolve_sidecar_health_status(
        enabled=bool(settings.opencode_go_sidecar_enabled),
        api_key_configured=settings.opencode_go_sidecar_api_key_encrypted is not None,
        recorded_status=settings.opencode_go_sidecar_last_health_status,
    )
    account_status = "active" if enabled_and_configured else "paused"

    return AccountSummary(
        account_id="opencode-go-sidecar",
        email="opencode.ai",
        alias=None,
        display_name="OpenCode Go",
        workspace_id=None,
        workspace_label="External subscription",
        seat_type="sidecar",
        plan_type="opencode_go",
        routing_policy="normal",
        status=account_status,
        security_work_authorized=False,
        usage=None,
        request_usage=request_usage,
        additional_quotas=[],
        auth=None,
        limit_warmup_enabled=False,
        kind="sidecar",
        provider="opencode_go",
        read_only=True,
        synthetic=True,
        health_status=health_status,
        health_message=settings.opencode_go_sidecar_last_health_message,
        model_count=settings.opencode_go_sidecar_last_model_count,
        base_url=settings.opencode_go_sidecar_base_url,
        last_checked_at=settings.opencode_go_sidecar_last_checked_at,
        sidecar_auths=[],
    )
