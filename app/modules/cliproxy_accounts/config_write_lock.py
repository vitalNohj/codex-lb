"""Cross-worker lease for one CLIProxyAPI config.yaml.

The panel commits the rollback snapshot before the management upload returns,
so a transaction advisory lock would drop while the PUT is still in flight.
This claim is committed on its own and renewed until the upload and failure
recovery finish. A crashed holder is recoverable after the lease expires.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.db.models import CliproxyConfigWriteClaim
from app.db.session import SessionLocal, close_session

logger = logging.getLogger(__name__)

_LEASE_SECONDS = 30.0
_RENEW_INTERVAL_SECONDS = 10.0
_RETRY_INTERVAL_SECONDS = 0.05
_ACQUIRE_TIMEOUT_SECONDS = 60.0


class CliproxyConfigWriteBusy(Exception):
    """Another worker still holds the config write lease."""


def cliproxy_config_lock_key(base_url: str) -> str:
    """One lease per CLIProxyAPI origin. A trailing slash does not make a second lock."""

    return hashlib.sha256(base_url.strip().rstrip("/").encode("utf-8")).hexdigest()


@asynccontextmanager
async def cliproxy_config_write_lock(
    lock_key: str,
    *,
    timeout: float = _ACQUIRE_TIMEOUT_SECONDS,
) -> AsyncIterator[None]:
    holder_id = uuid.uuid4().hex
    await _acquire(lock_key, holder_id, timeout=timeout)
    heartbeat = asyncio.create_task(_renew_periodically(lock_key, holder_id))
    try:
        yield
    finally:
        heartbeat.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat
        await _release(lock_key, holder_id)


async def _acquire(lock_key: str, holder_id: str, *, timeout: float) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        if await _try_acquire(lock_key, holder_id):
            return
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise CliproxyConfigWriteBusy
        await asyncio.sleep(min(_RETRY_INTERVAL_SECONDS, remaining))


async def _try_acquire(lock_key: str, holder_id: str) -> bool:
    now = datetime.now(UTC)
    session = SessionLocal()
    try:
        values = {
            "lock_key": lock_key,
            "holder_id": holder_id,
            "expires_at": now + timedelta(seconds=_LEASE_SECONDS),
        }
        dialect = session.get_bind().dialect.name
        insert_fn = pg_insert if dialect == "postgresql" else sqlite_insert
        insert_stmt = insert_fn(CliproxyConfigWriteClaim).values(**values)
        stmt = insert_stmt.on_conflict_do_update(
            index_elements=[CliproxyConfigWriteClaim.lock_key],
            set_={
                "holder_id": insert_stmt.excluded.holder_id,
                "expires_at": insert_stmt.excluded.expires_at,
            },
            where=CliproxyConfigWriteClaim.expires_at < now,
        )
        result = await session.execute(stmt.returning(CliproxyConfigWriteClaim.lock_key))
        await session.commit()
        return result.scalar_one_or_none() is not None
    finally:
        await close_session(session)


async def _renew_periodically(lock_key: str, holder_id: str) -> None:
    while True:
        await asyncio.sleep(_RENEW_INTERVAL_SECONDS)
        try:
            renewed = await _renew(lock_key, holder_id)
        except Exception:
            logger.warning("CLIProxyAPI config write lease renewal failed", exc_info=True)
            continue
        if not renewed:
            logger.warning("CLIProxyAPI config write lease lost before renewal")
            return


async def _renew(lock_key: str, holder_id: str) -> bool:
    now = datetime.now(UTC)
    session = SessionLocal()
    try:
        result = await session.execute(
            update(CliproxyConfigWriteClaim)
            .where(
                CliproxyConfigWriteClaim.lock_key == lock_key,
                CliproxyConfigWriteClaim.holder_id == holder_id,
            )
            .values(expires_at=now + timedelta(seconds=_LEASE_SECONDS))
            .returning(CliproxyConfigWriteClaim.lock_key)
        )
        await session.commit()
        return result.scalar_one_or_none() is not None
    finally:
        await close_session(session)


async def _release(lock_key: str, holder_id: str) -> None:
    session = SessionLocal()
    try:
        await session.execute(
            delete(CliproxyConfigWriteClaim).where(
                CliproxyConfigWriteClaim.lock_key == lock_key,
                CliproxyConfigWriteClaim.holder_id == holder_id,
            )
        )
        await session.commit()
    except Exception:
        logger.warning("CLIProxyAPI config write lease release failed", exc_info=True)
    finally:
        await close_session(session)
