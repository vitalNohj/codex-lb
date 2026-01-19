from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DashboardSettings


def _settings_table_exists(conn: Connection) -> bool:
    inspector = inspect(conn)
    return inspector.has_table("dashboard_settings")


async def run(session: AsyncSession) -> None:
    conn = await session.connection()
    exists = await conn.run_sync(_settings_table_exists)
    if not exists:
        return

    row = await session.get(DashboardSettings, 1)
    if row is not None:
        return

    session.add(
        DashboardSettings(
            id=1,
            sticky_threads_enabled=False,
            prefer_earlier_reset_accounts=False,
        )
    )
    await session.flush()

