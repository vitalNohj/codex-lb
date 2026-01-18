from __future__ import annotations

import asyncio
from pathlib import Path
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config.settings import get_settings

DATABASE_URL = get_settings().database_url

engine = create_async_engine(DATABASE_URL, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def _ensure_sqlite_dir(url: str) -> None:
    prefix = "sqlite+aiosqlite:///"
    if not url.startswith(prefix):
        return
    path = url[len(prefix) :]
    if path == ":memory:":
        return
    Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)


async def _safe_rollback(session: AsyncSession) -> None:
    if not session.in_transaction():
        return
    try:
        await asyncio.shield(session.rollback())
    except Exception:
        return


async def _safe_close(session: AsyncSession) -> None:
    try:
        await asyncio.shield(session.close())
    except Exception:
        return


async def get_session() -> AsyncIterator[AsyncSession]:
    session = SessionLocal()
    try:
        yield session
    except BaseException:
        await _safe_rollback(session)
        raise
    finally:
        if session.in_transaction():
            await _safe_rollback(session)
        await _safe_close(session)


async def init_db() -> None:
    from app.db.models import Base

    _ensure_sqlite_dir(DATABASE_URL)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _run_migrations(conn)


async def _run_migrations(conn: AsyncConnection) -> None:
    if conn.dialect.name != "sqlite":
        return
    await _sqlite_add_column_if_missing(conn, "accounts", "chatgpt_account_id", "VARCHAR")


async def _sqlite_add_column_if_missing(
    conn: AsyncConnection,
    table: str,
    column: str,
    column_type: str,
) -> None:
    result = await conn.exec_driver_sql(f"PRAGMA table_info({table})")
    rows = result.fetchall()
    existing = {row[1] for row in rows if len(row) > 1}
    if column in existing:
        return
    await conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")
