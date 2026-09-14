from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.modules.shared.schemas import DashboardModel

OpenCodeGoSidecarStatus = Literal["disabled", "missing_api_key", "unreachable", "unauthorized", "healthy", "error"]

#: Upstream endpoint shape, mirroring ``OpenCodeGoProtocol``. Declared here as a
#: literal rather than reusing the enum so the dashboard contract does not move
#: whenever the internal enum gains an internal-only member.
OpenCodeGoModelProtocol = Literal["chat_completions", "messages", "responses", "unknown"]


class OpenCodeGoSidecarModelSummary(DashboardModel):
    """One model from the live Go listing, annotated with what we can do with it.

    ``protocol`` and ``supported`` exist because OpenCode Go serves its
    catalogue across three differently-shaped endpoints and this build speaks
    only ``/chat/completions``. Without them the dashboard would list models it
    cannot route as though they were available. A model with ``supported:
    false`` must be rendered as visibly unavailable, not hidden and not offered.
    """

    id: str
    created: int | None = None
    owned_by: str | None = None
    protocol: OpenCodeGoModelProtocol = "unknown"
    supported: bool = False


class OpenCodeGoSidecarStatusResponse(DashboardModel):
    enabled: bool
    configured: bool
    status: OpenCodeGoSidecarStatus
    message: str | None = None
    base_url: str
    model_count: int | None = None
    last_checked_at: datetime | None = None


class OpenCodeGoSidecarTestResponse(OpenCodeGoSidecarStatusResponse):
    models: list[OpenCodeGoSidecarModelSummary] = Field(default_factory=list)


class OpenCodeGoSidecarModelsResponse(DashboardModel):
    models: list[OpenCodeGoSidecarModelSummary] = Field(default_factory=list)
