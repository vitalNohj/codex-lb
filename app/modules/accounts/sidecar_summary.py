from __future__ import annotations

from app.db.models import DashboardSettings
from app.modules.accounts.schemas import (
    AccountRequestUsage,
    AccountSummary,
    SidecarAuthAccount,
)
from app.modules.claude_sidecar.quota import (
    SidecarAuthQuota,
    SidecarQuotaSnapshot,
    snapshot_from_json,
)


def build_claude_sidecar_summary(
    settings: DashboardSettings,
    request_usage: AccountRequestUsage | None,
) -> AccountSummary | None:
    """Return a synthetic AccountSummary for the Claude sidecar, or None when hidden."""
    configured = (
        settings.claude_sidecar_api_key_encrypted is not None
        or bool(settings.claude_sidecar_base_url)
    )
    if not configured and not settings.claude_sidecar_enabled:
        return None

    health_status = settings.claude_sidecar_last_health_status or (
        "disabled"
        if not settings.claude_sidecar_enabled
        else "missing_api_key"
        if settings.claude_sidecar_api_key_encrypted is None
        else "unknown"
    )

    snapshot = snapshot_from_json(settings.claude_sidecar_quota_state_json)
    account_status, reset_at_primary, last_refresh_at = _derive_quota_state(
        snapshot=snapshot,
        health_status=health_status,
        quota_checked_at=settings.claude_sidecar_quota_checked_at,
    )
    sidecar_auths = _build_auth_rows(snapshot)

    return AccountSummary(
        account_id="claude-sidecar",
        email="cliproxyapi.local",
        alias=None,
        display_name="Claude via CLIProxyAPI",
        workspace_id=None,
        workspace_label="External sidecar",
        seat_type="sidecar",
        plan_type="claude",
        routing_policy="normal",
        status=account_status,
        security_work_authorized=False,
        usage=None,
        reset_at_primary=reset_at_primary,
        last_refresh_at=last_refresh_at,
        request_usage=request_usage,
        additional_quotas=[],
        auth=None,
        limit_warmup_enabled=False,
        kind="sidecar",
        provider="claude",
        read_only=True,
        synthetic=True,
        health_status=health_status,
        health_message=settings.claude_sidecar_last_health_message,
        model_count=settings.claude_sidecar_last_model_count,
        base_url=settings.claude_sidecar_base_url,
        last_checked_at=settings.claude_sidecar_last_checked_at,
        sidecar_auths=sidecar_auths,
    )


def _derive_quota_state(
    *,
    snapshot: SidecarQuotaSnapshot | None,
    health_status: str,
    quota_checked_at,
):
    # When the connection is unhealthy or quota poller never ran, retain
    # the previous "active vs paused" behavior so existing dashboards do
    # not regress.
    if snapshot is None or snapshot.status != "healthy":
        status = "active" if health_status == "healthy" else "paused"
        last_refresh = quota_checked_at if snapshot is not None else None
        return status, None, last_refresh

    accounts = snapshot.accounts
    if not accounts:
        return ("active", None, snapshot.checked_at)

    exceeded = [acct for acct in accounts if acct.quota_exceeded]
    if exceeded and len(exceeded) == len(accounts):
        status = "quota_exceeded"
    elif exceeded:
        status = "rate_limited"
    else:
        status = "active"

    reset_candidates = [acct.next_recover_at for acct in exceeded if acct.next_recover_at is not None]
    reset_at_primary = min(reset_candidates) if reset_candidates else None
    return status, reset_at_primary, snapshot.checked_at


def _build_auth_rows(snapshot: SidecarQuotaSnapshot | None) -> list[SidecarAuthAccount]:
    if snapshot is None:
        return []
    rows: list[SidecarAuthAccount] = []
    for auth in snapshot.accounts:
        rows.append(_auth_row(auth))
    return rows


def _auth_row(auth: SidecarAuthQuota) -> SidecarAuthAccount:
    return SidecarAuthAccount(
        name=auth.name,
        email=auth.email,
        status=auth.status,
        quota_exceeded=auth.quota_exceeded,
        next_recover_at=auth.next_recover_at,
        models_exceeded=[entry.model for entry in auth.model_states if entry.quota_exceeded],
        success=auth.success,
        failed=auth.failed,
    )
