"""add daily usage rollup table and fold watermark

DDL only — the daily lifetime store is created empty and backfill is owned
entirely by the runtime daily fold pass (which folds the permanent hourly
rollups, never raw), so this revision never blocks startup. The watermark
column backfills existing state rows to the epoch, so the new fold starts
its own paced backfill from zero without touching the lifetime, hourly, or
conversation watermarks.

Revision ID: 20261012_000000_add_daily_usage_rollups
Revises: 20261008_020000_restore_claude_sidecar_prefix_default
Create Date: 2026-10-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision = "20261012_000000_add_daily_usage_rollups"
down_revision = "20261008_020000_restore_claude_sidecar_prefix_default"
branch_labels = None
depends_on = None

_TABLE = "request_usage_daily_rollups"
_STATE_TABLE = "account_usage_rollup_state"
_WATERMARK_COLUMN = "daily_folded_through"


def _columns(connection: Connection, table_name: str) -> set[str]:
    inspector = sa.inspect(connection)
    if not inspector.has_table(table_name):
        return set()
    return {str(column["name"]) for column in inspector.get_columns(table_name) if column.get("name") is not None}


def upgrade() -> None:
    bind = op.get_bind()

    if not sa.inspect(bind).has_table(_TABLE):
        op.create_table(
            _TABLE,
            sa.Column("day_epoch", sa.BigInteger(), nullable=False),
            sa.Column("account_id", sa.String(), nullable=False),
            sa.Column("api_key_id", sa.String(), nullable=False),
            sa.Column("model", sa.String(), nullable=False),
            sa.Column("service_tier", sa.String(), nullable=False),
            sa.Column("request_kind", sa.String(), nullable=False),
            sa.Column("is_deleted", sa.Boolean(), server_default=sa.false(), nullable=False),
            sa.Column("request_count", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
            sa.Column("error_count", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
            sa.Column("cancelled_count", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
            sa.Column("input_tokens", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
            sa.Column("output_tokens", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
            sa.Column("reasoning_tokens", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
            sa.Column("output_or_reasoning_tokens", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
            sa.Column("cached_input_tokens", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
            sa.Column("cached_input_tokens_clamped", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
            sa.Column("cost_usd", sa.Float(), server_default=sa.text("0"), nullable=False),
            sa.Column("cost_count", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
            sa.PrimaryKeyConstraint(
                "day_epoch", "account_id", "api_key_id", "model", "service_tier", "request_kind", "is_deleted"
            ),
        )

    state_columns = _columns(bind, _STATE_TABLE)
    if state_columns and _WATERMARK_COLUMN not in state_columns:
        with op.batch_alter_table(_STATE_TABLE) as batch_op:
            batch_op.add_column(
                sa.Column(
                    _WATERMARK_COLUMN,
                    sa.DateTime(),
                    server_default=sa.text("'1970-01-01 00:00:00'"),
                    nullable=False,
                )
            )


def downgrade() -> None:
    # Non-destructive no-op (Kody rule: Do Not Destructively Downgrade Data
    # Without Write Provenance). The daily table is the permanent lifetime
    # usage store and the watermark drives the daily fold; this downgrade
    # cannot distinguish migration-created objects from data the runtime
    # fold has written since the upgrade, and dropping either would destroy
    # operator history that has no other backing store. Both objects are
    # inert at older revisions (the ORM there simply does not know them).
    pass
