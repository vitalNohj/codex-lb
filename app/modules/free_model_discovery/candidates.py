"""Pure candidate selection and grouping for free-model discovery.

No I/O here. The service fetches provider lists and persisted state and hands
them to these functions so the rules are unit-testable in isolation.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.core.clients.claude_sidecar import SidecarModel
from app.db.models import FreeModelProbeState
from app.modules.free_model_discovery.schemas import FreeModelCandidate, FreeModelCandidateGroup, FreeModelProvider

_FREE_MARKER = "free"


def is_free_model_id(model_id: str) -> bool:
    """Substring match: catches ``:free``, ``-free`` and ``/free`` shapes.

    Checked against the live OpenRouter/OrcaRouter lists, the bare substring
    hits exactly the free ids and no paid lookalikes.
    """

    return _FREE_MARKER in model_id.lower()


def is_router_selector(model_id: str) -> bool:
    """A last path segment that is exactly ``free`` is a router auto-selector
    (``orcarouter/free``), not a concrete model. Selectors are left to manual
    pinning: a verdict on one says something answered, not that a specific
    model is live.
    """

    last_segment = model_id.strip().lower().rsplit("/", 1)[-1]
    return last_segment == _FREE_MARKER


def normalize_model_key(model_id: str) -> str:
    return model_id.strip().lower()


@dataclass(frozen=True, slots=True)
class CandidateSplit:
    candidates: list[SidecarModel]
    discovered_count: int
    free_count: int
    already_pinned_count: int
    skipped_selector_count: int


def split_candidates(models: Iterable[SidecarModel], pinned_keys: set[str]) -> CandidateSplit:
    """Keep concrete free ids that are not pinned by any sidecar."""

    discovered = 0
    free = 0
    pinned = 0
    selectors = 0
    candidates: list[SidecarModel] = []
    seen: set[str] = set()
    for model in models:
        discovered += 1
        model_id = model.id.strip()
        if not model_id or not is_free_model_id(model_id):
            continue
        free += 1
        key = normalize_model_key(model_id)
        if key in seen:
            continue
        seen.add(key)
        if is_router_selector(model_id):
            selectors += 1
            continue
        if key in pinned_keys:
            pinned += 1
            continue
        candidates.append(model)
    return CandidateSplit(
        candidates=candidates,
        discovered_count=discovered,
        free_count=free,
        already_pinned_count=pinned,
        skipped_selector_count=selectors,
    )


def classify_group(
    *,
    state: FreeModelProbeState | None,
    unresolved_last_run: bool,
    now: datetime,
) -> FreeModelCandidateGroup:
    """Precedence: verdict memory wins over the last run's unresolved marker.

    A failed verdict whose cooldown is still active is ``cooldown``; any other
    prior verdict (failed past cooldown, or passed but no longer pinned) is
    ``due``. With no verdict memory, an item the last run could not resolve is
    ``unresolved``; otherwise it has never been tested and is ``new``.
    """

    if state is not None:
        if state.last_verdict == "failed" and state.cooldown_until is not None and state.cooldown_until > now:
            return "cooldown"
        return "due"
    if unresolved_last_run:
        return "unresolved"
    return "new"


def verdict_of(state: FreeModelProbeState | None) -> Literal["passed", "failed"] | None:
    if state is None:
        return None
    if state.last_verdict == "passed":
        return "passed"
    if state.last_verdict == "failed":
        return "failed"
    return None


def build_candidates(
    *,
    provider: FreeModelProvider,
    models: Iterable[SidecarModel],
    states: Mapping[str, FreeModelProbeState],
    unresolved_keys: set[str],
    now: datetime,
) -> list[FreeModelCandidate]:
    candidates: list[FreeModelCandidate] = []
    for model in models:
        key = normalize_model_key(model.id)
        state = states.get(key)
        group = classify_group(state=state, unresolved_last_run=key in unresolved_keys, now=now)
        candidates.append(
            FreeModelCandidate(
                provider=provider,
                model_id=model.id.strip(),
                group=group,
                owned_by=model.owned_by,
                last_verdict=verdict_of(state),
                last_verdict_at=state.last_verdict_at if state is not None else None,
                failure_streak=state.failure_streak if state is not None else 0,
                cooldown_until=state.cooldown_until if state is not None else None,
            )
        )
    return candidates
