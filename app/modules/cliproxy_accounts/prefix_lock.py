"""Serialize CLIProxyAPI prefix writes across serving workers.

A prefix edit patches CLIProxyAPI and then commits the codex-lb registry.
Those two steps have to stay in one order: if an older request commits the
registry after a newer request, inventory keeps the stale prefix forever.
SQLite takes a leased claim row. PostgreSQL holds ``pg_advisory_xact_lock``
on the request transaction until that commit.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, text, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CliproxyPrefixWriteClaim
from app.db.session import SessionLocal, close_session

logger = logging.getLogger(__name__)

PREFIX_WRITE_LOCK_NAME = "prefixes"
_LEASE_SECONDS = 30.0
_RENEW_INTERVAL_SECONDS = 10.0
_RETRY_INTERVAL_SECONDS = 0.05
_TIMEOUT_SECONDS = 20.0
_PROCESS_LOCK = asyncio.Lock()


class PrefixWriteLockTimeout(Exception):
    """The prefix write claim stayed held past the acquisition timeout."""


@asynccontextmanager
async def cliproxy_prefix_write_lock(session: AsyncSession) -> AsyncIterator[None]:
    """Hold the prefix-write lock across the upstream PATCH and registry commit."""

    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
            {"lock_key": "cliproxy-prefix-writes"},
        )
        yield
        return
    if dialect == "sqlite":
        holder_id = uuid.uuid4().hex
        await _acquire_sqlite_claim(holder_id)
        heartbeat = asyncio.create_task(
            _renew_sqlite_claim_periodically(holder_id),
            name="cliproxy-prefix-write-claim-heartbeat",
        )
        try:
            yield
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat
            await _release_sqlite_claim(holder_id)
        return
    async with _PROCESS_LOCK:
        yield


async def _acquire_sqlite_claim(holder_id: str) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _TIMEOUT_SECONDS
    while True:
        if await _try_acquire_sqlite_claim(holder_id):
            return
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise PrefixWriteLockTimeout("Another credential prefix update is in progress")
        await asyncio.sleep(min(_RETRY_INTERVAL_SECONDS, remaining))


async def _try_acquire_sqlite_claim(holder_id: str) -> bool:
    now = datetime.now(UTC)
    claim_session = SessionLocal()
    try:
        insert_stmt = sqlite_insert(CliproxyPrefixWriteClaim).values(
            lock_name=PREFIX_WRITE_LOCK_NAME,
            holder_id=holder_id,
            expires_at=now + timedelta(seconds=_LEASE_SECONDS),
        )
        statement = insert_stmt.on_conflict_do_update(
            index_elements=[CliproxyPrefixWriteClaim.lock_name],
            set_={
                "holder_id": insert_stmt.excluded.holder_id,
                "expires_at": insert_stmt.excluded.expires_at,
            },
            where=CliproxyPrefixWriteClaim.expires_at < now,
        )
        result = await claim_session.execute(statement.returning(CliproxyPrefixWriteClaim.lock_name))
        await claim_session.commit()
        return result.scalar_one_or_none() is not None
    finally:
        await close_session(claim_session)


async def _renew_sqlite_claim_periodically(holder_id: str) -> None:
    while True:
        await asyncio.sleep(_RENEW_INTERVAL_SECONDS)
        claim_session = SessionLocal()
        try:
            now = datetime.now(UTC)
            result = await claim_session.execute(
                update(CliproxyPrefixWriteClaim)
                .where(
                    CliproxyPrefixWriteClaim.lock_name == PREFIX_WRITE_LOCK_NAME,
                    CliproxyPrefixWriteClaim.holder_id == holder_id,
                )
                .values(expires_at=now + timedelta(seconds=_LEASE_SECONDS))
                .returning(CliproxyPrefixWriteClaim.lock_name)
            )
            await claim_session.commit()
            if result.scalar_one_or_none() is None:
                return
        except Exception:
            logger.warning("CLIProxyAPI prefix write claim renewal failed", exc_info=True)
        finally:
            await close_session(claim_session)


async def _release_sqlite_claim(holder_id: str) -> None:
    claim_session = SessionLocal()
    try:
        await claim_session.execute(
            delete(CliproxyPrefixWriteClaim).where(
                CliproxyPrefixWriteClaim.lock_name == PREFIX_WRITE_LOCK_NAME,
                CliproxyPrefixWriteClaim.holder_id == holder_id,
            )
        )
        await claim_session.commit()
    except Exception:
        logger.warning("CLIProxyAPI prefix write claim release failed", exc_info=True)
    finally:
        await close_session(claim_session)
