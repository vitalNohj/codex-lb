"""add encrypted CLIProxyAPI config snapshots

The panel keeps the previous config.yaml in codex-lb so a replace can roll
back without reading a copy off the CLIProxyAPI host. The YAML is Fernet
ciphertext; this revision only creates the empty table.

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


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table(_TABLE):
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("yaml_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(_TABLE):
        return
    pending = bind.execute(sa.text("SELECT COUNT(*) FROM cliproxy_config_snapshots")).scalar()
    if pending:
        raise RuntimeError(
            f"cannot downgrade {revision}: {pending} CLIProxyAPI config snapshot(s) still hold "
            "the previous file needed for rollback; restore or discard them before downgrading"
        )
    op.drop_table(_TABLE)
