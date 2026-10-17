"""drop the CLIProxyAPI credential-prefix registry and sticky pins

codex-lb no longer assigns prefixes or pins a request to one CLIProxyAPI
credential. CLIProxyAPI chooses the account. The request-log columns stay so
older rows keep the auth index they recorded. The status write claim stays.

Revision ID: 20261017_010000_drop_cliproxy_account_router
Revises: 20261017_000000_drop_cliproxy_config_editor
Create Date: 2026-10-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261017_010000_drop_cliproxy_account_router"
down_revision = "20261017_000000_drop_cliproxy_config_editor"
branch_labels = None
depends_on = None

_PREFIXES = "cliproxy_credential_prefixes"
_STICKY = "cliproxy_sticky_sessions"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table(_STICKY):
        op.drop_table(_STICKY)
    if inspector.has_table(_PREFIXES):
        op.drop_table(_PREFIXES)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(_PREFIXES):
        op.create_table(
            _PREFIXES,
            sa.Column("credential_name", sa.String(), nullable=False),
            sa.Column("auth_index", sa.String(), nullable=True),
            sa.Column("prefix", sa.String(length=32), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("credential_name"),
            sa.UniqueConstraint("prefix", name="uq_cliproxy_credential_prefixes_prefix"),
        )
    if not inspector.has_table(_STICKY):
        op.create_table(
            _STICKY,
            sa.Column("key", sa.String(), nullable=False),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("account_id", sa.String(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("key", "kind"),
        )
