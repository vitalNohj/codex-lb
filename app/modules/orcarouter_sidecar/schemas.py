from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.modules.shared.schemas import DashboardModel

OrcaRouterSidecarStatus = Literal["disabled", "missing_api_key", "unreachable", "unauthorized", "healthy", "error"]


class OrcaRouterSidecarModelSummary(DashboardModel):
    id: str
    created: int | None = None
    owned_by: str | None = None


class OrcaRouterSidecarStatusResponse(DashboardModel):
    enabled: bool
    configured: bool
    status: OrcaRouterSidecarStatus
    message: str | None = None
    base_url: str
    model_count: int | None = None
    last_checked_at: datetime | None = None


class OrcaRouterSidecarTestResponse(OrcaRouterSidecarStatusResponse):
    models: list[OrcaRouterSidecarModelSummary] = Field(default_factory=list)


class OrcaRouterSidecarModelsResponse(DashboardModel):
    models: list[OrcaRouterSidecarModelSummary] = Field(default_factory=list)
