"""Durable store for external-integration model price resolutions.

One row per ``(provider, incoming_model)``. The request path reads it and never
writes; the background lookup and the maintenance command are the only writers.
Keeping writes off the request path is what makes a known id cost exactly one
indexed read no matter how much traffic it carries.

Upserts are expressed as dialect-native ``INSERT ... ON CONFLICT DO UPDATE`` so
two workers that resolve the same first-sighting concurrently converge on one row
instead of racing a read-then-write.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.usage.pricing import ModelPrice
from app.core.utils.time import utcnow
from app.db.models import ExternalModelPrice, ExternalPriceStatus

logger = logging.getLogger(__name__)

# Retry schedule for a record whose lookup did not produce a price. Capped so a
# permanently unknown id settles at one lookup per day rather than growing without
# bound or hammering the catalogs. Attempt N waits ``_RETRY_BACKOFF[N-1]``.
_RETRY_BACKOFF: tuple[timedelta, ...] = (
    timedelta(minutes=5),
    timedelta(minutes=30),
    timedelta(hours=2),
    timedelta(hours=6),
    timedelta(hours=24),
)


@dataclass(frozen=True, slots=True)
class PriceRecord:
    """One persisted resolution, as the request path sees it."""

    provider: str
    incoming_model: str
    status: ExternalPriceStatus
    catalog_model: str | None
    catalog_source: str | None
    price: ModelPrice | None
    resolution_step: str | None
    detail: str | None
    retrieved_at: datetime
    updated_at: datetime
    attempt_count: int
    next_retry_at: datetime | None

    @property
    def is_priced(self) -> bool:
        return self.status is ExternalPriceStatus.RESOLVED and self.price is not None

    def retry_due(self, *, now: datetime | None = None) -> bool:
        """Whether an unresolved record may be looked up again.

        A resolved or not-token-priced record is never due: both are settled
        answers, and re-deriving them per request is exactly the work this store
        exists to eliminate. Only maintenance revisits them.
        """

        if self.status in (ExternalPriceStatus.RESOLVED, ExternalPriceStatus.NOT_TOKEN_PRICED):
            return False
        if self.next_retry_at is None:
            return True
        return (now or utcnow()) >= self.next_retry_at


def next_retry_at(attempt_count: int, *, now: datetime | None = None) -> datetime:
    """Backoff deadline after ``attempt_count`` consecutive failed lookups."""

    index = min(max(attempt_count, 1), len(_RETRY_BACKOFF)) - 1
    return (now or utcnow()) + _RETRY_BACKOFF[index]


def normalize_lookup_key(provider: str, incoming_model: str) -> tuple[str, str]:
    return provider.strip().lower(), incoming_model.strip().lower()


class ExternalModelPriceStore:
    """Repository over ``external_model_prices``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, provider: str, incoming_model: str) -> PriceRecord | None:
        provider_key, model_key = normalize_lookup_key(provider, incoming_model)
        if not provider_key or not model_key:
            return None
        result = await self._session.execute(self._select_one(provider_key, model_key))
        row = result.scalar_one_or_none()
        return _to_record(row) if row is not None else None

    async def list_all(self) -> list[PriceRecord]:
        result = await self._session.execute(
            select(ExternalModelPrice).order_by(ExternalModelPrice.provider, ExternalModelPrice.incoming_model)
        )
        return [_to_record(row) for row in result.scalars().all()]

    async def record_resolved(
        self,
        *,
        provider: str,
        incoming_model: str,
        catalog_model: str,
        catalog_source: str,
        price: ModelPrice,
        resolution_step: str,
    ) -> None:
        """Persist a successful resolution, clearing any prior failure state."""

        await self._upsert(
            provider=provider,
            incoming_model=incoming_model,
            status=ExternalPriceStatus.RESOLVED,
            catalog_model=catalog_model,
            catalog_source=catalog_source,
            input_per_1m=price.input_per_1m,
            output_per_1m=price.output_per_1m,
            resolution_step=resolution_step,
            detail=None,
            attempt_count=0,
            retry_at=None,
        )

    async def record_not_token_priced(
        self,
        *,
        provider: str,
        incoming_model: str,
        catalog_model: str,
        catalog_source: str,
        resolution_step: str,
        detail: str,
    ) -> None:
        """Persist a model the catalog lists but does not price per token.

        This is a settled answer, not a failure: the model has no token rate to
        find, so it carries no retry state and the UI shows ``--`` rather than an
        unresolved marker.
        """

        await self._upsert(
            provider=provider,
            incoming_model=incoming_model,
            status=ExternalPriceStatus.NOT_TOKEN_PRICED,
            catalog_model=catalog_model,
            catalog_source=catalog_source,
            input_per_1m=None,
            output_per_1m=None,
            resolution_step=resolution_step,
            detail=detail,
            attempt_count=0,
            retry_at=None,
        )

    async def record_unresolved(
        self,
        *,
        provider: str,
        incoming_model: str,
        status: ExternalPriceStatus,
        detail: str | None,
        resolution_step: str | None = None,
        previous_attempts: int = 0,
    ) -> None:
        """Persist a failed or abstained lookup with bounded backoff.

        Both the "nothing matched" and "several catalog models matched" outcomes
        land here. Persisting them is what stops a busy model id from re-running a
        lookup on every request: the row's retry deadline, not the traffic, decides
        when the next attempt happens.
        """

        attempts = previous_attempts + 1
        await self._upsert(
            provider=provider,
            incoming_model=incoming_model,
            status=status,
            catalog_model=None,
            catalog_source=None,
            input_per_1m=None,
            output_per_1m=None,
            resolution_step=resolution_step,
            detail=detail,
            attempt_count=attempts,
            retry_at=next_retry_at(attempts),
        )

    async def _upsert(
        self,
        *,
        provider: str,
        incoming_model: str,
        status: ExternalPriceStatus,
        catalog_model: str | None,
        catalog_source: str | None,
        input_per_1m: float | None,
        output_per_1m: float | None,
        resolution_step: str | None,
        detail: str | None,
        attempt_count: int,
        retry_at: datetime | None,
    ) -> None:
        provider_key, model_key = normalize_lookup_key(provider, incoming_model)
        if not provider_key or not model_key:
            return
        now = utcnow()
        values = {
            "provider": provider_key,
            "incoming_model": model_key,
            "status": status.value,
            "catalog_model": catalog_model,
            "catalog_source": catalog_source,
            "input_per_1m": input_per_1m,
            "output_per_1m": output_per_1m,
            "resolution_step": resolution_step,
            "detail": detail,
            "retrieved_at": now,
            "updated_at": now,
            "attempt_count": attempt_count,
            "next_retry_at": retry_at,
        }
        dialect = self._session.bind.dialect.name if self._session.bind is not None else "sqlite"
        insert = pg_insert if dialect == "postgresql" else sqlite_insert
        statement = insert(ExternalModelPrice).values(**values)
        # Concurrent first sightings of the same id race here by design: the
        # conflict target collapses them onto one row rather than raising.
        statement = statement.on_conflict_do_update(
            index_elements=[ExternalModelPrice.provider, ExternalModelPrice.incoming_model],
            set_={key: value for key, value in values.items() if key not in ("provider", "incoming_model")},
        )
        await self._session.execute(statement)
        await self._session.commit()

    @staticmethod
    def _select_one(provider_key: str, model_key: str) -> Select[tuple[ExternalModelPrice]]:
        return select(ExternalModelPrice).where(
            ExternalModelPrice.provider == provider_key,
            ExternalModelPrice.incoming_model == model_key,
        )


