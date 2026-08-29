"""add external model price resolution store and request log cost provenance

Revision ID: 20260828_000000_add_external_model_prices
Revises: 20260825_000000_add_orcarouter_sidecar_dashboard_settings
Create Date: 2026-08-28 00:00:00.000000

Creates ``external_model_prices``, the single durable owner of external-integration
model pricing records and resolution state, and adds the nullable
``request_logs.cost_source`` and ``request_logs.price_status`` provenance columns.

Every change is additive. Both new columns are deliberately left NULL on existing
rows: their provenance is genuinely unknown (the columns did not exist when the
rows were written), and inventing a value would assert a distinction the data
cannot support. Readers must treat NULL ``cost_source`` as unknown rather than as
billed, and NULL ``price_status`` as "not an external-priced row".
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision = "20260828_000000_add_external_model_prices"
down_revision = "20260825_000000_add_orcarouter_sidecar_dashboard_settings"
branch_labels = None
depends_on = None

_PRICES_TABLE = "external_model_prices"
_LOGS_TABLE = "request_logs"


def _columns(connection: Connection, table_name: str) -> set[str]:
    inspector = sa.inspect(connection)
    if not inspector.has_table(table_name):
        return set()
    return {str(column["name"]) for column in inspector.get_columns(table_name) if column.get("name") is not None}


def _has_table(connection: Connection, table_name: str) -> bool:
    return bool(sa.inspect(connection).has_table(table_name))


def upgrade() -> None:
    bind = op.get_bind()

    if not _has_table(bind, _PRICES_TABLE):
        op.create_table(
            _PRICES_TABLE,
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("provider", sa.String(), nullable=False),
            sa.Column("incoming_model", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("catalog_model", sa.String(), nullable=True),
            sa.Column("catalog_source", sa.String(), nullable=True),
            sa.Column("input_per_1m", sa.Float(), nullable=True),
            sa.Column("output_per_1m", sa.Float(), nullable=True),
            sa.Column("resolution_step", sa.String(), nullable=True),
            sa.Column("detail", sa.Text(), nullable=True),
            sa.Column("retrieved_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
            sa.Column("next_retry_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("provider", "incoming_model", name="uq_external_model_prices_provider_model"),
        )
        op.create_index("idx_external_model_prices_retry", _PRICES_TABLE, ["status", "next_retry_at"])

    log_columns = _columns(bind, _LOGS_TABLE)
    if log_columns:
        with op.batch_alter_table(_LOGS_TABLE) as batch_op:
            if "cost_source" not in log_columns:
                batch_op.add_column(sa.Column("cost_source", sa.String(), nullable=True))
            if "price_status" not in log_columns:
                batch_op.add_column(sa.Column("price_status", sa.String(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()

    log_columns = _columns(bind, _LOGS_TABLE)
    if log_columns:
        with op.batch_alter_table(_LOGS_TABLE) as batch_op:
            if "price_status" in log_columns:
                batch_op.drop_column("price_status")
            if "cost_source" in log_columns:
                batch_op.drop_column("cost_source")

    if _has_table(bind, _PRICES_TABLE):
        op.drop_index("idx_external_model_prices_retry", table_name=_PRICES_TABLE)
        op.drop_table(_PRICES_TABLE)
