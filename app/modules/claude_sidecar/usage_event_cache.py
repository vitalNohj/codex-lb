"""Process-wide cache of the Claude sidecar usage events behind the quota estimates.

Every surface that shows Claude remaining-quota estimates (dashboard overview,
accounts list, sidecar quota panel, pooled OAuth usage) reads the full
seven-day event history. Loading those rows per request materialized tens of
thousands of ORM entities on the event loop and cost seconds per call, on
every dashboard refresh.

``claude_sidecar_usage_events`` is append-only: the usage collector inserts
rows and nothing updates them. The cache keeps the window's events in memory
as compact records and, on each read, pulls only rows above its id watermark.

The watermark is exact only while no row is updated or deleted, so the cache
also records the trigger-maintained mutation generation and reloads in full
whenever it moves. A ``count``/``max(id)`` check of the window, read in the
same transaction, additionally catches a store swapped underneath the process
(for example a restored backup) and any gap the watermark reasoning missed.
Without the triggers (PostgreSQL, or a store the migration never reached)
nothing vouches for the watermark, so every read loads the window in full.
"""

from __future__ import annotations

import asyncio
import bisect
import heapq
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.utils.time import to_utc_naive
from app.db.models import CLAUDE_SIDECAR_USAGE_EVENT_MUTATION_TRIGGERS, ClaudeSidecarUsageEvent

# Rows kept below the requested window start. Concurrent readers each compute
# their own ``now``, so a reader arriving a moment behind the last sync asks
# for a slightly earlier ``since``; the slack lets it reuse the cached window
# instead of forcing a full reload.
_WINDOW_SLACK = timedelta(minutes=15)


@dataclass(frozen=True, slots=True)
class ClaudeUsageEstimateEvent:
    """The columns the quota estimates read, with an aware UTC timestamp."""

    id: int
    timestamp: datetime
    auth_index: str | None
    source: str | None
    total_tokens: int
    failed: bool


@dataclass(slots=True)
class _WindowState:
    database_key: str
    generation: int | None
    since: datetime
    max_id: int
    events: list[ClaudeUsageEstimateEvent] = field(default_factory=list)
    # Naive UTC sort keys parallel to ``events`` so pruning and slicing by
    # ``since`` stay a bisect instead of a scan.
    sort_keys: list[tuple[datetime, int]] = field(default_factory=list)


class ClaudeUsageEventCache:
    def __init__(self) -> None:
        self._state: _WindowState | None = None
        self._lock: asyncio.Lock | None = None
        self._lock_loop: asyncio.AbstractEventLoop | None = None

    def clear(self) -> None:
        self._state = None

    async def events_since(self, session: AsyncSession, since: datetime) -> list[ClaudeUsageEstimateEvent]:
        """Return every event with ``timestamp >= since``, ordered by (timestamp, id)."""
        since_naive = to_utc_naive(since)
        async with self._get_lock():
            state = await self._sync(session, since_naive)
        start = bisect.bisect_left(state.sort_keys, (since_naive, -1))
        return state.events[start:]

    def _get_lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if self._lock is None or self._lock_loop is not loop:
            self._lock = asyncio.Lock()
            self._lock_loop = loop
        return self._lock

    async def _sync(self, session: AsyncSession, since: datetime) -> _WindowState:
        database_key = str(session.get_bind().engine.url)
        # One snapshot: the fingerprint and any row fetch below run in the
        # session's transaction, so they agree with each other.
        count, max_id = (
            await session.execute(
                select(func.count(ClaudeSidecarUsageEvent.id), func.max(ClaudeSidecarUsageEvent.id)).where(
                    ClaudeSidecarUsageEvent.timestamp >= since
                )
            )
        ).one()
        count = int(count or 0)
        max_id = int(max_id or 0)
        generation = await _mutation_generation(session)

        state = self._state
        if (
            state is None
            or generation is None
            or state.generation != generation
            or state.database_key != database_key
            or since < state.since
        ):
            state = await self._load(
                session, database_key, generation, since - _WINDOW_SLACK, min_id=None, max_id=max_id
            )
        else:
            if max_id > state.max_id:
                fresh = await self._load(
                    session, database_key, generation, state.since, min_id=state.max_id, max_id=max_id
                )
                _merge(state, fresh)
            _prune(state, since - _WINDOW_SLACK)
            if not _matches_fingerprint(state, since, count=count, max_id=max_id):
                state = await self._load(
                    session, database_key, generation, since - _WINDOW_SLACK, min_id=None, max_id=max_id
                )
        self._state = state
        return state

    async def _load(
        self,
        session: AsyncSession,
        database_key: str,
        generation: int | None,
        since: datetime,
        *,
        min_id: int | None,
        max_id: int,
    ) -> _WindowState:
        statement = select(
            ClaudeSidecarUsageEvent.id,
            ClaudeSidecarUsageEvent.timestamp,
            ClaudeSidecarUsageEvent.auth_index,
            ClaudeSidecarUsageEvent.source,
            ClaudeSidecarUsageEvent.total_tokens,
            ClaudeSidecarUsageEvent.failed,
        ).where(ClaudeSidecarUsageEvent.timestamp >= since, ClaudeSidecarUsageEvent.id <= max_id)
        if min_id is not None:
            statement = statement.where(ClaudeSidecarUsageEvent.id > min_id)
        rows = (await session.execute(statement)).all()
        state = _WindowState(database_key=database_key, generation=generation, since=since, max_id=max_id)
        records = sorted(
            (
                (to_utc_naive(timestamp), event_id),
                ClaudeUsageEstimateEvent(
                    id=event_id,
                    timestamp=to_utc_naive(timestamp).replace(tzinfo=timezone.utc),
                    auth_index=auth_index,
                    source=source,
                    total_tokens=int(total_tokens or 0),
                    failed=bool(failed),
                ),
            )
            for event_id, timestamp, auth_index, source, total_tokens, failed in rows
        )
        state.sort_keys = [key for key, _ in records]
        state.events = [event for _, event in records]
        return state


