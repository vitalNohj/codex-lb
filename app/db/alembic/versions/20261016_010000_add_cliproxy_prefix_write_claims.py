"""add the SQLite lock table for CLIProxyAPI prefix writes

``20261016_000000_add_cliproxy_credential_prefixes`` was edited after some
databases had already applied the original revision. Alembic does not re-run
a stamped revision, so those databases never created
``cliproxy_prefix_write_claims``. This successor creates the lock table when
it is missing. Existing traffic does not read it.

Revision ID: 20261016_010000_add_cliproxy_prefix_write_claims
Revises: 20261016_000000_add_cliproxy_credential_prefixes
Create Date: 2026-10-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261016_010000_add_cliproxy_prefix_write_claims"
down_revision = "20261016_000000_add_cliproxy_credential_prefixes"
branch_labels = None
depends_on = None

_LOCK_TABLE = "cliproxy_prefix_write_claims"


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table(_LOCK_TABLE):
        return
    op.create_table(
        _LOCK_TABLE,
        sa.Column("lock_name", sa.String(), nullable=False),
        sa.Column("holder_id", sa.String(length=100), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("lock_name"),
    )


def downgrade() -> None:
    # Non-destructive no-op. Dropping the lock table while a worker holds
    # the claim would strand that write, and this downgrade cannot tell an
    # empty lock from one in use. Older revisions simply do not know the table.
    pass
