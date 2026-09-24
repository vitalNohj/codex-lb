"""Behavioral tests for the single-active discovery-run migration.

The migration must never repair data to make room for its index: a second
``running`` row is not proven abandoned, and ``downgrade()`` cannot restore a
rewritten status. It must refuse instead, leaving every row byte-identical, and
it must still create the index on a clean table because that index is the only
thing that closes the start race.

These drive the real ``upgrade()`` against a synthetic SQLite database rather
than asserting on source text, which cannot show refusal actually happens.

NOT EXECUTED in the pass that added them - see the PR description.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from importlib import import_module
from pathlib import Path

import pytest
import sqlalchemy as sa

migration = import_module("app.db.alembic.versions.20260914_020000_single_active_free_model_discovery_run")

pytestmark = pytest.mark.unit

_RUNS_TABLE = "free_model_discovery_runs"
_INDEX_NAME = "uq_free_model_discovery_runs_single_active"

_CREATE_RUNS = f"""
CREATE TABLE {_RUNS_TABLE} (
    id VARCHAR NOT NULL PRIMARY KEY,
    status VARCHAR(16) NOT NULL,
    started_at DATETIME NOT NULL,
    finished_at DATETIME,
    deadline_at DATETIME NOT NULL,
    cancel_requested BOOLEAN NOT NULL DEFAULT 0,
    pacing_floor_seconds FLOAT NOT NULL,
    pacing_cap_seconds FLOAT NOT NULL,
    max_attempts_per_item INTEGER NOT NULL,
    error_message TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""


def _seed_run(con: sqlite3.Connection, run_id: str, status: str, started_at: datetime) -> None:
    con.execute(
        f"INSERT INTO {_RUNS_TABLE} "
        "(id, status, started_at, deadline_at, cancel_requested, pacing_floor_seconds, "
        " pacing_cap_seconds, max_attempts_per_item, error_message) "
        "VALUES (?, ?, ?, ?, 0, 1.0, 2.0, 1, NULL)",
        (run_id, status, started_at.isoformat(), (started_at + timedelta(hours=1)).isoformat()),
    )


def _all_rows(db_path: Path) -> list[tuple]:
    con = sqlite3.connect(db_path)
    try:
        return sorted(con.execute(f"SELECT * FROM {_RUNS_TABLE}").fetchall())
    finally:
        con.close()


def _indexes(db_path: Path) -> list[str]:
    con = sqlite3.connect(db_path)
    try:
        return [
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=?",
                (_RUNS_TABLE,),
            )
        ]
    finally:
        con.close()


def _run_upgrade(db_path: Path) -> None:
    """Invoke the real ``upgrade()`` with alembic's op context bound to ``db_path``."""

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.upgrade()
    engine.dispose()


@pytest.fixture()
def seeded_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "discovery.db"
    con = sqlite3.connect(db_path)
    try:
        con.execute(_CREATE_RUNS)
        con.commit()
    finally:
        con.close()
    return db_path


def test_upgrade_refuses_duplicate_running_rows_and_changes_nothing(seeded_db: Path) -> None:
    now = datetime(2026, 9, 14, 12, 0, 0)
    con = sqlite3.connect(seeded_db)
    try:
        _seed_run(con, "older-running", "running", now - timedelta(hours=2))
        _seed_run(con, "newer-running", "running", now)
        _seed_run(con, "done", "completed", now - timedelta(days=1))
        con.commit()
    finally:
        con.close()

    before = _all_rows(seeded_db)

    with pytest.raises(RuntimeError) as excinfo:
        _run_upgrade(seeded_db)

    # The operator is told which runs collide, not left guessing.
    message = str(excinfo.value)
    assert "older-running" in message
    assert "newer-running" in message
    assert "No rows were changed." in message

    # Every column of every row is byte-identical: no status was rewritten and
    # no error_message was stamped onto a run that may still be live.
    assert _all_rows(seeded_db) == before
    # And no index was created, so nothing recorded a successful migration.
    assert _INDEX_NAME not in _indexes(seeded_db)


def test_upgrade_creates_the_mandatory_index_on_a_clean_table(seeded_db: Path) -> None:
    now = datetime(2026, 9, 14, 12, 0, 0)
    con = sqlite3.connect(seeded_db)
    try:
        _seed_run(con, "only-running", "running", now)
        _seed_run(con, "finished-a", "completed", now - timedelta(days=1))
        # Two terminal rows share a status: the index must be partial, not a
        # plain unique constraint, or retained history would collide.
        _seed_run(con, "finished-b", "completed", now - timedelta(days=2))
        con.commit()
    finally:
        con.close()

    _run_upgrade(seeded_db)

    assert _INDEX_NAME in _indexes(seeded_db)


def test_created_index_rejects_a_second_active_run(seeded_db: Path) -> None:
    now = datetime(2026, 9, 14, 12, 0, 0)
    con = sqlite3.connect(seeded_db)
    try:
        _seed_run(con, "only-running", "running", now)
        con.commit()
    finally:
        con.close()

    _run_upgrade(seeded_db)

    con = sqlite3.connect(seeded_db)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            _seed_run(con, "second-running", "running", now + timedelta(minutes=1))
            con.commit()
    finally:
        con.close()
