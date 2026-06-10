"""add claude sidecar quota polling

Revision ID: 20260611_000000_add_claude_sidecar_quota_polling
Revises: 20260610_090000_add_claude_sidecar_dashboard_settings
Create Date: 2026-06-11 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision = "20260611_000000_add_claude_sidecar_quota_polling"
down_revision = "20260610_090000_add_claude_sidecar_dashboard_settings"
branch_labels = None
depends_on = None

_TABLE_NAME = "dashboard_settings"


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
        if "claude_sidecar_management_key_encrypted" not in columns:
            batch_op.add_column(
                sa.Column("claude_sidecar_management_key_encrypted", sa.LargeBinary(), nullable=True)
            )
        if "claude_sidecar_quota_poll_interval_seconds" not in columns:
            batch_op.add_column(
                sa.Column(
                    "claude_sidecar_quota_poll_interval_seconds",
                    sa.Float(),
                    server_default=sa.text("60.0"),
                    nullable=False,
                )
            )
        if "claude_sidecar_quota_state_json" not in columns:
            batch_op.add_column(sa.Column("claude_sidecar_quota_state_json", sa.Text(), nullable=True))
        if "claude_sidecar_quota_checked_at" not in columns:
            batch_op.add_column(sa.Column("claude_sidecar_quota_checked_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    columns = _columns(bind, _TABLE_NAME)
    if not columns:
        return
    with op.batch_alter_table(_TABLE_NAME) as batch_op:
        for column_name in (
            "claude_sidecar_quota_checked_at",
            "claude_sidecar_quota_state_json",
            "claude_sidecar_quota_poll_interval_seconds",
            "claude_sidecar_management_key_encrypted",
        ):
            if column_name in columns:
                batch_op.drop_column(column_name)
