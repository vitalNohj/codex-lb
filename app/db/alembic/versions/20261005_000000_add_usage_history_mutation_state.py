"""track in-place usage_history changes with a trigger-maintained generation

The dashboard's SQLite bulk usage-history cache re-hashed every cached row on
each read to detect corrections and deletes. A single-row generation counter,
bumped by AFTER UPDATE / AFTER DELETE triggers on SQLite, lets it skip that
digest while nothing has changed. Inserts do not fire the triggers. PostgreSQL
gets the table only; its usage-history reads do not use the SQLite cache.

Revision ID: 20261005_000000_add_usage_history_mutation_state
Revises: 20261003_010000_backfill_gpt_6_1_sol_costs
Create Date: 2026-10-05 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261005_000000_add_usage_history_mutation_state"
down_revision = "20261003_010000_backfill_gpt_6_1_sol_costs"
branch_labels = None
depends_on = None

_TABLE = "usage_history_mutation_state"
_TRIGGERS = (
    ("usage_history_mutation_after_update", "UPDATE"),
    ("usage_history_mutation_after_delete", "DELETE"),
)


def upgrade() -> None:
    connection = op.get_bind()
    if not sa.inspect(connection).has_table(_TABLE):
        op.create_table(
            _TABLE,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("generation", sa.Integer(), server_default=sa.text("0"), nullable=False),
        )
    if connection.dialect.name != "sqlite":
        return
    op.execute(f"INSERT OR IGNORE INTO {_TABLE} (id, generation) VALUES (1, 0)")
    for name, operation in _TRIGGERS:
        op.execute(
            f"CREATE TRIGGER IF NOT EXISTS {name} AFTER {operation} ON usage_history "
            f"BEGIN UPDATE {_TABLE} SET generation = generation + 1 WHERE id = 1; END"
        )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name == "sqlite":
        for name, _operation in _TRIGGERS:
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
    if sa.inspect(connection).has_table(_TABLE):
        op.drop_table(_TABLE)
