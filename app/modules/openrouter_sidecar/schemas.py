from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.modules.shared.schemas import DashboardModel

OpenRouterSidecarStatus = Literal["disabled", "missing_api_key", "unreachable", "unauthorized", "healthy", "error"]


class OpenRouterSidecarModelSummary(DashboardModel):
    id: str
    created: int | None = None
    owned_by: str | None = None


class OpenRouterSidecarStatusResponse(DashboardModel):
    enabled: bool
    configured: bool
    status: OpenRouterSidecarStatus
    message: str | None = None
    base_url: str
    model_count: int | None = None
    last_checked_at: datetime | None = None


class OpenRouterSidecarTestResponse(OpenRouterSidecarStatusResponse):
    models: list[OpenRouterSidecarModelSummary] = Field(default_factory=list)


class OpenRouterSidecarModelsResponse(DashboardModel):
    models: list[OpenRouterSidecarModelSummary] = Field(default_factory=list)
