"""add claude sidecar usage estimates

Revision ID: 20260611_010000_add_claude_sidecar_usage_estimates
Revises: 20260611_000000_add_claude_sidecar_quota_polling
Create Date: 2026-06-11 01:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision = "20260611_010000_add_claude_sidecar_usage_estimates"
down_revision = "20260611_000000_add_claude_sidecar_quota_polling"
branch_labels = None
depends_on = None

_SETTINGS_TABLE = "dashboard_settings"
_USAGE_TABLE = "claude_sidecar_usage_events"


def _columns(connection: Connection, table_name: str) -> set[str]:
    inspector = sa.inspect(connection)
    if not inspector.has_table(table_name):
        return set()
    return {str(column["name"]) for column in inspector.get_columns(table_name) if column.get("name") is not None}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(_USAGE_TABLE):
        op.create_table(
            _USAGE_TABLE,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("request_id", sa.String(), nullable=False),
            sa.Column("timestamp", sa.DateTime(), nullable=False),
            sa.Column("auth_index", sa.String(), nullable=True),
            sa.Column("source", sa.String(), nullable=True),
            sa.Column("provider", sa.String(), nullable=True),
            sa.Column("model", sa.String(), nullable=True),
            sa.Column("alias", sa.String(), nullable=True),
            sa.Column("endpoint", sa.String(), nullable=True),
            sa.Column("auth_type", sa.String(), nullable=True),
            sa.Column("input_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
            sa.Column("output_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
            sa.Column("reasoning_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
            sa.Column("cached_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
            sa.Column("total_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
            sa.Column("failed", sa.Boolean(), server_default=sa.false(), nullable=False),
            sa.Column("latency_ms", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("request_id", name="uq_claude_sidecar_usage_events_request_id"),
        )
    existing_indexes = {index["name"] for index in inspector.get_indexes(_USAGE_TABLE)}
    if "idx_claude_sidecar_usage_auth_time" not in existing_indexes:
        op.create_index(
            "idx_claude_sidecar_usage_auth_time",
            _USAGE_TABLE,
            ["auth_index", "timestamp"],
        )
    if "idx_claude_sidecar_usage_time" not in existing_indexes:
        op.create_index("idx_claude_sidecar_usage_time", _USAGE_TABLE, ["timestamp"])

    columns = _columns(bind, _SETTINGS_TABLE)
    if not columns:
        return
    with op.batch_alter_table(_SETTINGS_TABLE) as batch_op:
        if "claude_sidecar_auth_plans_json" not in columns:
            batch_op.add_column(sa.Column("claude_sidecar_auth_plans_json", sa.Text(), nullable=True))
        if "claude_sidecar_usage_poll_interval_seconds" not in columns:
            batch_op.add_column(
                sa.Column(
                    "claude_sidecar_usage_poll_interval_seconds",
                    sa.Float(),
                    server_default=sa.text("15.0"),
                    nullable=False,
                )
            )
        if "claude_sidecar_usage_queue_batch_size" not in columns:
            batch_op.add_column(
                sa.Column(
                    "claude_sidecar_usage_queue_batch_size",
                    sa.Integer(),
                    server_default=sa.text("100"),
                    nullable=False,
                )
            )
        if "claude_sidecar_usage_collection_enabled" not in columns:
            batch_op.add_column(
                sa.Column(
                    "claude_sidecar_usage_collection_enabled",
                    sa.Boolean(),
                    server_default=sa.true(),
                    nullable=False,
                )
            )


def downgrade() -> None:
    bind = op.get_bind()
    columns = _columns(bind, _SETTINGS_TABLE)
    if columns:
        with op.batch_alter_table(_SETTINGS_TABLE) as batch_op:
            for column_name in (
                "claude_sidecar_usage_collection_enabled",
                "claude_sidecar_usage_queue_batch_size",
                "claude_sidecar_usage_poll_interval_seconds",
                "claude_sidecar_auth_plans_json",
            ):
                if column_name in columns:
                    batch_op.drop_column(column_name)
    inspector = sa.inspect(bind)
    if inspector.has_table(_USAGE_TABLE):
        existing_indexes = {index["name"] for index in inspector.get_indexes(_USAGE_TABLE)}
        if "idx_claude_sidecar_usage_time" in existing_indexes:
            op.drop_index("idx_claude_sidecar_usage_time", table_name=_USAGE_TABLE)
        if "idx_claude_sidecar_usage_auth_time" in existing_indexes:
            op.drop_index("idx_claude_sidecar_usage_auth_time", table_name=_USAGE_TABLE)
        op.drop_table(_USAGE_TABLE)
