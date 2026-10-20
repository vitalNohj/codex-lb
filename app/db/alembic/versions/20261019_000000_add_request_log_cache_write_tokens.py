"""record prompt-cache write tokens and their cost on request logs

Claude through CLIProxyAPI reports prompt-cache writes inside the prompt token
count. ``request_logs.cache_write_input_tokens`` stores them so the row can be
priced at the cache-write rate instead of as plain input, and
``request_logs.cache_write_input_cost_usd`` stores the part of a
catalog-calculated ``cost_usd`` those writes cost, so the request details can
show it without re-pricing the row from the static table. Existing rows keep
NULL in both: their writes were never reported to codex-lb, and their persisted
costs stay as written.

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
_COLUMNS: tuple[tuple[str, type[sa.Integer] | type[sa.Float]], ...] = (
    ("cache_write_input_tokens", sa.Integer),
    ("cache_write_input_cost_usd", sa.Float),
)


def _columns(bind: sa.Connection, table: str) -> set[str]:
    inspector = sa.inspect(bind)
    if not inspector.has_table(table):
        return set()
    return {str(column["name"]) for column in inspector.get_columns(table) if column.get("name") is not None}


def upgrade() -> None:
    existing = _columns(op.get_bind(), _LOGS)
    missing = [(name, column_type) for name, column_type in _COLUMNS if name not in existing]
    if not missing:
        return
    with op.batch_alter_table(_LOGS) as batch_op:
        for name, column_type in missing:
            batch_op.add_column(sa.Column(name, column_type(), nullable=True))


def downgrade() -> None:
    """Keep both columns and the values application traffic wrote to them.

    After the upgrade every Claude request log row stores its cache-write
    tokens and their cost, and nothing tells those values apart from ones this
    revision wrote (it writes none), so dropping the columns would destroy
    request history. Running ``upgrade()`` again reuses them.

    Code older than this revision does not declare the columns, and its
    startup schema check reports them as drift. Drop
    ``request_logs.cache_write_input_tokens`` and
    ``request_logs.cache_write_input_cost_usd`` by hand before starting such
    code.
    """

    return
