from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base
from app.modules.claude_sidecar.usage_queue import ClaudeSidecarUsageRecord
from app.modules.claude_sidecar.usage_repository import ClaudeSidecarUsageRepository

pytestmark = pytest.mark.unit


def _record(request_id: str, total_tokens: int) -> ClaudeSidecarUsageRecord:
    return ClaudeSidecarUsageRecord(
        request_id=request_id,
        timestamp=datetime(2026, 5, 5, 12, 0, tzinfo=timezone.utc),
        auth_index="auth-1",
        source="claude@example.com",
        provider="claude",
        model="claude-sonnet",
        alias="claude",
        endpoint="POST /v1/chat/completions",
        auth_type="oauth",
        input_tokens=1,
        output_tokens=2,
        reasoning_tokens=3,
        cached_tokens=4,
        total_tokens=total_tokens,
        failed=False,
        latency_ms=100,
    )


@pytest.mark.asyncio
async def test_insert_usage_events_skips_duplicate_request_ids() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            repo = ClaudeSidecarUsageRepository(session)

            inserted_first = await repo.insert_usage_events([_record("req_1", 10)])
            inserted_second = await repo.insert_usage_events([_record("req_1", 20), _record("req_2", 30)])
            totals = await repo.usage_totals_by_auth(
                window_start=datetime(2026, 5, 5, 11, 0, tzinfo=timezone.utc),
                window_end=datetime(2026, 5, 5, 13, 0, tzinfo=timezone.utc),
            )

        assert inserted_first == 1
        assert inserted_second == 1
        assert len(totals) == 1
        assert totals[0].total_tokens == 40
        assert totals[0].request_count == 2
    finally:
        await engine.dispose()
