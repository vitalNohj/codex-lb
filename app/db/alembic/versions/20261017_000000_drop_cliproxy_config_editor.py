"""drop the CLIProxyAPI whole-file config editor tables

The panel no longer views or replaces config.yaml. The encrypted snapshots
and the write lease existed only for that editor, so leaving the tables would
keep ciphertext with no reader.

Revision ID: 20261017_000000_drop_cliproxy_config_editor
Revises: 20261016_020000_add_cliproxy_routing_attribution
Create Date: 2026-10-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261017_000000_drop_cliproxy_config_editor"
down_revision = "20261016_020000_add_cliproxy_routing_attribution"
branch_labels = None
depends_on = None

_SNAPSHOTS = "cliproxy_config_snapshots"
_CLAIMS = "cliproxy_config_write_claims"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table(_SNAPSHOTS):
        op.drop_table(_SNAPSHOTS)
    if inspector.has_table(_CLAIMS):
        op.drop_table(_CLAIMS)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(_SNAPSHOTS):
        op.create_table(
            _SNAPSHOTS,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("upstream_key", sa.String(length=64), nullable=False),
            sa.Column("content_sha256", sa.String(length=64), nullable=False),
            sa.Column("yaml_ciphertext", sa.LargeBinary(), nullable=False),
            sa.Column("action", sa.String(length=32), nullable=False),
        )
    if not inspector.has_table(_CLAIMS):
        op.create_table(
            _CLAIMS,
            sa.Column("lock_key", sa.String(length=64), primary_key=True),
            sa.Column("holder_id", sa.String(length=64), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        )
