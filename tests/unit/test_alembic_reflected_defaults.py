"""SQLite batch rebuilds must keep reflected server defaults byte-identical.

``batch_alter_table`` on SQLite reflects the table and recreates it. A
reflected default such as ``dashboard_settings.dashboard_layout_json``
(``'{"requests":true,...}'``) used to come back from that rebuild as
``'{"requests"NULL,...}'`` because SQLAlchemy reads ``:true`` inside ``text()``
as a bind parameter. Upstream's later batch migrations on ``dashboard_settings``
(for example ``20260908_000000_replace_upstream_stream_transport_default_sentinel``)
would then corrupt the fork's column default and fail the schema drift check.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Table, event

from app.db.alembic.reflection import escape_reflected_default_binds, reflected_default_escaping
from app.modules.settings.dashboard_layout import DEFAULT_DASHBOARD_LAYOUT_JSON, sql_dashboard_layout_default

pytestmark = pytest.mark.unit

_TABLE = "dashboard_settings"


def _stored_default(engine: sa.Engine, column: str) -> str | None:
    with engine.connect() as connection:
        rows = connection.exec_driver_sql(f"PRAGMA table_info('{_TABLE}')").fetchall()
    return next(row[4] for row in rows if row[1] == column)


def _seed(engine: sa.Engine) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql(
            f"CREATE TABLE {_TABLE} (id VARCHAR NOT NULL PRIMARY KEY, "
            "upstream_stream_transport VARCHAR NOT NULL DEFAULT 'default', "
            f"dashboard_layout_json TEXT NOT NULL DEFAULT {sql_dashboard_layout_default()}, "
            "pg_cast_default TEXT NOT NULL DEFAULT 'a::b', "
            "escaped_default TEXT NOT NULL DEFAULT 'x\\:y')"
        )


def _rebuild_unrelated_column(engine: sa.Engine) -> None:
    with engine.begin() as connection:
        operations = Operations(MigrationContext.configure(connection, opts={"render_as_batch": True}))
        with operations.batch_alter_table(_TABLE) as batch_op:
            batch_op.alter_column(
                "upstream_stream_transport",
                existing_type=sa.String(),
                existing_nullable=False,
                server_default=sa.text("'auto'"),
            )


def test_batch_rebuild_keeps_json_default_with_escaping(tmp_path: Path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'batch.db'}")
    _seed(engine)

    with reflected_default_escaping():
        _rebuild_unrelated_column(engine)

    assert _stored_default(engine, "dashboard_layout_json") == sql_dashboard_layout_default()
    assert _stored_default(engine, "upstream_stream_transport") == "'auto'"
    # Colons that are not bind parameters are left exactly as they were.
    assert _stored_default(engine, "pg_cast_default") == "'a::b'"
    assert _stored_default(engine, "escaped_default") == "'x\\:y'"
    with engine.begin() as connection:
        connection.exec_driver_sql(f"INSERT INTO {_TABLE} (id) VALUES ('1')")
        stored = connection.exec_driver_sql(f"SELECT dashboard_layout_json FROM {_TABLE}").scalar_one()
    assert stored == DEFAULT_DASHBOARD_LAYOUT_JSON


def test_batch_rebuild_without_escaping_corrupts_json_default(tmp_path: Path) -> None:
    """Pins the SQLAlchemy behaviour the hook exists for; if this starts
    passing without the hook, the hook can be retired."""

    engine = sa.create_engine(f"sqlite:///{tmp_path / 'batch.db'}")
    _seed(engine)

    _rebuild_unrelated_column(engine)

    assert "NULL" in (_stored_default(engine, "dashboard_layout_json") or "")


def test_escaping_is_scoped_to_the_migration_run() -> None:
    assert not event.contains(Table, "column_reflect", escape_reflected_default_binds)
    with reflected_default_escaping():
        assert event.contains(Table, "column_reflect", escape_reflected_default_binds)
        with reflected_default_escaping():
            assert event.contains(Table, "column_reflect", escape_reflected_default_binds)
        # A nested run does not remove the outer run's hook.
        assert event.contains(Table, "column_reflect", escape_reflected_default_binds)
    assert not event.contains(Table, "column_reflect", escape_reflected_default_binds)
