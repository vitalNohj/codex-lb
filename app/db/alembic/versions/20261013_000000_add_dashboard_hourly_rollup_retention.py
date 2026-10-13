"""add dashboard hourly-rollup retention setting

Revision ID: 20261013_000000_add_dashboard_hourly_rollup_retention
Revises: 20261012_000000_add_daily_usage_rollups
Create Date: 2026-10-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision = "20261013_000000_add_dashboard_hourly_rollup_retention"
down_revision = "20261012_000000_add_daily_usage_rollups"
branch_labels = None
depends_on = None

_COLUMN_NAME = "hourly_rollup_retention_days"


def _columns(connection: Connection, table_name: str) -> set[str]:
    inspector = sa.inspect(connection)
    if not inspector.has_table(table_name):
        return set()
    return {str(column["name"]) for column in inspector.get_columns(table_name) if column.get("name") is not None}


def upgrade() -> None:
    bind = op.get_bind()
    dashboard_columns = _columns(bind, "dashboard_settings")
    if not dashboard_columns:
        return
    with op.batch_alter_table("dashboard_settings") as batch_op:
        if _COLUMN_NAME not in dashboard_columns:
            batch_op.add_column(sa.Column(_COLUMN_NAME, sa.Integer(), nullable=True))


def downgrade() -> None:
    # Preserve configured values; this downgrade cannot distinguish
    # migration-owned data from legitimate application settings (Kody rule:
    # Do Not Destructively Downgrade Data Without Write Provenance). The
    # column is nullable and inert at older revisions, so leaving it in
    # place keeps operator settings intact without schema drift for the
    # current ORM.
    pass
