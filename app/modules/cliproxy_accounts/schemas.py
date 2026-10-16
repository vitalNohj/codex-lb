from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.modules.shared.schemas import DashboardModel

CliproxyAccountsStatus = Literal["healthy", "not_configured", "unauthorized", "unreachable", "error"]


class CliproxyQuotaWindow(DashboardModel):
    """One Grok consumer window for a credential card."""

    id: str
    label: str
    kind: str
    percent_remaining: float
    resets_at: datetime | None = None


class CliproxyCredential(DashboardModel):
    """One CLIProxyAPI credential. Token fields are never part of this contract."""

    name: str
    auth_index: str | None = None
    email: str | None = None
    provider: str
    health: str
    disabled: bool = False
    unavailable: bool = False
    quota_exceeded: bool = False
    # CLIProxyAPI v8.0.30 omits prefix from GET /v0/management/auth-files.
    # Keep the field so a later build that adds it surfaces without a schema change.
    prefix: str | None = None
    models: list[str] = Field(default_factory=list)
    models_error: str | None = None
    quota_windows: list[CliproxyQuotaWindow] = Field(default_factory=list)
    prepaid_credits: int | None = None
    usage_tokens: int | None = None
    usage_requests: int | None = None


class CliproxyProviderCredentials(DashboardModel):
    provider: str
    credentials: list[CliproxyCredential] = Field(default_factory=list)


class CliproxyAccountsResponse(DashboardModel):
    status: CliproxyAccountsStatus
    message: str | None = None
    providers: list[CliproxyProviderCredentials] = Field(default_factory=list)
