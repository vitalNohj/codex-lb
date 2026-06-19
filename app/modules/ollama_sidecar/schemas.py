from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.modules.shared.schemas import DashboardModel

OllamaSidecarStatus = Literal["disabled", "missing_api_key", "unreachable", "unauthorized", "healthy", "error"]


class OllamaSidecarModelSummary(DashboardModel):
    id: str
    created: int | None = None
    owned_by: str | None = None


class OllamaSidecarStatusResponse(DashboardModel):
    enabled: bool
    configured: bool
    status: OllamaSidecarStatus
    message: str | None = None
    base_url: str
    model_count: int | None = None
    last_checked_at: datetime | None = None


class OllamaSidecarTestResponse(OllamaSidecarStatusResponse):
    models: list[OllamaSidecarModelSummary] = Field(default_factory=list)


class OllamaSidecarModelsResponse(DashboardModel):
    models: list[OllamaSidecarModelSummary] = Field(default_factory=list)