def _to_record(row: ExternalModelPrice) -> PriceRecord:
    price: ModelPrice | None = None
    if row.input_per_1m is not None and row.output_per_1m is not None:
        # Cached input is deliberately priced at the full input rate: no
        # participating catalog publishes a cache-read rate for every model, and
        # inventing a discount ratio would be a fabricated number rather than a
        # published one.
        price = ModelPrice(input_per_1m=row.input_per_1m, output_per_1m=row.output_per_1m)
    return PriceRecord(
        provider=row.provider,
        incoming_model=row.incoming_model,
        status=_parse_status(row.status),
        catalog_model=row.catalog_model,
        catalog_source=row.catalog_source,
        price=price,
        resolution_step=row.resolution_step,
        detail=row.detail,
        retrieved_at=row.retrieved_at,
        updated_at=row.updated_at,
        attempt_count=row.attempt_count,
        next_retry_at=row.next_retry_at,
    )


def _parse_status(raw: str) -> ExternalPriceStatus:
    try:
        return ExternalPriceStatus(raw)
    except ValueError:
        # A row written by a newer version carrying an unknown status must not
        # crash the request path. Treating it as unresolved is safe: the UI shows
        # no price and maintenance rewrites it.
        logger.warning("unknown external price status %r; treating as unresolved", raw)
        return ExternalPriceStatus.UNRESOLVED


def statuses_requiring_attention() -> Sequence[ExternalPriceStatus]:
    """Statuses the maintenance command reports for operator review."""

    return (ExternalPriceStatus.UNRESOLVED, ExternalPriceStatus.AMBIGUOUS)
