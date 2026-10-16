"""add encrypted CLIProxyAPI config snapshots

The panel keeps the previous config.yaml in codex-lb so a replace can roll
back without reading a copy off the CLIProxyAPI host. The YAML is Fernet
ciphertext. A second empty table leases config writes so two workers cannot
replace that snapshot at the same time.

Revision ID: 20261016_000000_add_cliproxy_config_snapshots
Revises: 20261013_000000_add_dashboard_hourly_rollup_retention
Create Date: 2026-10-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261016_000000_add_cliproxy_config_snapshots"
down_revision = "20261013_000000_add_dashboard_hourly_rollup_retention"
branch_labels = None
depends_on = None

_TABLE = "cliproxy_config_snapshots"
_CLAIMS = "cliproxy_config_write_claims"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(_TABLE):
        op.create_table(
            _TABLE,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
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


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table(_TABLE):
        pending = bind.execute(sa.text("SELECT COUNT(*) FROM cliproxy_config_snapshots")).scalar()
        if pending:
            raise RuntimeError(
                f"cannot downgrade {revision}: {pending} CLIProxyAPI config snapshot(s) still hold "
                "the previous file needed for rollback; restore or discard them before downgrading"
            )
        op.drop_table(_TABLE)
    if inspector.has_table(_CLAIMS):
        op.drop_table(_CLAIMS)
