"""Dashboard I/O schemas for the OpenCode Go quota read.

The published contract is quota-contract.md (task codexlb-opencode-go-quota-r1).
Two independent axes are modelled deliberately:

- ``status`` answers "do we have data, and how good is it".
- ``scope`` answers "what are the numbers about".

Collapsing them would make "we could not read your usage" indistinguishable from
"you have no quota left", which is the specific failure this schema exists to
prevent. Only ``ok`` and ``stale`` ever carry windows; every other status carries
an empty list, which means **unknown** - never zero and never full.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.modules.shared.schemas import DashboardModel

OpenCodeGoQuotaStatus = Literal[
    "disabled",
    "not_configured",
    "ok",
    "stale",
    "unauthorized",
    "rate_limited",
    "unavailable",
]
OpenCodeGoQuotaScope = Literal["unknown", "account", "per_model"]
OpenCodeGoWindowKey = Literal["five_hour", "weekly", "monthly"]
OpenCodeGoWindowStatus = Literal["ok", "rate_limited", "unknown"]


class OpenCodeGoQuotaWindowResponse(DashboardModel):
    """One usage window.

    ``percentUsed`` is 0..100 in the *used* direction. There is deliberately no
    ``percentRemaining``: the used direction rests on a single-source inference,
    and publishing a derived remaining value would lend it a false second
    confirmation. ``null`` means unknown, not zero.
    """

    key: OpenCodeGoWindowKey
    # Upstream's own key ("rolling" | "weekly" | "monthly"), preserved verbatim
    # so the rolling -> five_hour mapping stays auditable against a future
    # authenticated capture.
    upstream_key: str
    status: OpenCodeGoWindowStatus
    percent_used: float | None = None
    resets_at: datetime | None = None
    limit_reached: bool | None = None


class OpenCodeGoQuotaResponse(DashboardModel):
    """Result of a dashboard quota read. Always HTTP 200; ``status`` carries the outcome."""

    status: OpenCodeGoQuotaStatus
    # Upstream sends three unlabelled windows with no model dimension, so scope
    # is reported as "unknown" rather than mislabelled as an account total.
    scope: OpenCodeGoQuotaScope = "unknown"
    message: str | None = None
    # When the windows were obtained upstream (may predate ``refreshedAt`` when stale).
    checked_at: datetime | None = None
    # When this answer was produced.
    refreshed_at: datetime | None = None
    stale: bool = False
    stale_reason: str | None = None
    model_breakdown_available: bool = False
    # Always empty while ``modelBreakdownAvailable`` is false. No per-model
    # window is ever manufactured from the documented dollar caps.
    models: list[str] = Field(default_factory=list)
    # Ordered five_hour, weekly, monthly. A window upstream omitted or sent
    # malformed is absent, so consumers must handle 0-3 entries.
    windows: list[OpenCodeGoQuotaWindowResponse] = Field(default_factory=list)
