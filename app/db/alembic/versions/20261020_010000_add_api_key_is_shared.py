"""add the per-API-key shared toggle

A shared key is one handed to a friend or client: it sees only its own usage,
limits and expiry, whatever its usage sections say. The column defaults to
false, so every existing key keeps behaving exactly per its usage sections
until an operator turns the toggle on. Usage sections are left untouched, so
turning the toggle off again restores what the key could see before.

Revision ID: 20261020_010000_add_api_key_is_shared
Revises: 20261020_000000_add_api_key_reset_credits_section
Create Date: 2026-10-20 01:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision = "20261020_010000_add_api_key_is_shared"
down_revision = "20261020_000000_add_api_key_reset_credits_section"
branch_labels = None
depends_on = None

_TABLE = "api_keys"
_COLUMN = "is_shared"


def _columns(connection: Connection) -> set[str]:
    inspector = sa.inspect(connection)
    if not inspector.has_table(_TABLE):
        return set()
    return {str(column["name"]) for column in inspector.get_columns(_TABLE) if column.get("name") is not None}


def upgrade() -> None:
    connection = op.get_bind()
    columns = _columns(connection)
    if not columns or _COLUMN in columns:
        return
    with op.batch_alter_table(_TABLE) as batch_op:
        batch_op.add_column(sa.Column(_COLUMN, sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    connection = op.get_bind()
    if _COLUMN not in _columns(connection):
        return
    with op.batch_alter_table(_TABLE) as batch_op:
        batch_op.drop_column(_COLUMN)
