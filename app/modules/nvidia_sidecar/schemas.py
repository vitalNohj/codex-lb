from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.modules.shared.schemas import DashboardModel

NvidiaSidecarStatus = Literal["disabled", "missing_api_key", "unreachable", "unauthorized", "healthy", "error"]


class NvidiaSidecarModelSummary(DashboardModel):
    id: str
    created: int | None = None
    owned_by: str | None = None


class NvidiaSidecarStatusResponse(DashboardModel):
    enabled: bool
    configured: bool
    status: NvidiaSidecarStatus
    message: str | None = None
    base_url: str
    model_count: int | None = None
    last_checked_at: datetime | None = None


class NvidiaSidecarTestResponse(NvidiaSidecarStatusResponse):
    models: list[NvidiaSidecarModelSummary] = Field(default_factory=list)


class NvidiaSidecarModelsResponse(DashboardModel):
    models: list[NvidiaSidecarModelSummary] = Field(default_factory=list)
