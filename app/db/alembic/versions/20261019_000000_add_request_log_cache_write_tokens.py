"""record prompt-cache write tokens on request logs

Claude through CLIProxyAPI reports prompt-cache writes inside the prompt token
count. ``request_logs.cache_write_input_tokens`` stores them so the row can be
priced at the cache-write rate instead of as plain input. Existing rows keep
NULL: their writes were never reported to codex-lb, and their persisted costs
stay as written.

Revision ID: 20261019_000000_add_request_log_cache_write_tokens
Revises: 20261018_000000_add_cliproxy_capacity_router
Create Date: 2026-10-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261019_000000_add_request_log_cache_write_tokens"
down_revision = "20261018_000000_add_cliproxy_capacity_router"
branch_labels = None
depends_on = None

_LOGS = "request_logs"
_COLUMN = "cache_write_input_tokens"


def _columns(bind: sa.Connection, table: str) -> set[str]:
    inspector = sa.inspect(bind)
    if not inspector.has_table(table):
        return set()
    return {str(column["name"]) for column in inspector.get_columns(table) if column.get("name") is not None}


def upgrade() -> None:
    bind = op.get_bind()
    if _COLUMN in _columns(bind, _LOGS):
        return
    with op.batch_alter_table(_LOGS) as batch_op:
        batch_op.add_column(sa.Column(_COLUMN, sa.Integer(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if _COLUMN not in _columns(bind, _LOGS):
        return
    with op.batch_alter_table(_LOGS) as batch_op:
        batch_op.drop_column(_COLUMN)
