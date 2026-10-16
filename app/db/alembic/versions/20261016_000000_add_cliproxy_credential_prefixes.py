"""add the codex-lb CLIProxyAPI credential prefix registry

CLIProxyAPI v8.0.30 does not return ``prefix`` from the auth-file list, so
the panel stores the prefix it assigned. The registry starts empty. A second
table is the SQLite lock that keeps a prefix PATCH and its registry commit
in one order across workers. Databases that already applied an earlier copy
of this revision get that lock table from
``20261016_010000_add_cliproxy_prefix_write_claims`` instead. Existing traffic
does not read either table.

Revision ID: 20261016_000000_add_cliproxy_credential_prefixes
Revises: 20261013_000000_add_dashboard_hourly_rollup_retention
Create Date: 2026-10-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261016_000000_add_cliproxy_credential_prefixes"
down_revision = "20261013_000000_add_dashboard_hourly_rollup_retention"
branch_labels = None
depends_on = None

_TABLE = "cliproxy_credential_prefixes"
_LOCK_TABLE = "cliproxy_prefix_write_claims"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(_TABLE):
        op.create_table(
            _TABLE,
            sa.Column("credential_name", sa.String(), nullable=False),
            sa.Column("auth_index", sa.String(), nullable=True),
            sa.Column("prefix", sa.String(length=32), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("credential_name"),
            sa.UniqueConstraint("prefix", name="uq_cliproxy_credential_prefixes_prefix"),
        )
    if not inspector.has_table(_LOCK_TABLE):
        op.create_table(
            _LOCK_TABLE,
            sa.Column("lock_name", sa.String(), nullable=False),
            sa.Column("holder_id", sa.String(length=100), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("lock_name"),
        )


def downgrade() -> None:
    # Non-destructive no-op. This table is the only copy of prefixes the
    # panel assigned. Dropping it would forget those assignments, and this
    # downgrade cannot tell a migration-created empty table from one the
    # panel has written. Older revisions simply do not know the table.
    pass
