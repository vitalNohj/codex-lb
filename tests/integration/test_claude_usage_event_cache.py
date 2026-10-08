from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, event, update

from app.core.utils.time import to_utc_naive, utcnow
from app.db.models import ClaudeSidecarUsageEvent
from app.db.session import SessionLocal, engine
from app.modules.claude_sidecar.usage_event_cache import get_claude_usage_event_cache
from app.modules.claude_sidecar.usage_queue import ClaudeSidecarUsageRecord
from app.modules.claude_sidecar.usage_repository import ClaudeSidecarUsageRepository

pytestmark = pytest.mark.integration


def _record(
    request_id: str, timestamp: datetime, *, tokens: int = 10, failed: bool = False
) -> ClaudeSidecarUsageRecord:
    return ClaudeSidecarUsageRecord(
        request_id=request_id,
        timestamp=timestamp,
        auth_index="1",
        source="user@example.com",
        provider="claude",
        model="claude-opus",
        alias=None,
        endpoint=None,
        auth_type="oauth",
        input_tokens=tokens,
        output_tokens=0,
        reasoning_tokens=0,
        cached_tokens=0,
        total_tokens=tokens,
        failed=failed,
        latency_ms=None,
    )


async def _insert(*records: ClaudeSidecarUsageRecord) -> None:
    async with SessionLocal() as session:
        await ClaudeSidecarUsageRepository(session).insert_usage_events(list(records))


async def _read(since: datetime) -> list[tuple[str | None, datetime, int, bool]]:
    async with SessionLocal() as session:
        events = await ClaudeSidecarUsageRepository(session).list_estimate_events_since(since)
    return [(event.auth_index, event.timestamp, event.total_tokens, event.failed) for event in events]


