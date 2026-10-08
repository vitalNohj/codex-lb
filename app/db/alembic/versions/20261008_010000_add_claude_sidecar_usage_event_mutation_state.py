"""track in-place claude_sidecar_usage_events changes with a trigger-maintained generation

The Claude quota-estimate event cache reads only rows above its id watermark.
That is exact for inserts but blind to an UPDATE or DELETE of a cached row, and
no aggregate fingerprint covers every field the estimates read. A single-row
generation counter, bumped by AFTER UPDATE / AFTER DELETE triggers on SQLite,
tells the cache when to reload. Inserts do not fire the triggers. PostgreSQL
gets the table only; without triggers the cache reads the window in full.

Revision ID: 20261008_010000_add_claude_sidecar_usage_event_mutation_state
Revises: 20261008_000000_merge_usage_history_and_haiku_pin_heads
Create Date: 2026-10-08 01:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261008_010000_add_claude_sidecar_usage_event_mutation_state"
down_revision = "20261008_000000_merge_usage_history_and_haiku_pin_heads"
branch_labels = None
depends_on = None

_TABLE = "claude_sidecar_usage_event_mutation_state"
_EVENTS = "claude_sidecar_usage_events"
_TRIGGERS = (
    ("claude_sidecar_usage_event_mutation_after_update", "UPDATE"),
    ("claude_sidecar_usage_event_mutation_after_delete", "DELETE"),
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
            f"CREATE TRIGGER IF NOT EXISTS {name} AFTER {operation} ON {_EVENTS} "
            f"BEGIN UPDATE {_TABLE} SET generation = generation + 1 WHERE id = 1; END"
        )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name == "sqlite":
        for name, _operation in _TRIGGERS:
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
    if sa.inspect(connection).has_table(_TABLE):
        op.drop_table(_TABLE)
