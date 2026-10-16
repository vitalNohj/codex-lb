from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.modules.shared.schemas import DashboardModel

QuotaConfidence = Literal["established", "estimated", "unknown"]


class QuotaFeedWindow(DashboardModel):
    id: str
    kind: str
    percent_remaining: float | None = None
    resets_at: datetime | None = None
    confidence: QuotaConfidence
    source: str


class QuotaFeedAccount(DashboardModel):
    provider: str
    account_key: str
    windows: list[QuotaFeedWindow]


class ProviderHeadroom(DashboardModel):
    accounts_available: int = Field(ge=0)
    max_headroom_percent: float | None = None


class QuotaFeedResponse(DashboardModel):
    schema_version: int = 1
    generated_at: datetime
    providers: list[QuotaFeedAccount]
    per_provider: dict[str, ProviderHeadroom]
