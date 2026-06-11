from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import case, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ClaudeSidecarUsageEvent
from app.modules.claude_sidecar.usage_queue import ClaudeSidecarUsageRecord


@dataclass(frozen=True, slots=True)
class ClaudeSidecarUsageTotals:
    auth_index: str | None
    source: str | None
    total_tokens: int
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    cached_tokens: int
    request_count: int
    failed_count: int
    first_timestamp: datetime | None
    last_timestamp: datetime | None


class ClaudeSidecarUsageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert_usage_events(self, records: Sequence[ClaudeSidecarUsageRecord]) -> int:
        if not records:
            return 0
        request_ids = [record.request_id for record in records]
        existing = set(
            (
                await self._session.execute(
                    select(ClaudeSidecarUsageEvent.request_id).where(
                        ClaudeSidecarUsageEvent.request_id.in_(request_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        inserted = 0
        for record in records:
            if record.request_id in existing:
                continue
            self._session.add(
                ClaudeSidecarUsageEvent(
                    request_id=record.request_id,
                    timestamp=record.timestamp,
                    auth_index=record.auth_index,
                    source=record.source,
                    provider=record.provider,
                    model=record.model,
                    alias=record.alias,
                    endpoint=record.endpoint,
                    auth_type=record.auth_type,
                    input_tokens=record.input_tokens,
                    output_tokens=record.output_tokens,
                    reasoning_tokens=record.reasoning_tokens,
                    cached_tokens=record.cached_tokens,
                    total_tokens=record.total_tokens,
                    failed=record.failed,
                    latency_ms=record.latency_ms,
                )
            )
            existing.add(record.request_id)
            inserted += 1
        if inserted:
            await self._session.commit()
        return inserted

    async def usage_totals_by_auth(
        self,
        *,
        window_start: datetime,
        window_end: datetime,
    ) -> list[ClaudeSidecarUsageTotals]:
        rows = (
            await self._session.execute(
                select(
                    ClaudeSidecarUsageEvent.auth_index,
                    ClaudeSidecarUsageEvent.source,
                    func.coalesce(func.sum(ClaudeSidecarUsageEvent.total_tokens), 0),
                    func.coalesce(func.sum(ClaudeSidecarUsageEvent.input_tokens), 0),
                    func.coalesce(func.sum(ClaudeSidecarUsageEvent.output_tokens), 0),
                    func.coalesce(func.sum(ClaudeSidecarUsageEvent.reasoning_tokens), 0),
                    func.coalesce(func.sum(ClaudeSidecarUsageEvent.cached_tokens), 0),
                    func.count(ClaudeSidecarUsageEvent.id),
                    func.coalesce(
                        func.sum(
                            case(
                                (ClaudeSidecarUsageEvent.failed.is_(True), 1),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                    func.min(ClaudeSidecarUsageEvent.timestamp),
                    func.max(ClaudeSidecarUsageEvent.timestamp),
                )
                .where(
                    ClaudeSidecarUsageEvent.timestamp >= window_start,
                    ClaudeSidecarUsageEvent.timestamp < window_end,
                )
                .group_by(ClaudeSidecarUsageEvent.auth_index, ClaudeSidecarUsageEvent.source)
            )
        ).all()
        totals: list[ClaudeSidecarUsageTotals] = []
        for row in rows:
            totals.append(
                ClaudeSidecarUsageTotals(
                    auth_index=row[0],
                    source=row[1],
                    total_tokens=int(row[2] or 0),
                    input_tokens=int(row[3] or 0),
                    output_tokens=int(row[4] or 0),
                    reasoning_tokens=int(row[5] or 0),
                    cached_tokens=int(row[6] or 0),
                    request_count=int(row[7] or 0),
                    failed_count=int(row[8] or 0),
                    first_timestamp=row[9],
                    last_timestamp=row[10],
                )
            )
        return totals

    async def latest_event_by_auth(self) -> dict[tuple[str | None, str | None], datetime]:
        rows = (
            await self._session.execute(
                select(
                    ClaudeSidecarUsageEvent.auth_index,
                    ClaudeSidecarUsageEvent.source,
                    func.max(ClaudeSidecarUsageEvent.timestamp),
                ).group_by(ClaudeSidecarUsageEvent.auth_index, ClaudeSidecarUsageEvent.source)
            )
        ).all()
        return {(row[0], row[1]): row[2] for row in rows if row[2] is not None}

    async def list_events_since(self, since: datetime) -> list[ClaudeSidecarUsageEvent]:
        return (
            (
                await self._session.execute(
                    select(ClaudeSidecarUsageEvent)
                    .where(ClaudeSidecarUsageEvent.timestamp >= since)
                    .order_by(ClaudeSidecarUsageEvent.timestamp.asc(), ClaudeSidecarUsageEvent.id.asc())
                )
            )
            .scalars()
            .all()
        )

    async def delete_older_than(self, cutoff: datetime) -> int:
        result = await self._session.execute(
            delete(ClaudeSidecarUsageEvent).where(ClaudeSidecarUsageEvent.timestamp < cutoff)
        )
        await self._session.commit()
        return int(result.rowcount or 0)