class _EventRowLoads:
    """Count the statements that read event rows (not the fingerprint)."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    def __enter__(self) -> _EventRowLoads:
        event.listen(engine.sync_engine, "before_cursor_execute", self._capture)
        return self

    def __exit__(self, *args: object) -> None:
        event.remove(engine.sync_engine, "before_cursor_execute", self._capture)

    def _capture(self, conn, cursor, statement, parameters, context, executemany) -> None:
        # Row reads select columns; the fingerprint only aggregates them.
        if "claude_sidecar_usage_events.total_tokens" in statement and not statement.lstrip().startswith(
            "SELECT count("
        ):
            self.statements.append(" ".join(statement.split()))

    @property
    def full_loads(self) -> list[str]:
        return [statement for statement in self.statements if "claude_sidecar_usage_events.id >" not in statement]

    @property
    def incremental_loads(self) -> list[str]:
        return [statement for statement in self.statements if "claude_sidecar_usage_events.id >" in statement]


@pytest.mark.asyncio
async def test_estimate_events_read_window_in_timestamp_order(db_setup):
    now = utcnow()
    await _insert(
        _record("late", now - timedelta(minutes=1), tokens=3),
        _record("old", now - timedelta(days=8), tokens=1),
        _record("early", now - timedelta(hours=2), tokens=2, failed=True),
    )

    events = await _read(now - timedelta(days=7))

    assert [tokens for _, _, tokens, _ in events] == [2, 3]
    assert [failed for _, _, _, failed in events] == [True, False]
    assert all(timestamp.tzinfo is timezone.utc for _, timestamp, _, _ in events)
    assert events[0][1] == (now - timedelta(hours=2)).replace(tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_estimate_events_fetch_only_appended_rows(db_setup):
    now = utcnow()
    await _insert(_record("first", now - timedelta(hours=1), tokens=1))
    assert [tokens for _, _, tokens, _ in await _read(now - timedelta(days=7))] == [1]

    await _insert(
        _record("second", now - timedelta(minutes=5), tokens=2),
        # A late-arriving row older than the cached rows must still slot in by time.
        _record("backfill", now - timedelta(hours=3), tokens=3),
    )
    with _EventRowLoads() as loads:
        events = await _read(now - timedelta(days=7))

    assert [tokens for _, _, tokens, _ in events] == [3, 1, 2]
    assert loads.full_loads == []
    assert len(loads.incremental_loads) == 1


@pytest.mark.asyncio
async def test_estimate_events_reuse_cache_for_slightly_earlier_since(db_setup):
    now = utcnow()
    await _insert(
        _record("edge", now - timedelta(days=7, minutes=2), tokens=1),
        _record("inside", now - timedelta(hours=1), tokens=2),
    )
    assert [tokens for _, _, tokens, _ in await _read(now - timedelta(days=7))] == [2]

    with _EventRowLoads() as loads:
        events = await _read(now - timedelta(days=7, minutes=5))

    assert [tokens for _, _, tokens, _ in events] == [1, 2]
    assert loads.statements == []


@pytest.mark.asyncio
async def test_estimate_events_reload_after_rows_disappear(db_setup):
    now = utcnow()
    await _insert(
        _record("keep", now - timedelta(hours=2), tokens=1),
        _record("gone", now - timedelta(hours=1), tokens=2),
    )
    assert [tokens for _, _, tokens, _ in await _read(now - timedelta(days=7))] == [1, 2]

    async with SessionLocal() as session:
        await session.execute(delete(ClaudeSidecarUsageEvent).where(ClaudeSidecarUsageEvent.request_id == "gone"))
        await session.commit()
    with _EventRowLoads() as loads:
        events = await _read(now - timedelta(days=7))

    assert [tokens for _, _, tokens, _ in events] == [1]
    assert len(loads.full_loads) == 1


@pytest.mark.asyncio
async def test_estimate_events_clear_forces_full_reload(db_setup):
    now = utcnow()
    await _insert(_record("only", now - timedelta(hours=1), tokens=4))
    await _read(now - timedelta(days=7))

    get_claude_usage_event_cache().clear()
    with _EventRowLoads() as loads:
        events = await _read(now - timedelta(days=7))

    assert [tokens for _, _, tokens, _ in events] == [4]
    assert len(loads.full_loads) == 1


@pytest.mark.asyncio
async def test_estimate_events_reload_when_same_count_has_lower_max_id(db_setup):
    now = utcnow()
    await _insert(
        _record("a", now - timedelta(hours=3), tokens=1),
        _record("b", now - timedelta(hours=2), tokens=2),
        _record("c", now - timedelta(hours=1), tokens=3),
    )
    async with SessionLocal() as session:
        await session.execute(delete(ClaudeSidecarUsageEvent).where(ClaudeSidecarUsageEvent.request_id == "a"))
        await session.commit()
    assert [tokens for _, _, tokens, _ in await _read(now - timedelta(days=7))] == [2, 3]

    # Same row count, lower max id: what a restored backup looks like. Row "c"
    # moves to the freed lower id and carries different usage.
    async with SessionLocal() as session:
        first_id = (
            await session.execute(
                ClaudeSidecarUsageEvent.__table__.select()
                .with_only_columns(ClaudeSidecarUsageEvent.id)
                .where(ClaudeSidecarUsageEvent.request_id == "b")
            )
        ).scalar_one() - 1
        await session.execute(
            update(ClaudeSidecarUsageEvent)
            .where(ClaudeSidecarUsageEvent.request_id == "c")
            .values(id=first_id, total_tokens=9)
        )
        await session.commit()
    with _EventRowLoads() as loads:
        events = await _read(now - timedelta(days=7))

    assert [tokens for _, _, tokens, _ in events] == [2, 9]
    assert len(loads.full_loads) == 1


@pytest.mark.asyncio
async def test_estimate_events_merge_many_late_rows_in_order(db_setup):
    now = utcnow()
    await _insert(*(_record(f"cached-{i}", now - timedelta(minutes=10 * i), tokens=i) for i in range(1, 6)))
    await _read(now - timedelta(days=7))

    late = [_record(f"late-{i}", now - timedelta(minutes=10 * i + 5), tokens=100 + i) for i in range(1, 6)]
    await _insert(*late)
    with _EventRowLoads() as loads:
        events = await _read(now - timedelta(days=7))

    timestamps = [timestamp for _, timestamp, _, _ in events]
    assert timestamps == sorted(timestamps)
    assert len(events) == 10
    assert [tokens for _, _, tokens, _ in events][:2] == [105, 5]
    assert loads.full_loads == []


@pytest.mark.asyncio
async def test_estimate_events_reload_when_newest_row_is_replaced_at_same_id(db_setup):
    now = utcnow()
    await _insert(
        _record("a", now - timedelta(hours=2), tokens=1),
        _record("b", now - timedelta(hours=1), tokens=2),
    )
    assert [tokens for _, _, tokens, _ in await _read(now - timedelta(days=7))] == [1, 2]

    # Same count, same max id, different row: SQLite can hand a deleted
    # newest id to the next insert.
    async with SessionLocal() as session:
        await session.execute(
            update(ClaudeSidecarUsageEvent)
            .where(ClaudeSidecarUsageEvent.request_id == "b")
            .values(request_id="b2", total_tokens=7, timestamp=to_utc_naive(now - timedelta(minutes=30)))
        )
        await session.commit()
    with _EventRowLoads() as loads:
        events = await _read(now - timedelta(days=7))

    assert [tokens for _, _, tokens, _ in events] == [1, 7]
    assert len(loads.full_loads) == 1
