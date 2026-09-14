"""enforce at most one running free-model discovery run

Revision ID: 20260914_020000_single_active_free_model_discovery_run
Revises: 20260914_010000_merge_free_model_discovery_and_opencode_go_heads
Create Date: 2026-09-14

The service already refuses to start a second run while one is ``running``,
but that check and the insert are separated by a plan rebuild that performs
provider HTTP calls. Two rapid clicks can both pass the check and both insert,
producing two concurrent sweeps against rate-limited providers.

A partial unique index makes the database the arbiter. Partial rather than a
plain unique constraint because finished runs are retained as history and must
be free to share their terminal statuses; only ``running`` is restricted.

Any pre-existing duplicates are reconciled first - keeping the newest running
run and marking older ones ``failed`` - because the index cannot be created
while duplicates exist. That is a status correction on already-abandoned rows,
not a deletion: no run row and no item row is removed.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260914_020000_single_active_free_model_discovery_run"
down_revision = "20260914_010000_merge_free_model_discovery_and_opencode_go_heads"
branch_labels = None
depends_on = None

_RUNS_TABLE = "free_model_discovery_runs"
_INDEX_NAME = "uq_free_model_discovery_runs_single_active"


def _has_table(bind: sa.engine.Connection, table: str) -> bool:
    return sa.inspect(bind).has_table(table)


def _has_index(bind: sa.engine.Connection, table: str, index: str) -> bool:
    return any(existing["name"] == index for existing in sa.inspect(bind).get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, _RUNS_TABLE):
        return
    if _has_index(bind, _RUNS_TABLE, _INDEX_NAME):
        return

    # Demote any stale extra running rows so the unique index can be built.
    # Keeps the most recently started one, which is the run an operator would
    # still expect to be live.
    bind.execute(
        sa.text(
            f"""
            UPDATE {_RUNS_TABLE}
               SET status = 'failed',
                   error_message = COALESCE(
                       error_message,
                       'Superseded: multiple concurrent runs existed before the single-active guard'
                   )
             WHERE status = 'running'
               AND id NOT IN (
                   SELECT id FROM {_RUNS_TABLE}
                    WHERE status = 'running'
                    ORDER BY started_at DESC
                    LIMIT 1
               )
            """
        )
    )

    op.create_index(
        _INDEX_NAME,
        _RUNS_TABLE,
        ["status"],
        unique=True,
        sqlite_where=sa.text("status = 'running'"),
        postgresql_where=sa.text("status = 'running'"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if _has_table(bind, _RUNS_TABLE) and _has_index(bind, _RUNS_TABLE, _INDEX_NAME):
        op.drop_index(_INDEX_NAME, table_name=_RUNS_TABLE)
