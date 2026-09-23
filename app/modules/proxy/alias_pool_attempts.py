"""Alias pool attempt primitives shared by the failover loop and the dispatchers.

This module is a leaf on purpose: the pool-capable dispatchers import it to
report an open-time failure and to attribute their request-log row, and the
failover loop in ``alias_pool_dispatch.py`` imports it to classify that
failure and to consult the cooldown registry. Neither side imports the other.

Three things live here:

* :class:`ChatRequestAttribution` - what a dispatcher writes into the request
  log row for ``model`` / ``upstream_model`` / ``pool_attempts`` /
  ``latency_queue_ms``. The client-facing alias is ``model``; the target that
  actually served the request is ``upstream_model``.
* :class:`PoolTargetFailed` - raised by a dispatcher *instead of* settling and
  logging when its upstream open fails in a retryable way and the loop said a
  later target may still be tried. It carries a closure that produces the
  client-facing error response, so a terminal failure is still rendered by the
  provider that produced it.
* The cooldown registry - process-local, keyed by target string.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Final

from fastapi import Response

from app.modules.free_model_discovery.limits import parse_retry_after

logger = logging.getLogger(__name__)

POOL_ATTEMPTS_HEADER: Final = "X-Codex-LB-Pool-Attempts"

RETRYABLE_UPSTREAM_STATUSES: Final[frozenset[int]] = frozenset(
    {401, 402, 403, 408, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524, 525, 526}
)

PAYMENT_REQUIRED_COOLDOWN_SECONDS: Final = 30 * 60.0
DEFAULT_COOLDOWN_SECONDS: Final = 60.0
MAX_RETRY_AFTER_COOLDOWN_SECONDS: Final = 60 * 60.0


@dataclass(frozen=True, slots=True)
class ChatRequestAttribution:
    """How a sidecar dispatcher labels its request-log row.

    ``model`` is what the client asked for and what API-key limits key on; it
    is the alias for aliased requests. ``upstream_model`` is the target that
    was dispatched, ``None`` when it equals ``model``. ``pool_attempts`` and
    ``queue_ms`` are set only by the failover loop.
    """

    model: str
    upstream_model: str | None = None
    pool_attempts: int | None = None
    queue_ms: int | None = None

    @classmethod
    def direct(cls, model: str) -> ChatRequestAttribution:
        return cls(model=model)

    @classmethod
    def aliased(cls, *, alias: str, target: str) -> ChatRequestAttribution:
        return cls(model=alias, upstream_model=None if target == alias else target)


@dataclass(frozen=True, slots=True)
class RetryableUpstreamFailure:
    """Why an attempt is being abandoned, as the cooldown registry records it."""

    status_code: int
    message: str
    retry_after_seconds: float | None = None

    def cooldown_seconds(self) -> float:
        if self.status_code == 402:
            return PAYMENT_REQUIRED_COOLDOWN_SECONDS
        if self.status_code == 429 and self.retry_after_seconds is not None:
            return min(self.retry_after_seconds, MAX_RETRY_AFTER_COOLDOWN_SECONDS)
        return DEFAULT_COOLDOWN_SECONDS


class PoolTargetFailed(Exception):
    """A pool attempt failed before any byte reached the client.

    Raised by a pool-capable dispatcher in place of its normal error path when
    ``allow_failover`` was set. ``render`` performs that normal error path
    (settle, log, build the client response) and is awaited by the loop only
    when the failure turns out to be terminal, so the settlement happens
    exactly once and only for the attempt that ends the request.
    """

    def __init__(
        self,
        failure: RetryableUpstreamFailure,
        *,
        render: Callable[[], Awaitable[Response]],
    ) -> None:
        super().__init__(failure.message)
        self.failure = failure
        self.render = render


def is_retryable_upstream_status(status_code: int) -> bool:
    return status_code in RETRYABLE_UPSTREAM_STATUSES


def retryable_failure_from_error(
    *,
    status_code: int,
    message: str,
    headers: Mapping[str, str] | None,
) -> RetryableUpstreamFailure | None:
    """Classify a sidecar error; ``None`` means "return it to the client as is"."""

    if not is_retryable_upstream_status(status_code):
        return None
    retry_after = None
    if status_code == 429 and headers:
        for key, value in headers.items():
            if key.lower() == "retry-after":
                retry_after = parse_retry_after(value)
                break
    return RetryableUpstreamFailure(status_code=status_code, message=message, retry_after_seconds=retry_after)


@dataclass(frozen=True, slots=True)
class TargetCooldown:
    until_monotonic: float
    until: datetime
    last_status: int
    last_error: str


@dataclass(frozen=True, slots=True)
class TargetHealth:
    state: str  # "healthy" | "cooling"
    until: datetime | None
    last_status: int | None
    last_error: str | None


class AliasPoolCooldownRegistry:
    """Process-local cooldowns keyed by target string.

    Keyed by the target, not the provider: ``orcarouter/z-ai/glm-5.3`` cooling
    must not stop ``orcarouter/auto``. Entries expire lazily on read. A
    multi-replica deployment learns a cooldown per replica, which costs one
    wasted upstream round-trip per replica per window; acceptable for a
    failover cache and far simpler than sharing it.
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: dict[str, TargetCooldown] = {}

    def record_failure(self, target: str, failure: RetryableUpstreamFailure) -> TargetCooldown:
        seconds = failure.cooldown_seconds()
        now_monotonic = self._clock()
        entry = TargetCooldown(
            until_monotonic=now_monotonic + seconds,
            until=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=seconds),
            last_status=failure.status_code,
            last_error=failure.message[:512],
        )
        with self._lock:
            self._entries[target] = entry
        return entry

    def record_success(self, target: str) -> None:
        with self._lock:
            self._entries.pop(target, None)

    def cooldown_for(self, target: str) -> TargetCooldown | None:
        with self._lock:
            entry = self._entries.get(target)
            if entry is None:
                return None
            if entry.until_monotonic <= self._clock():
                del self._entries[target]
                return None
            return entry

    def order_targets(self, targets: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Split ``targets`` into ``(ready, cooling)``.

        ``ready`` keeps pool order. ``cooling`` is sorted soonest-to-expire
        first so a caller with nothing ready can still try the best candidate
        instead of failing the request on a cooldown alone.
        """

        ready: list[str] = []
        cooling: list[tuple[float, int, str]] = []
        for index, target in enumerate(targets):
            entry = self.cooldown_for(target)
            if entry is None:
                ready.append(target)
            else:
                cooling.append((entry.until_monotonic, index, target))
        cooling.sort()
        return tuple(ready), tuple(target for _, _, target in cooling)

    def health(self, target: str) -> TargetHealth:
        entry = self.cooldown_for(target)
        if entry is None:
            return TargetHealth(state="healthy", until=None, last_status=None, last_error=None)
        return TargetHealth(
            state="cooling",
            until=entry.until,
            last_status=entry.last_status,
            last_error=entry.last_error,
        )

    def retain(self, targets: set[str]) -> None:
        """Drop entries for targets no longer configured anywhere."""

        with self._lock:
            for target in list(self._entries):
                if target not in targets:
                    del self._entries[target]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


_registry = AliasPoolCooldownRegistry()


def get_alias_pool_cooldowns() -> AliasPoolCooldownRegistry:
    return _registry


def reset_alias_pool_cooldowns() -> None:
    """Test hook: forget every cooldown."""

    _registry.clear()
