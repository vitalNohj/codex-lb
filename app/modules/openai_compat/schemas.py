from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.modules.shared.schemas import DashboardModel

OpenAICompatStatus = Literal["disabled", "unreachable", "unauthorized", "healthy", "error"]


class OpenAICompatModelSummary(DashboardModel):
    id: str
    created: int | None = None
    owned_by: str | None = None


class OpenAICompatStatusResponse(DashboardModel):
    id: str
    name: str
    enabled: bool
    configured: bool
    status: OpenAICompatStatus
    message: str | None = None
    base_url: str
    model_count: int | None = None
    last_checked_at: datetime | None = None


class OpenAICompatTestResponse(OpenAICompatStatusResponse):
    models: list[OpenAICompatModelSummary] = Field(default_factory=list)


class OpenAICompatModelsResponse(DashboardModel):
    models: list[OpenAICompatModelSummary] = Field(default_factory=list)
