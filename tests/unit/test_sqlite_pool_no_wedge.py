"""File-SQLite sessions held across a wait on another task must not wedge the process.

#177 took the process-wide SQLite writer lock when a session checked out its
connection and released it only on checkin. A task that kept a session open
while it awaited a second task that needed a session deadlocked: the lock
re-entered only for its owner task. ``LeaderElection.run_if_leader`` runs its
body as a separate task, so a scheduler holding a session around it wedged
every later request, ``/health/live`` included.

These tests use the real file-SQLite engine settings. Each one awaits under a
timeout so a deadlock fails the test instead of hanging the suite.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.core.scheduling.leader_election as leader_election_module
import app.db.session as session_module
from app.db.models import Base
from app.db.session import get_background_session, sqlite_writer_section

pytestmark = pytest.mark.unit

# Generous for a loaded CI host; a deadlock never finishes at all.
_DEADLOCK_TIMEOUT_SECONDS = 10.0
# More concurrent sessions than the pool retains, so overflow is exercised.
_MANY_SESSIONS = 12


@asynccontextmanager
async def _file_sqlite_background_sessions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Point ``get_background_session`` at a fresh file-SQLite engine with production pool settings."""
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'store.db'}"
    engine = create_async_engine(database_url, **session_module._sqlite_file_async_engine_kwargs())
    session_module._configure_sqlite_engine(engine.sync_engine, enable_wal=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    # The writer section is active for file SQLite only; make that explicit
    # instead of depending on the suite's database URL.
    monkeypatch.setattr(session_module, "_settings", SimpleNamespace(database_url=database_url))
    monkeypatch.setattr(session_module, "_sqlite_writer_lock", None)
    monkeypatch.setattr(session_module, "_background_session_factory", factory)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await connection.exec_driver_sql("CREATE TABLE marks (task TEXT NOT NULL)")
        yield factory
    finally:
        await engine.dispose()


async def _write_mark(name: str) -> None:
    async with get_background_session() as session:
        async with sqlite_writer_section():
            await session.execute(text("INSERT INTO marks (task) VALUES (:task)"), {"task": name})
            await session.commit()


async def _marks() -> list[str]:
    async with get_background_session() as session:
        rows = await session.execute(text("SELECT task FROM marks ORDER BY rowid"))
        return [row[0] for row in rows]


@pytest.mark.asyncio
async def test_session_held_while_awaiting_a_task_that_writes_finishes(tmp_path, monkeypatch) -> None:
    """The handoff regression: A holds an open session and awaits B, which needs a session."""
    async with _file_sqlite_background_sessions(tmp_path, monkeypatch):

        async def holder() -> None:
            async with get_background_session() as session:
                # The read checks out a connection and opens a transaction,
                # so the session really holds it while it waits below.
                await session.execute(text("SELECT count(*) FROM marks"))
                await asyncio.create_task(_write_mark("other-task"))
                await session.execute(text("SELECT count(*) FROM marks"))

        await asyncio.wait_for(holder(), timeout=_DEADLOCK_TIMEOUT_SECONDS)
        assert await _marks() == ["other-task"]


@pytest.mark.asyncio
async def test_writer_section_does_not_block_another_task_from_reading(tmp_path, monkeypatch) -> None:
    """Reads take no lock: a task inside a writer section may wait on a reader task."""
    async with _file_sqlite_background_sessions(tmp_path, monkeypatch):

        async def writer() -> list[str]:
            async with get_background_session() as session:
                async with sqlite_writer_section():
                    await session.execute(text("INSERT INTO marks (task) VALUES ('writer')"))
                    # WAL: the reader sees the last committed state, not this
                    # uncommitted row, and does not wait for the writer.
                    seen = await asyncio.create_task(_marks())
                    await session.commit()
            return seen

        assert await asyncio.wait_for(writer(), timeout=_DEADLOCK_TIMEOUT_SECONDS) == []
        assert await _marks() == ["writer"]


@pytest.mark.asyncio
async def test_more_held_sessions_than_retained_connections_do_not_wait(tmp_path, monkeypatch) -> None:
    """Every task holds a session until all of them have one; the pool must not make any wait."""
    async with _file_sqlite_background_sessions(tmp_path, monkeypatch):
        holders = _MANY_SESSIONS
        assert holders > session_module._sqlite_file_async_engine_kwargs()["pool_size"]
        all_checked_out = asyncio.Event()
        checked_out = 0

        async def hold() -> None:
            nonlocal checked_out
            async with get_background_session() as session:
                await session.execute(text("SELECT 1"))
                checked_out += 1
                if checked_out == holders:
                    all_checked_out.set()
                await all_checked_out.wait()

        await asyncio.wait_for(
            asyncio.gather(*(hold() for _ in range(holders))),
            timeout=_DEADLOCK_TIMEOUT_SECONDS,
        )
        assert checked_out == holders


@pytest.mark.asyncio
async def test_nested_chain_of_tasks_each_holding_a_session_finishes(tmp_path, monkeypatch) -> None:
    """Each task holds a session and awaits the next one, deeper than the retained pool."""
    async with _file_sqlite_background_sessions(tmp_path, monkeypatch):
        depth = _MANY_SESSIONS

        async def link(level: int) -> None:
            async with get_background_session() as session:
                await session.execute(text("SELECT 1"))
                if level < depth:
                    await asyncio.create_task(link(level + 1))
                else:
                    await asyncio.create_task(_write_mark("deepest"))

        await asyncio.wait_for(link(1), timeout=_DEADLOCK_TIMEOUT_SECONDS)
        assert await _marks() == ["deepest"]


@pytest.mark.asyncio
async def test_run_if_leader_body_opens_a_session_while_the_caller_holds_one(tmp_path, monkeypatch) -> None:
    """``run_if_leader`` runs the body as another task; the caller's open session must not starve it."""
    async with _file_sqlite_background_sessions(tmp_path, monkeypatch):
        monkeypatch.setattr(
            leader_election_module,
            "get_settings",
            lambda: SimpleNamespace(leader_election_enabled=True, leader_election_ttl_seconds=30),
        )
        election = leader_election_module.LeaderElection(leader_id="node-a")

        async def body() -> str:
            await _write_mark("leader-body")
            return "ran"

        async def scheduler_tick() -> str | None:
            async with get_background_session() as session:
                await session.execute(text("SELECT count(*) FROM marks"))
                return await election.run_if_leader(body)

        try:
            assert await asyncio.wait_for(scheduler_tick(), timeout=_DEADLOCK_TIMEOUT_SECONDS) == "ran"
        finally:
            await election.release()
        assert await _marks() == ["leader-body"]


@pytest.mark.asyncio
async def test_sequential_sessions_reuse_a_retained_connection(tmp_path, monkeypatch) -> None:
    """The pool keeps #177's gain: back-to-back sessions do not open a new connection each."""
    async with _file_sqlite_background_sessions(tmp_path, monkeypatch) as factory:
        engine = factory.kw["bind"]
        opened = 0

        def _count(_dbapi_connection: object, _record: object) -> None:
            nonlocal opened
            opened += 1

        event.listen(engine.sync_engine, "connect", _count)
        for index in range(20):
            await _write_mark(f"write-{index}")
        assert len(await _marks()) == 20
        assert opened <= 1
