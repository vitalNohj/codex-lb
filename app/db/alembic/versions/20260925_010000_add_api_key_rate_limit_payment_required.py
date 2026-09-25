"""add the per-API-key usage-exhaustion 402 toggle

The column defaults to false, so every existing API key keeps answering usage
exhaustion with 429 until an operator enables the toggle on it.

Revision ID: 20260925_010000_add_api_key_rate_limit_payment_required
Revises: 20260925_000000_fold_nvidia_into_openai_compat
Create Date: 2026-09-25 01:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision = "20260925_010000_add_api_key_rate_limit_payment_required"
down_revision = "20260925_000000_fold_nvidia_into_openai_compat"
branch_labels = None
depends_on = None

_TABLE = "api_keys"
_COLUMN = "rate_limit_as_payment_required"


def _columns(connection: Connection) -> set[str]:
    inspector = sa.inspect(connection)
    if not inspector.has_table(_TABLE):
        return set()
    return {str(column["name"]) for column in inspector.get_columns(_TABLE) if column.get("name") is not None}


def upgrade() -> None:
    connection = op.get_bind()
    if _COLUMN in _columns(connection):
        return
    with op.batch_alter_table(_TABLE) as batch_op:
        batch_op.add_column(sa.Column(_COLUMN, sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    connection = op.get_bind()
    if _COLUMN not in _columns(connection):
        return
    with op.batch_alter_table(_TABLE) as batch_op:
        batch_op.drop_column(_COLUMN)
