"""add reference cost to request_logs

Revision ID: 20260614_020000_add_request_log_reference_cost
Revises: 20260614_010000_backfill_free_sidecar_request_log_costs
Create Date: 2026-06-14 02:00:00.000000

Adds a nullable ``reference_cost_usd`` column to ``request_logs`` capturing what
a request would have cost at the paid-equivalent list price. ``cost_usd``
remains the authoritative record of actual spend; ``reference_cost_usd`` is
purely additive and powers the savings figure (``reference_cost_usd - cost_usd``)
for free/cheap sidecar models. Historical rows are left ``NULL`` (no backfill).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision = "20260614_020000_add_request_log_reference_cost"
down_revision = "20260614_010000_backfill_free_sidecar_request_log_costs"
branch_labels = None
depends_on = None


def _columns(connection: Connection, table_name: str) -> set[str]:
    inspector = sa.inspect(connection)
    if not inspector.has_table(table_name):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    columns = _columns(bind, "request_logs")
    if not columns:
        return
    if "reference_cost_usd" not in columns:
        with op.batch_alter_table("request_logs") as batch_op:
            batch_op.add_column(sa.Column("reference_cost_usd", sa.Float(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    columns = _columns(bind, "request_logs")
    if not columns or "reference_cost_usd" not in columns:
        return
    with op.batch_alter_table("request_logs") as batch_op:
        batch_op.drop_column("reference_cost_usd")
