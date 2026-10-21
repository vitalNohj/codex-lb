"""add dashboard card and section visibility

Revision ID: 20261021_010000_add_dashboard_layout
Revises: 20261021_000000_add_lifetime_api_key_limit_window
Create Date: 2026-10-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

from app.modules.settings.dashboard_layout import sql_dashboard_layout_default

revision = "20261021_010000_add_dashboard_layout"
down_revision = "20261021_000000_add_lifetime_api_key_limit_window"
branch_labels = None
depends_on = None

_COLUMN_NAME = "dashboard_layout_json"


def _columns(connection: Connection, table_name: str) -> set[str]:
    inspector = sa.inspect(connection)
    if not inspector.has_table(table_name):
        return set()
    return {str(column["name"]) for column in inspector.get_columns(table_name) if column.get("name") is not None}


def upgrade() -> None:
    bind = op.get_bind()
    dashboard_columns = _columns(bind, "dashboard_settings")
    if not dashboard_columns or _COLUMN_NAME in dashboard_columns:
        return
    with op.batch_alter_table("dashboard_settings") as batch_op:
        batch_op.add_column(
            sa.Column(
                _COLUMN_NAME,
                sa.Text(),
                nullable=False,
                server_default=sa.literal_column(sql_dashboard_layout_default()),
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    dashboard_columns = _columns(bind, "dashboard_settings")
    if _COLUMN_NAME not in dashboard_columns:
        return
    with op.batch_alter_table("dashboard_settings") as batch_op:
        batch_op.drop_column(_COLUMN_NAME)
