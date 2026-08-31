"""Durable store for external-integration model price resolutions.

One row per ``(provider, incoming_model)``. The request path reads it and never
writes; the background lookup and the maintenance command are the only writers.
Keeping writes off the request path is what makes a known id cost exactly one
indexed read no matter how much traffic it carries.

Lookups atomically claim a short lease in that row. Outcome writes carry the
claim token, so stale work cannot replace a newer result and a crashed worker
cannot strand the model indefinitely.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import Select, and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.usage.pricing import ModelPrice
from app.core.utils.time import utcnow
from app.db.models import ExternalModelPrice, ExternalPriceStatus
from app.db.session import sqlite_writer_section

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

_LOOKUP_LEASE = timedelta(minutes=2)


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

    @property
    def is_settled(self) -> bool:
        """Whether this record already holds an answer a source produced.

        A priced record and a not-token-priced one are both answers. Neither may
        be discarded because some *other* source failed to answer this pass: the
        outage says nothing about a question that was already closed.
        """

        return self.is_priced or self.status is ExternalPriceStatus.NOT_TOKEN_PRICED

    def retry_due(self, *, now: datetime | None = None) -> bool:
        """Whether this record may be looked up again.

        A settled answer carries no deadline, so it is never due: re-deriving one
        per request is exactly the work this store exists to eliminate. The one
        exception is a rate preserved through an unreadable upstream price, which
        stays ``RESOLVED`` and keeps serving while carrying a deadline, so the
        source is re-read rather than the question being closed.
        """

        if self.next_retry_at is None:
            return self.status not in (ExternalPriceStatus.RESOLVED, ExternalPriceStatus.NOT_TOKEN_PRICED)
        return (now or utcnow()) >= self.next_retry_at


@dataclass(frozen=True, slots=True)
class LookupClaim:
    token: str
    record: PriceRecord


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

    async def rates_for_models(
        self,
        lookup_keys: Sequence[tuple[str, str]],
    ) -> dict[tuple[str, str], ModelPrice]:
        """Persisted rates keyed by provider and incoming model id.

        One query for the whole page: the read path may not turn rendering a list
        into a lookup per row. The provider remains part of the key because two
        integrations may publish different component rates for the same id.
        """

        keys = {
            normalize_lookup_key(provider, model)
            for provider, model in lookup_keys
            if provider and model and model.strip()
        }
        if not keys:
            return {}
        providers = sorted({provider for provider, _model in keys})
        models = sorted({model for _provider, model in keys})
        result = await self._session.execute(
            select(ExternalModelPrice).where(
                ExternalModelPrice.provider.in_(providers),
                ExternalModelPrice.incoming_model.in_(models),
                ExternalModelPrice.status == ExternalPriceStatus.RESOLVED.value,
            )
        )
        rates: dict[tuple[str, str], ModelPrice] = {}
        for row in result.scalars().all():
            record = _to_record(row)
            key = (record.provider, record.incoming_model)
            if key in keys and record.price is not None:
                rates[key] = record.price
        return rates

    async def claim_lookup(self, provider: str, incoming_model: str) -> LookupClaim | None:
        provider_key, model_key = normalize_lookup_key(provider, incoming_model)
        if not provider_key or not model_key:
            return None
        now = utcnow()
        token = uuid4().hex
        lease_until = now + _LOOKUP_LEASE
        values = {
            "provider": provider_key,
            "incoming_model": model_key,
            "status": ExternalPriceStatus.PENDING.value,
            "catalog_model": None,
            "catalog_source": None,
            "input_per_1m": None,
            "output_per_1m": None,
            "resolution_step": None,
            "detail": "lookup in progress",
            "retrieved_at": now,
            "updated_at": now,
            "attempt_count": 0,
            "next_retry_at": lease_until,
            "lookup_token": token,
        }
        dialect = self._session.bind.dialect.name if self._session.bind is not None else "sqlite"
        insert = pg_insert if dialect == "postgresql" else sqlite_insert
        statement = insert(ExternalModelPrice).values(**values)
        due = or_(ExternalModelPrice.next_retry_at.is_(None), ExternalModelPrice.next_retry_at <= now)
        retryable = or_(
            ExternalModelPrice.status.not_in(
                (ExternalPriceStatus.RESOLVED.value, ExternalPriceStatus.NOT_TOKEN_PRICED.value)
            ),
            ExternalModelPrice.next_retry_at.is_not(None),
        )
        statement = statement.on_conflict_do_update(
            index_elements=[ExternalModelPrice.provider, ExternalModelPrice.incoming_model],
            set_={
                "lookup_token": token,
                "next_retry_at": lease_until,
                "updated_at": now,
            },
            where=and_(retryable, due),
        ).returning(ExternalModelPrice)
        async with sqlite_writer_section():
            result = await self._session.execute(statement)
            row = result.scalar_one_or_none()
            await self._session.commit()
        if row is None:
            return None
        return LookupClaim(token=token, record=_to_record(row))

    async def record_resolved(
        self,
        *,
        provider: str,
        incoming_model: str,
        catalog_model: str,
        catalog_source: str,
        price: ModelPrice,
        resolution_step: str,
        claim_token: str | None = None,
    ) -> bool:
        """Persist a successful resolution, clearing any prior failure state."""

        return await self._upsert(
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
            claim_token=claim_token,
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
        claim_token: str | None = None,
    ) -> bool:
        """Persist a model the catalog lists but does not price per token.

        This is a settled answer, not a failure: the model has no token rate to
        find, so it carries no retry state and the UI shows ``--`` rather than an
        unresolved marker.
        """

        return await self._upsert(
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
            claim_token=claim_token,
        )

    async def record_price_unparseable(
        self,
        *,
        provider: str,
        incoming_model: str,
        record: PriceRecord | None,
        catalog_model: str | None,
        catalog_source: str | None,
        detail: str,
        previous_attempts: int = 0,
        claim_token: str | None = None,
    ) -> bool:
        """The source still lists the model but priced it unreadably.

        Neither a resolution nor a delisting. Whatever rate was last parsed
        successfully stays exactly as it is -- an upstream schema change must not
        be able to erase a good rate -- and only the retry deadline advances, so
        the next lookup re-reads the source instead of settling the question.
        """

        return await self.record_retryable_failure(
            provider=provider,
            incoming_model=incoming_model,
            record=record,
            detail=detail,
            catalog_model=catalog_model,
            catalog_source=catalog_source,
            previous_attempts=previous_attempts,
            claim_token=claim_token,
        )

    async def record_retryable_failure(
        self,
        *,
        provider: str,
        incoming_model: str,
        record: PriceRecord | None,
        detail: str,
        catalog_model: str | None = None,
        catalog_source: str | None = None,
        previous_attempts: int = 0,
        claim_token: str | None = None,
    ) -> bool:
        attempts = previous_attempts + 1
        if record is not None and record.is_priced:
            assert record.price is not None
            return await self._upsert(
                provider=provider,
                incoming_model=incoming_model,
                status=ExternalPriceStatus.RESOLVED,
                catalog_model=record.catalog_model,
                catalog_source=record.catalog_source,
                input_per_1m=record.price.input_per_1m,
                output_per_1m=record.price.output_per_1m,
                resolution_step=record.resolution_step,
                detail=detail,
                # The incremented count is what widens the schedule. Resetting it
                # would pin the deadline at the first backoff step, so an upstream
                # schema change would re-fetch every five minutes indefinitely.
                attempt_count=attempts,
                retry_at=next_retry_at(attempts),
                retrieved_at=record.retrieved_at,
                claim_token=claim_token,
            )
        # Nothing was ever parsed for this id, so there is no value to preserve.
        # It stays unresolved with backoff rather than being settled as unpriced.
        return await self._upsert(
            provider=provider,
            incoming_model=incoming_model,
            status=ExternalPriceStatus.UNRESOLVED,
            catalog_model=catalog_model,
            catalog_source=catalog_source,
            input_per_1m=None,
            output_per_1m=None,
            resolution_step=None,
            detail=detail,
            attempt_count=attempts,
            retry_at=next_retry_at(attempts),
            claim_token=claim_token,
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
        claim_token: str | None = None,
    ) -> bool:
        """Persist a failed or abstained lookup with bounded backoff.

        Both the "nothing matched" and "several catalog models matched" outcomes
        land here. Persisting them is what stops a busy model id from re-running a
        lookup on every request: the row's retry deadline, not the traffic, decides
        when the next attempt happens.
        """

        attempts = previous_attempts + 1
        return await self._upsert(
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
            claim_token=claim_token,
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
        retrieved_at: datetime | None = None,
        claim_token: str | None = None,
    ) -> bool:
        provider_key, model_key = normalize_lookup_key(provider, incoming_model)
        if not provider_key or not model_key:
            return False
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
            # A preserved rate keeps the retrieval time of the fetch that produced
            # it: nothing new was retrieved, so claiming otherwise would overstate
            # the freshness of a number this pass could not confirm.
            "retrieved_at": retrieved_at or now,
            "updated_at": now,
            "attempt_count": attempt_count,
            "next_retry_at": retry_at,
            "lookup_token": None,
        }
        if claim_token is not None:
            statement = (
                update(ExternalModelPrice)
                .where(
                    ExternalModelPrice.provider == provider_key,
                    ExternalModelPrice.incoming_model == model_key,
                    ExternalModelPrice.lookup_token == claim_token,
                )
                .values(**{key: value for key, value in values.items() if key not in ("provider", "incoming_model")})
            )
            async with sqlite_writer_section():
                result = await self._session.execute(statement)
                await self._session.commit()
            return bool(result.rowcount)
        dialect = self._session.bind.dialect.name if self._session.bind is not None else "sqlite"
        insert = pg_insert if dialect == "postgresql" else sqlite_insert
        statement = insert(ExternalModelPrice).values(**values)
        # Concurrent first sightings of the same id race here by design: the
        # conflict target collapses them onto one row rather than raising.
        statement = statement.on_conflict_do_update(
            index_elements=[ExternalModelPrice.provider, ExternalModelPrice.incoming_model],
            set_={key: value for key, value in values.items() if key not in ("provider", "incoming_model")},
        )
        # Background lookups write while requests are writing their logs. On
        # file-backed SQLite that is the contention this section serializes; a
        # "database is locked" here would leave the record with no backoff row and
        # let the next request re-dispatch the same lookup.
        async with sqlite_writer_section():
            await self._session.execute(statement)
            await self._session.commit()
        return True

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
