"""Per-provider synthetic account cards for CLIProxyAPI credentials.

The cards stay unregistered until :data:`CLIPROXY_ACCOUNT_POOL_ENABLED` is
turned on. Listing accounts therefore stays identical to today's Claude
sidecar card until the rollout that actually routes these credentials.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.db.models import DashboardSettings
from app.modules.accounts.schemas import AccountSummary, SidecarAuthAccount, SidecarQuotaWindow
from app.modules.claude_sidecar.quota import (
    SidecarAuthQuota,
    SidecarRateLimitHold,
    dashboard_auth_status,
    dashboard_status_for_auth,
)

# Product switch for putting CLIProxyAPI credentials into the accounts list.
# Inventory endpoints do not consult this flag. Leave it false until routing
# is ready so a deploy cannot add new account cards.
CLIPROXY_ACCOUNT_POOL_ENABLED = False

_PROVIDER_LABELS = {
    "claude": "Claude",
    "codex": "Codex",
    "openai": "OpenAI",
    "xai": "xAI",
}


def cliproxy_account_pool_enabled() -> bool:
    """Return whether per-provider CLIProxyAPI cards are added to account lists."""

    return CLIPROXY_ACCOUNT_POOL_ENABLED


def build_cliproxy_provider_summaries(
    settings: DashboardSettings,
    accounts: Sequence[SidecarAuthQuota],
    holds: Sequence[SidecarRateLimitHold] = (),
) -> list[AccountSummary]:
    """Group credentials into one synthetic account per provider.

    ``AccountsService`` calls this only while :func:`cliproxy_account_pool_enabled`
    is true, so a deploy with the switch off does not add cards.
    """

    grouped: dict[str, list[SidecarAuthQuota]] = {}
    for auth in accounts:
        provider = (auth.provider or "unknown").strip().lower() or "unknown"
        grouped.setdefault(provider, []).append(auth)
    return [_summary_for_provider(settings, provider, grouped[provider], holds) for provider in sorted(grouped)]


def _summary_for_provider(
    settings: DashboardSettings,
    provider: str,
    rows: list[SidecarAuthQuota],
    holds: Sequence[SidecarRateLimitHold] = (),
) -> AccountSummary:
    label = _PROVIDER_LABELS.get(provider, provider)
    email = next((row.email for row in rows if row.email), f"{provider}.cliproxy.local")
    usable = any(_usable(row) for row in rows)
    return AccountSummary(
        account_id=f"cliproxy-{_slug(provider)}",
        email=email,
        alias=None,
        display_name=f"CLIProxyAPI {label}",
        workspace_id=None,
        workspace_label="External sidecar",
        seat_type="sidecar",
        plan_type=provider,
        routing_policy="normal",
        status=_summary_status(rows),
        security_work_authorized=False,
        usage=None,
        request_usage=None,
        additional_quotas=[],
        auth=None,
        limit_warmup_enabled=False,
        kind="sidecar",
        provider=provider,
        read_only=True,
        synthetic=True,
        health_status="healthy" if usable else "error",
        health_message=None,
        model_count=None,
        base_url=settings.claude_sidecar_base_url,
        last_checked_at=None,
        sidecar_auths=[_auth_row(row, holds) for row in rows],
    )


def _summary_status(rows: Sequence[SidecarAuthQuota]) -> str:
    if any(_usable(row) for row in rows):
        if any(row.quota_exceeded for row in rows):
            return "rate_limited"
        return "active"
    if rows and all(row.quota_exceeded for row in rows):
        return "quota_exceeded"
    return "paused"


def _usable(row: SidecarAuthQuota) -> bool:
    if row.disabled or row.quota_exceeded or row.unavailable:
        return False
    return dashboard_auth_status(row) != "reauth_required"


def _auth_row(
    auth: SidecarAuthQuota,
    holds: Sequence[SidecarRateLimitHold] = (),
) -> SidecarAuthAccount:
    credits = auth.grok_credits
    windows = [
        SidecarQuotaWindow(
            id=window.id,
            label=window.label,
            kind=window.kind,
            percent_remaining=window.percent_remaining,
            resets_at=window.resets_at,
        )
        for window in (credits.windows if credits is not None else ())
    ]
    return SidecarAuthAccount(
        name=auth.name,
        auth_index=auth.auth_index,
        email=auth.email,
        provider=auth.provider,
        status=dashboard_status_for_auth(auth, holds),
        paused=auth.disabled,
        excluded_models=[],
        excluded_models_state="unsupported",
        quota_exceeded=auth.quota_exceeded,
        next_recover_at=auth.next_recover_at,
        models_exceeded=[entry.model for entry in auth.model_states if entry.quota_exceeded],
        success=auth.success,
        failed=auth.failed,
        quota_windows=windows,
        prepaid_credits=credits.prepaid_credits if credits is not None else None,
    )


def _slug(provider: str) -> str:
    slug = "".join(char if char.isalnum() else "-" for char in provider.lower()).strip("-")
    return slug or "unknown"
