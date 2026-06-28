"""add sidecar default reasoning effort dashboard settings

Revision ID: 20260621_000000_add_sidecar_default_reasoning_efforts
Revises: 20260619_020000_merge_ollama_and_guest_heads
Create Date: 2026-06-21 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision = "20260621_000000_add_sidecar_default_reasoning_efforts"
down_revision = "20260619_020000_merge_ollama_and_guest_heads"
branch_labels = None
depends_on = None

_TABLE_NAME = "dashboard_settings"
_COLUMNS = (
    "claude_sidecar_default_reasoning_effort",
    "openrouter_sidecar_default_reasoning_effort",
    "omniroute_sidecar_default_reasoning_effort",
    "ollama_sidecar_default_reasoning_effort",
)


def _columns(connection: Connection, table_name: str) -> set[str]:
    inspector = sa.inspect(connection)
    if not inspector.has_table(table_name):
        return set()
    return {str(column["name"]) for column in inspector.get_columns(table_name) if column.get("name") is not None}


def upgrade() -> None:
    bind = op.get_bind()
    columns = _columns(bind, _TABLE_NAME)
    if not columns:
        return
    with op.batch_alter_table(_TABLE_NAME) as batch_op:
        for column_name in _COLUMNS:
            if column_name not in columns:
                batch_op.add_column(sa.Column(column_name, sa.String(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    columns = _columns(bind, _TABLE_NAME)
    if not columns:
        return
    with op.batch_alter_table(_TABLE_NAME) as batch_op:
        for column_name in reversed(_COLUMNS):
            if column_name in columns:
                batch_op.drop_column(column_name)
