"""add model aliases dashboard setting

Revision ID: 20260628_000000_add_model_aliases
Revises: 20260623_000000_add_request_logs_requested_reasoning_effort
Create Date: 2026-06-28 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision = "20260628_000000_add_model_aliases"
down_revision = "20260623_000000_add_request_logs_requested_reasoning_effort"
branch_labels = None
depends_on = None

_TABLE_NAME = "dashboard_settings"
_COLUMN_NAME = "model_aliases_json"


def _columns(connection: Connection, table_name: str) -> set[str]:
    inspector = sa.inspect(connection)
    if not inspector.has_table(table_name):
        return set()
    return {str(column["name"]) for column in inspector.get_columns(table_name) if column.get("name") is not None}


def upgrade() -> None:
    bind = op.get_bind()
    columns = _columns(bind, _TABLE_NAME)
    if not columns or _COLUMN_NAME in columns:
        return
    with op.batch_alter_table(_TABLE_NAME) as batch_op:
        batch_op.add_column(
            sa.Column(_COLUMN_NAME, sa.Text(), server_default="{}", nullable=False)
        )


def downgrade() -> None:
    bind = op.get_bind()
    columns = _columns(bind, _TABLE_NAME)
    if _COLUMN_NAME not in columns:
        return
    with op.batch_alter_table(_TABLE_NAME) as batch_op:
        batch_op.drop_column(_COLUMN_NAME)
