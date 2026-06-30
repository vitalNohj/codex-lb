from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.modules.accounts.schemas import SidecarAuthAccount
from app.modules.shared.schemas import DashboardModel

ClaudeSidecarStatus = Literal["disabled", "missing_api_key", "unreachable", "unauthorized", "healthy", "error"]
ClaudeSidecarQuotaStatus = Literal[
    "healthy", "unauthorized", "unreachable", "error", "unknown", "disabled", "not_configured"
]
ClaudeSidecarRoutingStatus = Literal["healthy", "disabled", "not_configured", "unreachable", "unauthorized", "error"]
ClaudeSidecarRoutingStrategy = Literal["round_robin", "fill_first"]


class ClaudeSidecarModelSummary(DashboardModel):
    id: str
    created: int | None = None
    owned_by: str | None = None


class ClaudeSidecarStatusResponse(DashboardModel):
    enabled: bool
    configured: bool
    status: ClaudeSidecarStatus
    message: str | None = None
    base_url: str
    model_count: int | None = None
    last_checked_at: datetime | None = None


class ClaudeSidecarTestResponse(ClaudeSidecarStatusResponse):
    models: list[ClaudeSidecarModelSummary] = Field(default_factory=list)


class ClaudeSidecarModelsResponse(DashboardModel):
    models: list[ClaudeSidecarModelSummary] = Field(default_factory=list)


class ClaudeSidecarQuotaResponse(DashboardModel):
    status: ClaudeSidecarQuotaStatus
    message: str | None = None
    checked_at: datetime | None = None
    accounts: list[SidecarAuthAccount] = Field(default_factory=list)


class ClaudeSidecarRoutingAccount(DashboardModel):
    name: str
    auth_index: str | None = None
    email: str | None = None
    priority: int = 0


class ClaudeSidecarRoutingResponse(DashboardModel):
    status: ClaudeSidecarRoutingStatus
    message: str | None = None
    strategy: ClaudeSidecarRoutingStrategy | None = None
    accounts: list[ClaudeSidecarRoutingAccount] = Field(default_factory=list)


class ClaudeSidecarRoutingStrategyUpdate(DashboardModel):
    strategy: ClaudeSidecarRoutingStrategy


class ClaudeSidecarAccountPriorityUpdate(DashboardModel):
    name: str = Field(min_length=1)
    priority: int = Field(ge=0, le=1_000_000)
