from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.modules.shared.schemas import DashboardModel

ClaudeSidecarStatus = Literal["disabled", "missing_api_key", "unreachable", "unauthorized", "healthy", "error"]


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
