from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.modules.shared.schemas import DashboardModel

OmniRouteSidecarStatus = Literal["disabled", "missing_api_key", "unreachable", "unauthorized", "healthy", "error"]


class OmniRouteSidecarModelSummary(DashboardModel):
    id: str
    created: int | None = None
    owned_by: str | None = None


class OmniRouteSidecarStatusResponse(DashboardModel):
    enabled: bool
    configured: bool
    status: OmniRouteSidecarStatus
    message: str | None = None
    base_url: str
    model_count: int | None = None
    last_checked_at: datetime | None = None


class OmniRouteSidecarTestResponse(OmniRouteSidecarStatusResponse):
    models: list[OmniRouteSidecarModelSummary] = Field(default_factory=list)


class OmniRouteSidecarModelsResponse(DashboardModel):
    models: list[OmniRouteSidecarModelSummary] = Field(default_factory=list)
