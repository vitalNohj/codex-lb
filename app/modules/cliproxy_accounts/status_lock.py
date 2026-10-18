"""Serialize CLIProxyAPI credential status writes across serving workers.

The last-enabled check and the upstream status PATCH have to see one
inventory. SQLite takes a leased claim row. PostgreSQL holds
``pg_advisory_xact_lock`` on the request transaction until that commit.
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

STATUS_WRITE_LOCK_NAME = "status"
_LEASE_SECONDS = 30.0
_RENEW_INTERVAL_SECONDS = 10.0
_RETRY_INTERVAL_SECONDS = 0.05
_TIMEOUT_SECONDS = 20.0


class StatusWriteLockTimeout(Exception):
    """The status write claim stayed held past the acquisition timeout."""


class ApiKeyWriteLockTimeout(Exception):
    """The API-key list claim stayed held past the acquisition timeout."""


class PrefixWriteLockTimeout(Exception):
    """The prefix claim stayed held past the acquisition timeout."""


class _ClaimLock:
    def __init__(self, name: str, pg_key: str, timeout_message: str, timeout_type: type[Exception]) -> None:
        self.name = name
        self.pg_key = pg_key
        self.timeout_message = timeout_message
        self.timeout_type = timeout_type
        self.process_lock = asyncio.Lock()


_STATUS_LOCK = _ClaimLock(
    STATUS_WRITE_LOCK_NAME,
    "cliproxy-status-writes",
    "Another credential status update is in progress",
    StatusWriteLockTimeout,
)


@asynccontextmanager
async def cliproxy_status_write_lock(session: AsyncSession) -> AsyncIterator[None]:
    """Hold the status-write lock across the inventory check and upstream PATCH."""

    async with _claim_lock(session, _STATUS_LOCK):
        yield


_API_KEY_LIST_LOCKS: dict[str, _ClaimLock] = {}


def _api_key_list_lock(kind: str) -> _ClaimLock:
    existing = _API_KEY_LIST_LOCKS.get(kind)
    if existing is not None:
        return existing
    created = _ClaimLock(
        name=f"api-key:{kind}",
        pg_key=f"cliproxy-api-key-list:{kind}",
        timeout_message="Another API-key account update is in progress",
        timeout_type=ApiKeyWriteLockTimeout,
    )
    return _API_KEY_LIST_LOCKS.setdefault(kind, created)


_PREFIX_LOCK = _ClaimLock(
    "prefix",
    "cliproxy-prefix-writes",
    "Another CLIProxyAPI prefix update is in progress",
    PrefixWriteLockTimeout,
)


@asynccontextmanager
async def cliproxy_prefix_write_lock(session: AsyncSession) -> AsyncIterator[None]:
    """Hold the prefix lock while a stored prefix is assigned or replaced."""

    async with _claim_lock(session, _PREFIX_LOCK):
        yield


@asynccontextmanager
async def cliproxy_api_key_list_lock(session: AsyncSession, kind: str) -> AsyncIterator[None]:
    """Hold one provider list lock from the read through the upstream mutation."""

    async with _claim_lock(session, _api_key_list_lock(kind)):
        yield


@asynccontextmanager
async def _claim_lock(session: AsyncSession, lock: _ClaimLock) -> AsyncIterator[None]:
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
            {"lock_key": lock.pg_key},
        )
        yield
        return
    if dialect == "sqlite":
        holder_id = uuid.uuid4().hex
        await _acquire_sqlite_claim(holder_id, lock)
        heartbeat = asyncio.create_task(
            _renew_sqlite_claim_periodically(holder_id, lock),
            name=f"cliproxy-{lock.name}-write-claim-heartbeat",
        )
        try:
            yield
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat
            await _release_sqlite_claim(holder_id, lock)
        return
    async with lock.process_lock:
        yield


async def _acquire_sqlite_claim(holder_id: str, lock: _ClaimLock) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _TIMEOUT_SECONDS
    while True:
        if await _try_acquire_sqlite_claim(holder_id, lock):
            return
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise lock.timeout_type(lock.timeout_message)
        await asyncio.sleep(min(_RETRY_INTERVAL_SECONDS, remaining))


async def _try_acquire_sqlite_claim(holder_id: str, lock: _ClaimLock) -> bool:
    now = datetime.now(UTC)
    claim_session = SessionLocal()
    try:
        insert_stmt = sqlite_insert(CliproxyPrefixWriteClaim).values(
            lock_name=lock.name,
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


async def _renew_sqlite_claim_periodically(holder_id: str, lock: _ClaimLock) -> None:
    while True:
        await asyncio.sleep(_RENEW_INTERVAL_SECONDS)
        claim_session = SessionLocal()
        try:
            now = datetime.now(UTC)
            result = await claim_session.execute(
                update(CliproxyPrefixWriteClaim)
                .where(
                    CliproxyPrefixWriteClaim.lock_name == lock.name,
                    CliproxyPrefixWriteClaim.holder_id == holder_id,
                )
                .values(expires_at=now + timedelta(seconds=_LEASE_SECONDS))
                .returning(CliproxyPrefixWriteClaim.lock_name)
            )
            await claim_session.commit()
            if result.scalar_one_or_none() is None:
                return
        except Exception:
            logger.warning("CLIProxyAPI %s write claim renewal failed", lock.name, exc_info=True)
        finally:
            await close_session(claim_session)


async def _release_sqlite_claim(holder_id: str, lock: _ClaimLock) -> None:
    claim_session = SessionLocal()
    try:
        await claim_session.execute(
            delete(CliproxyPrefixWriteClaim).where(
                CliproxyPrefixWriteClaim.lock_name == lock.name,
                CliproxyPrefixWriteClaim.holder_id == holder_id,
            )
        )
        await claim_session.commit()
    except Exception:
        logger.warning("CLIProxyAPI %s write claim release failed", lock.name, exc_info=True)
    finally:
        await close_session(claim_session)
