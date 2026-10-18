"""restore CLIProxyAPI capacity routing pins

codex-lb again chooses the CLIProxyAPI credential. Sticky pins for those
credential ids live in ``cliproxy_sticky_sessions`` because
``sticky_sessions.account_id`` references ``accounts.id``. The dashboard
switch defaults on, matching Codex routing. ``request_logs.sidecar_route``
records sticky, rebind, or selected.

Revision ID: 20261018_000000_add_cliproxy_capacity_router
Revises: 20261017_010000_drop_cliproxy_account_router
Create Date: 2026-10-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261018_000000_add_cliproxy_capacity_router"
down_revision = "20261017_010000_drop_cliproxy_account_router"
branch_labels = None
depends_on = None

_SETTINGS = "dashboard_settings"
_LOGS = "request_logs"
_STICKY = "cliproxy_sticky_sessions"
_FLAG = "cliproxy_capacity_routing_enabled"
_ROUTE = "sidecar_route"


def _columns(bind: sa.Connection, table: str) -> set[str]:
    inspector = sa.inspect(bind)
    if not inspector.has_table(table):
        return set()
    return {str(column["name"]) for column in inspector.get_columns(table) if column.get("name") is not None}


def upgrade() -> None:
    bind = op.get_bind()
    if _FLAG not in _columns(bind, _SETTINGS):
        with op.batch_alter_table(_SETTINGS) as batch_op:
            batch_op.add_column(
                sa.Column(_FLAG, sa.Boolean(), nullable=False, server_default=sa.true()),
            )
    if _ROUTE not in _columns(bind, _LOGS):
        with op.batch_alter_table(_LOGS) as batch_op:
            batch_op.add_column(sa.Column(_ROUTE, sa.String(), nullable=True))
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
    if _ROUTE in _columns(bind, _LOGS):
        with op.batch_alter_table(_LOGS) as batch_op:
            batch_op.drop_column(_ROUTE)
    if _FLAG in _columns(bind, _SETTINGS):
        with op.batch_alter_table(_SETTINGS) as batch_op:
            batch_op.drop_column(_FLAG)
