from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from app.modules.shared.schemas import DashboardModel

FreeModelProvider = Literal["openrouter", "orcarouter"]
FreeModelCandidateGroup = Literal["new", "unresolved", "due", "cooldown"]
FreeModelRunStatus = Literal["running", "completed", "cancelled", "expired", "failed"]
FreeModelItemState = Literal["queued", "passed", "failed", "unresolved"]
FreeModelProviderPlanStatus = Literal["ok", "disabled", "missing_api_key", "unreachable", "error"]
# What a rate-limit rejection was EXPLICITLY attributed to by the vendor.
# ``unknown`` is the honest default: a bare 429/402, a generic message or a run
# of 429s does not establish scope.
FreeModelLimitScope = Literal["shared", "model", "unknown"]

FREE_MODEL_PROVIDERS: tuple[FreeModelProvider, ...] = ("openrouter", "orcarouter")


class FreeModelCandidate(DashboardModel):
    provider: FreeModelProvider
    model_id: str
    group: FreeModelCandidateGroup
    owned_by: str | None = None
    # Cross-run memory, when any exists.
    last_verdict: Literal["passed", "failed"] | None = None
    last_verdict_at: datetime | None = None
    failure_streak: int = 0
    cooldown_until: datetime | None = None


class FreeModelProviderPlan(DashboardModel):
    provider: FreeModelProvider
    status: FreeModelProviderPlanStatus
    message: str | None = None
    discovered_count: int = 0
    free_count: int = 0
    already_pinned_count: int = 0
    skipped_selector_count: int = 0
    candidates: list[FreeModelCandidate] = Field(default_factory=list)


class FreeModelDiscoveryPlanResponse(DashboardModel):
    generated_at: datetime
    providers: list[FreeModelProviderPlan] = Field(default_factory=list)
    active_run_id: str | None = None


class FreeModelDiscoverySelection(DashboardModel):
    provider: FreeModelProvider
    model_id: str = Field(min_length=1, max_length=512)


class FreeModelDiscoveryStartRequest(DashboardModel):
    selections: list[FreeModelDiscoverySelection] = Field(min_length=1, max_length=2000)

    @field_validator("selections")
    @classmethod
    def _validate_unique_selections(cls, value: list[FreeModelDiscoverySelection]) -> list[FreeModelDiscoverySelection]:
        seen: set[tuple[str, str]] = set()
        for selection in value:
            key = (selection.provider, selection.model_id.strip().lower())
            if key in seen:
                raise ValueError("Duplicate selections are not allowed")
            seen.add(key)
        return value


class FreeModelDiscoveryRunItemResponse(DashboardModel):
    provider: FreeModelProvider
    model_id: str
    group: FreeModelCandidateGroup
    state: FreeModelItemState
    attempts: int
    # Scope of the last rate-limit rejection, when there was one.
    limit_scope: FreeModelLimitScope | None = None
    next_attempt_at: datetime | None = None
    last_attempt_at: datetime | None = None
    last_http_status: int | None = None
    last_outcome: str | None = None
    content_chars: int | None = None
    content_ok_match: bool | None = None
    reasoning_chars: int | None = None
    added_to_full_models: bool = False
    resolved_at: datetime | None = None


class FreeModelDiscoveryRunCounts(DashboardModel):
    total: int = 0
    queued: int = 0
    passed: int = 0
    failed: int = 0
    unresolved: int = 0
    added: int = 0
    # Split of ``queued`` by whether a request was ever issued. A retried item
    # is not the same as an untouched one, and collapsing them is what made a
    # live run look stopped at "0 resolved".
    awaiting_first_attempt: int = 0
    retrying: int = 0


class FreeModelDiscoveryProviderProgress(DashboardModel):
    provider: FreeModelProvider
    counts: FreeModelDiscoveryRunCounts
    # Current adaptive interval the runner is honouring for this provider.
    current_interval_seconds: float | None = None
    next_probe_at: datetime | None = None
    # Why this provider is waiting, when it is waiting for a stated reason.
    waiting_reason: str | None = None
    # Scope the vendor actually attributed the limit to, never inferred.
    limit_scope: FreeModelLimitScope | None = None
    # True when the whole provider queue is held on one vendor instruction.
    provider_paused: bool = False


class FreeModelDiscoveryRunResponse(DashboardModel):
    id: str
    status: FreeModelRunStatus
    started_at: datetime
    finished_at: datetime | None = None
    deadline_at: datetime
    cancel_requested: bool = False
    pacing_floor_seconds: float
    pacing_cap_seconds: float
    max_attempts_per_item: int
    error_message: str | None = None
    counts: FreeModelDiscoveryRunCounts
    providers: list[FreeModelDiscoveryProviderProgress] = Field(default_factory=list)
    items: list[FreeModelDiscoveryRunItemResponse] = Field(default_factory=list)


class FreeModelDiscoveryRunSummary(DashboardModel):
    id: str
    status: FreeModelRunStatus
    started_at: datetime
    finished_at: datetime | None = None
    counts: FreeModelDiscoveryRunCounts


class FreeModelDiscoveryRunsResponse(DashboardModel):
    active_run_id: str | None = None
    runs: list[FreeModelDiscoveryRunSummary] = Field(default_factory=list)
