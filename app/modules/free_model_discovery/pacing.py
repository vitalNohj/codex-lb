"""Pacing and cooldown arithmetic. Pure functions, no I/O.

Two independent timescales:

* Intra-run pacing (``ProviderPacer``): one probe at a time per provider with
  an adaptive minimum interval. A 429 honours the router's retry hint or
  doubles the interval up to the cap. A streak of clean responses decays the
  interval back toward the floor. This is the rate-limit defence.

* Cross-run cooldown (``cooldown_for_failure_streak``): only a real ``failed``
  verdict escalates, on a coarse schedule, so known-dead ids stop consuming
  probes on every run. Inconclusive outcomes never escalate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

DEFAULT_PACING_FLOOR_SECONDS = 20.0
DEFAULT_PACING_CAP_SECONDS = 600.0
DEFAULT_MAX_ATTEMPTS_PER_ITEM = 12
DEFAULT_RUN_WALL_CLOCK = timedelta(hours=24)

# Clean responses in a row before the interval halves back toward the floor.
_DECAY_STREAK = 3

_COOLDOWN_SCHEDULE: tuple[timedelta, ...] = (
    timedelta(hours=1),
    timedelta(hours=6),
    timedelta(days=1),
    timedelta(days=3),
    timedelta(days=7),
)


def cooldown_for_failure_streak(failure_streak: int) -> timedelta:
    """1h, 6h, 24h, 3d, then 7d for every further consecutive failure."""

    if failure_streak <= 0:
        return _COOLDOWN_SCHEDULE[0]
    index = min(failure_streak, len(_COOLDOWN_SCHEDULE)) - 1
    return _COOLDOWN_SCHEDULE[index]


@dataclass(slots=True)
class ProviderPacer:
    floor_seconds: float
    cap_seconds: float
    current_seconds: float = 0.0
    clean_streak: int = 0

    def __post_init__(self) -> None:
        if self.floor_seconds <= 0:
            raise ValueError("floor_seconds must be positive")
        if self.cap_seconds < self.floor_seconds:
            raise ValueError("cap_seconds must be >= floor_seconds")
        if self.current_seconds <= 0:
            self.current_seconds = self.floor_seconds

    def on_rate_limited(self, retry_after_seconds: float | None) -> float:
        """Return the wait before the next probe on this provider."""

        self.clean_streak = 0
        if retry_after_seconds is not None and retry_after_seconds > 0:
            self.current_seconds = min(self.cap_seconds, max(self.floor_seconds, retry_after_seconds))
        else:
            self.current_seconds = min(self.cap_seconds, self.current_seconds * 2)
        return self.current_seconds

    def on_inconclusive(self) -> float:
        """Non-429 inconclusive: hold the current pace, do not decay."""

        self.clean_streak = 0
        return self.current_seconds

    def on_verdict(self) -> float:
        """Clean 200 (either verdict): decay after a short streak."""

        self.clean_streak += 1
        if self.clean_streak >= _DECAY_STREAK:
            self.clean_streak = 0
            self.current_seconds = max(self.floor_seconds, self.current_seconds / 2)
        return self.current_seconds
