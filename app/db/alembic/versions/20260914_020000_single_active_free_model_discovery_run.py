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

If duplicate ``running`` rows already exist the index cannot be created. This
migration then **fails with a concrete error and changes nothing**. An earlier
draft rewrote the older rows to ``failed`` automatically; that was wrong,
because a second ``running`` row is not proven abandoned and ``downgrade()``
could not restore the rewritten statuses. Which run to keep is an operator
decision about live work, so it is surfaced rather than guessed.

Refusal is only useful if the rollout actually stops on it. **On default
configuration** ``app/db/session.py`` runs startup migrations
(``database_migrate_on_startup``, default ``True``) and re-raises on failure
(``database_migrations_fail_fast``, default ``True``), so startup aborts rather
than continuing into the new service. That is the default-config path read from
source only; it does **not** establish the effective settings of any particular
deployment. Confirming that the target deployment stops on migration failure -
rather than proceeding with the old or a partially updated service - remains a
pre-deployment requirement, not something this migration can guarantee.
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

    # Refuse rather than repair. Creating the index is mandatory - it is the
    # only thing that actually closes the start race - but no run row is
    # rewritten to make room for it.
    duplicate_ids = [
        row[0]
        for row in bind.execute(
            sa.text(
                f"SELECT id FROM {_RUNS_TABLE} WHERE status = 'running' ORDER BY started_at DESC"
            )
        ).fetchall()
    ]
    if len(duplicate_ids) > 1:
        raise RuntimeError(
            "Cannot enforce a single active free-model discovery run: "
            f"{len(duplicate_ids)} runs are currently 'running' "
            f"(ids: {', '.join(duplicate_ids)}). "
            "Decide which run should remain active and finish or cancel the others "
            "through the dashboard, then re-run this migration. "
            "No rows were changed."
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
