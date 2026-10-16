"""record the CLIProxyAPI credential chosen for a sidecar request

Dispatch writes ``sidecar_provider`` and ``sidecar_auth_index`` when the
account pool is on. Sticky pins for those credential ids live in
``cliproxy_sticky_sessions`` because ``sticky_sessions.account_id`` references
``accounts.id``.

Revision ID: 20261016_020000_add_cliproxy_routing_attribution
Revises: 20261016_000000_add_cliproxy_config_snapshots
Create Date: 2026-10-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision = "20261016_020000_add_cliproxy_routing_attribution"
down_revision = "20261016_000000_add_cliproxy_config_snapshots"
branch_labels = None
depends_on = None

_LOGS = "request_logs"
_STICKY = "cliproxy_sticky_sessions"
_INDEX = "idx_logs_sidecar_credential"
_LOG_COLUMNS = ("sidecar_provider", "sidecar_auth_index")


def _columns(connection: Connection, table: str) -> set[str]:
    inspector = sa.inspect(connection)
    if not inspector.has_table(table):
        return set()
    return {str(column["name"]) for column in inspector.get_columns(table) if column.get("name") is not None}


def _index_names(connection: Connection, table: str) -> set[str]:
    inspector = sa.inspect(connection)
    if not inspector.has_table(table):
        return set()
    return {str(index["name"]) for index in inspector.get_indexes(table) if index.get("name") is not None}


def upgrade() -> None:
    bind = op.get_bind()
    missing = [name for name in _LOG_COLUMNS if name not in _columns(bind, _LOGS)]
    if missing and sa.inspect(bind).has_table(_LOGS):
        with op.batch_alter_table(_LOGS) as batch_op:
            for name in missing:
                batch_op.add_column(sa.Column(name, sa.String(), nullable=True))
    if sa.inspect(bind).has_table(_LOGS) and _INDEX not in _index_names(bind, _LOGS):
        op.create_index(_INDEX, _LOGS, list(_LOG_COLUMNS))
    if sa.inspect(bind).has_table(_STICKY):
        return
    op.create_table(
        _STICKY,
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("account_id", sa.String(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key", "kind"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table(_STICKY):
        op.drop_table(_STICKY)
    if not sa.inspect(bind).has_table(_LOGS):
        return
    if _INDEX in _index_names(bind, _LOGS):
        op.drop_index(_INDEX, table_name=_LOGS)
    present = [name for name in _LOG_COLUMNS if name in _columns(bind, _LOGS)]
    if not present:
        return
    with op.batch_alter_table(_LOGS) as batch_op:
        for name in present:
            batch_op.drop_column(name)
