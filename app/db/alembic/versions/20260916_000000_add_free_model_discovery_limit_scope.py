"""record the vendor-attributed scope of a discovery rate-limit rejection

Revision ID: 20260916_000000_add_free_model_discovery_limit_scope
Revises: 20260914_020000_single_active_free_model_discovery_run
Create Date: 2026-09-16

Discovery could not tell a provider/account-wide limit from an upstream
model-specific one, because the response headers and typed error metadata that
carry that distinction were discarded at the transport boundary. The classifier
now keeps the vendor's own attribution, and this column persists it per item so
the operator-facing reason survives a restart mid-run.

Purely additive and nullable: existing rows keep NULL, which reads as "no
rate-limit rejection recorded", and every existing reader ignores the column.
No backfill is possible or attempted - the evidence for historical rows was
never captured, and inventing a scope for them is exactly the guess this
change exists to stop.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260916_000000_add_free_model_discovery_limit_scope"
down_revision = "20260914_020000_single_active_free_model_discovery_run"
branch_labels = None
depends_on = None

_ITEMS_TABLE = "free_model_discovery_run_items"
_COLUMN = "last_limit_scope"


def _has_table(bind: sa.engine.Connection, table: str) -> bool:
    return sa.inspect(bind).has_table(table)


def _has_column(bind: sa.engine.Connection, table: str, column: str) -> bool:
    return any(existing["name"] == column for existing in sa.inspect(bind).get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, _ITEMS_TABLE):
        return
    if _has_column(bind, _ITEMS_TABLE, _COLUMN):
        return
    op.add_column(_ITEMS_TABLE, sa.Column(_COLUMN, sa.String(length=16), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if _has_table(bind, _ITEMS_TABLE) and _has_column(bind, _ITEMS_TABLE, _COLUMN):
        op.drop_column(_ITEMS_TABLE, _COLUMN)