async def _mutation_generation(session: AsyncSession) -> int | None:
    """Return the trigger-maintained mutation generation, read in the session's transaction.

    ``None`` when it cannot be trusted to have seen every UPDATE and DELETE:
    not SQLite, or the state row or either trigger is missing.
    """
    if session.get_bind().dialect.name != "sqlite":
        return None
    placeholders = ",".join(f":t{index}" for index in range(len(CLAUDE_SIDECAR_USAGE_EVENT_MUTATION_TRIGGERS)))
    trigger_count = (
        await session.execute(
            text(
                "SELECT count(*) FROM sqlite_master WHERE type = 'trigger' "
                f"AND tbl_name = 'claude_sidecar_usage_events' AND name IN ({placeholders})"
            ),
            {f"t{index}": name for index, name in enumerate(CLAUDE_SIDECAR_USAGE_EVENT_MUTATION_TRIGGERS)},
        )
    ).scalar_one()
    if trigger_count != len(CLAUDE_SIDECAR_USAGE_EVENT_MUTATION_TRIGGERS):
        return None
    generation = (
        await session.execute(text("SELECT generation FROM claude_sidecar_usage_event_mutation_state WHERE id = 1"))
    ).scalar_one_or_none()
    return None if generation is None else int(generation)


def _merge(state: _WindowState, fresh: _WindowState) -> None:
    """Fold newly inserted rows into the window, keeping (timestamp, id) order.

    New rows almost always sort after everything cached, so the common case is
    an append. When a late-arriving row sorts inside the cached range, both
    sorted sequences are merged in one linear pass rather than inserting row
    by row, which would shift the cached lists once per late row.
    """
    if fresh.sort_keys:
        if not state.sort_keys or fresh.sort_keys[0] > state.sort_keys[-1]:
            state.sort_keys.extend(fresh.sort_keys)
            state.events.extend(fresh.events)
        else:
            merged = list(
                heapq.merge(
                    zip(state.sort_keys, state.events, strict=True),
                    zip(fresh.sort_keys, fresh.events, strict=True),
                    key=lambda pair: pair[0],
                )
            )
            state.sort_keys = [key for key, _ in merged]
            state.events = [event for _, event in merged]
    state.max_id = fresh.max_id


def _prune(state: _WindowState, since: datetime) -> None:
    if since <= state.since:
        return
    start = bisect.bisect_left(state.sort_keys, (since, -1))
    if start:
        del state.sort_keys[:start]
        del state.events[:start]
    state.since = since


def _matches_fingerprint(state: _WindowState, since: datetime, *, count: int, max_id: int) -> bool:
    """Whether the cached rows at or after ``since`` match the database window.

    Count alone misses a swapped database holding the same number of rows (for
    example a restored backup), so the largest cached id must match too.
    """
    start = bisect.bisect_left(state.sort_keys, (since, -1))
    if len(state.sort_keys) - start != count:
        return False
    cached_max_id = max((event_id for _, event_id in state.sort_keys[start:]), default=0)
    return cached_max_id == max_id


_cache = ClaudeUsageEventCache()


def get_claude_usage_event_cache() -> ClaudeUsageEventCache:
    return _cache
