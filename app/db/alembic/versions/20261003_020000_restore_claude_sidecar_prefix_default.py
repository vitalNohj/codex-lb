"""restore the declared CLIProxyAPI model prefix server default

Revision ID: 20261003_020000_restore_claude_sidecar_prefix_default
Revises: 20261003_010000_backfill_gpt_6_1_sol_costs
Create Date: 2026-10-03 02:00:00.000000

ORM metadata has declared ``claude``, ``cp-`` and ``cp_`` as the server default
of ``dashboard_settings.claude_sidecar_model_prefixes_json`` since the sidecar
routing settings were unified, but that revision set the column default to
``'[]'``. The startup schema drift check therefore failed on PostgreSQL, and an
SQLite-only drift ignore hid the same mismatch on SQLite. This revision sets the
declared default on every backend. Existing settings rows keep the prefixes they
already store; only rows inserted without a value are affected.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision = "20261003_020000_restore_claude_sidecar_prefix_default"
down_revision = "20261003_010000_backfill_gpt_6_1_sol_costs"
branch_labels = None
depends_on = None

_TABLE_NAME = "dashboard_settings"
_COLUMN_NAME = "claude_sidecar_model_prefixes_json"
# Frozen copy of the ORM server default; a migration must not import live models.
_DECLARED_DEFAULT = (
    '\'[{"prefix": "claude", "strip": false}, {"prefix": "cp-", "strip": true}, {"prefix": "cp_", "strip": true}]\''
)
_PREVIOUS_DEFAULT = "'[]'"


def _has_column(connection: Connection) -> bool:
    inspector = sa.inspect(connection)
    if not inspector.has_table(_TABLE_NAME):
        return False
    return any(column.get("name") == _COLUMN_NAME for column in inspector.get_columns(_TABLE_NAME))


def _set_server_default(default: str) -> None:
    if not _has_column(op.get_bind()):
        return
    with op.batch_alter_table(_TABLE_NAME) as batch_op:
        batch_op.alter_column(_COLUMN_NAME, server_default=sa.text(default), existing_type=sa.Text())


def upgrade() -> None:
    _set_server_default(_DECLARED_DEFAULT)


def downgrade() -> None:
    _set_server_default(_PREVIOUS_DEFAULT)
