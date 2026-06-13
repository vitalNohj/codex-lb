from __future__ import annotations

from app.db.models import DashboardSettings
from app.modules.accounts.schemas import (
    AccountRequestUsage,
    AccountSummary,
    AccountUsage,
    SidecarAuthAccount,
)
from app.modules.claude_sidecar.quota import (
    SidecarAuthQuota,
    SidecarQuotaSnapshot,
    snapshot_from_json,
)
from app.modules.claude_sidecar.usage_estimates import (
    PRIMARY_WINDOW_MINUTES,
    SECONDARY_WINDOW_MINUTES,
    ClaudeAuthUsageEstimate,
    ClaudeUsageEstimates,
)


def build_claude_sidecar_summary(
    settings: DashboardSettings,
    request_usage: AccountRequestUsage | None,
    usage_estimates: ClaudeUsageEstimates | None = None,
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
    sidecar_auths = _build_auth_rows(snapshot, usage_estimates)
    aggregate_usage = usage_estimates.aggregate if usage_estimates is not None else None
    usage = (
        AccountUsage(
            primary_remaining_percent=aggregate_usage.primary_remaining_percent,
            secondary_remaining_percent=aggregate_usage.secondary_remaining_percent,
        )
        if aggregate_usage
        and (
            aggregate_usage.primary_remaining_percent is not None
            or aggregate_usage.secondary_remaining_percent is not None
        )
        else None
    )

    return AccountSummary(
        account_id="claude-sidecar",
        email="cliproxyapi.local",
        alias=None,
        display_name="CLI Proxy API",
        workspace_id=None,
        workspace_label="External sidecar",
        seat_type="sidecar",
        plan_type="claude",
        routing_policy="normal",
        status=account_status,
        security_work_authorized=False,
        usage=usage,
        reset_at_primary=reset_at_primary or (aggregate_usage.reset_at_primary if aggregate_usage else None),
        reset_at_secondary=aggregate_usage.reset_at_secondary if aggregate_usage else None,
        window_minutes_primary=PRIMARY_WINDOW_MINUTES if usage is not None else None,
        window_minutes_secondary=SECONDARY_WINDOW_MINUTES if usage is not None else None,
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


def _build_auth_rows(
    snapshot: SidecarQuotaSnapshot | None,
    usage_estimates: ClaudeUsageEstimates | None,
) -> list[SidecarAuthAccount]:
    estimates_by_key = {
        _estimate_key(estimate): estimate
        for estimate in (usage_estimates.accounts if usage_estimates is not None else [])
        if _estimate_key(estimate) is not None
    }
    if snapshot is None:
        return [_auth_row_from_estimate(estimate) for estimate in estimates_by_key.values()]
    rows: list[SidecarAuthAccount] = []
    seen: set[str] = set()
    for auth in snapshot.accounts:
        key = _auth_key(auth)
        estimate = estimates_by_key.get(key) if key is not None else None
        if key is not None:
            seen.add(key)
        rows.append(_auth_row(auth, estimate))
    for key, estimate in estimates_by_key.items():
        if key not in seen:
            rows.append(_auth_row_from_estimate(estimate))
    return rows


def _auth_row(auth: SidecarAuthQuota, estimate: ClaudeAuthUsageEstimate | None) -> SidecarAuthAccount:
    return SidecarAuthAccount(
        name=auth.name,
        auth_index=auth.auth_index,
        email=auth.email,
        status=auth.status,
        quota_exceeded=auth.quota_exceeded,
        next_recover_at=auth.next_recover_at,
        models_exceeded=[entry.model for entry in auth.model_states if entry.quota_exceeded],
        success=auth.success,
        failed=auth.failed,
        plan_type=estimate.plan_type if estimate else None,
        usage_source=estimate.usage_source if estimate else None,
        primary_remaining_percent=estimate.primary_remaining_percent if estimate else None,
        secondary_remaining_percent=estimate.secondary_remaining_percent if estimate else None,
        primary_used_tokens=estimate.primary_used_tokens if estimate else None,
        secondary_used_tokens=estimate.secondary_used_tokens if estimate else None,
        primary_token_budget=estimate.primary_token_budget if estimate else None,
        secondary_token_budget=estimate.secondary_token_budget if estimate else None,
        reset_at_primary=estimate.reset_at_primary if estimate else None,
        reset_at_secondary=estimate.reset_at_secondary if estimate else None,
        confidence=estimate.confidence if estimate else None,
    )


def _auth_row_from_estimate(estimate: ClaudeAuthUsageEstimate) -> SidecarAuthAccount:
    name = estimate.email or estimate.source or estimate.auth_index or "Claude auth"
    return SidecarAuthAccount(
        name=name,
        auth_index=estimate.auth_index,
        email=estimate.email,
        status=None,
        quota_exceeded=False,
        plan_type=estimate.plan_type,
        usage_source=estimate.usage_source,
        primary_remaining_percent=estimate.primary_remaining_percent,
        secondary_remaining_percent=estimate.secondary_remaining_percent,
        primary_used_tokens=estimate.primary_used_tokens,
        secondary_used_tokens=estimate.secondary_used_tokens,
        primary_token_budget=estimate.primary_token_budget,
        secondary_token_budget=estimate.secondary_token_budget,
        reset_at_primary=estimate.reset_at_primary,
        reset_at_secondary=estimate.reset_at_secondary,
        confidence=estimate.confidence,
    )


def _auth_key(auth: SidecarAuthQuota) -> str | None:
    if auth.auth_index:
        return f"auth:{auth.auth_index}"
    if auth.email:
        return f"source:{auth.email.lower()}"
    return None


def _estimate_key(estimate: ClaudeAuthUsageEstimate) -> str | None:
    if estimate.auth_index:
        return f"auth:{estimate.auth_index}"
    if estimate.email:
        return f"source:{estimate.email.lower()}"
    if estimate.source:
        return f"source:{estimate.source.lower()}"
    return None
