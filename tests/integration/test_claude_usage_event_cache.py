from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, event

from app.core.utils.time import utcnow
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
        if "claude_sidecar_usage_events.total_tokens" in statement:
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
