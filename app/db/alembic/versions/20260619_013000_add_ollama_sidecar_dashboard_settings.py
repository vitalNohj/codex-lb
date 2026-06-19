"""add ollama sidecar dashboard settings

Revision ID: 20260619_013000_add_ollama_sidecar_dashboard_settings
Revises: 20260618_040000_unify_sidecar_routing_settings
Create Date: 2026-06-19 01:30:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision = "20260619_013000_add_ollama_sidecar_dashboard_settings"
down_revision = "20260618_040000_unify_sidecar_routing_settings"
branch_labels = None
depends_on = None

_TABLE_NAME = "dashboard_settings"


def _columns(connection: Connection, table_name: str) -> set[str]:
    inspector = sa.inspect(connection)
    if not inspector.has_table(table_name):
        return set()
    return {str(column["name"]) for column in inspector.get_columns(table_name) if column.get("name") is not None}


def upgrade() -> None:
    bind = op.get_bind()
    columns = _columns(bind, _TABLE_NAME)
    if not columns:
        return
    with op.batch_alter_table(_TABLE_NAME) as batch_op:
        if "ollama_sidecar_enabled" not in columns:
            batch_op.add_column(
                sa.Column("ollama_sidecar_enabled", sa.Boolean(), server_default=sa.false(), nullable=False)
            )
        if "ollama_sidecar_base_url" not in columns:
            batch_op.add_column(
                sa.Column(
                    "ollama_sidecar_base_url",
                    sa.String(),
                    server_default=sa.text("'https://ollama.com'"),
                    nullable=False,
                )
            )
        if "ollama_sidecar_api_key_encrypted" not in columns:
            batch_op.add_column(sa.Column("ollama_sidecar_api_key_encrypted", sa.LargeBinary(), nullable=True))
        if "ollama_sidecar_model_prefixes_json" not in columns:
            batch_op.add_column(
                sa.Column(
                    "ollama_sidecar_model_prefixes_json",
                    sa.Text(),
                    server_default=sa.text("'[]'"),
                    nullable=False,
                )
            )
        if "ollama_sidecar_full_models_json" not in columns:
            batch_op.add_column(
                sa.Column(
                    "ollama_sidecar_full_models_json",
                    sa.Text(),
                    server_default=sa.text("'[]'"),
                    nullable=False,
                )
            )
        if "ollama_sidecar_connect_timeout_seconds" not in columns:
            batch_op.add_column(
                sa.Column(
                    "ollama_sidecar_connect_timeout_seconds",
                    sa.Float(),
                    server_default=sa.text("8.0"),
                    nullable=False,
                )
            )
        if "ollama_sidecar_request_timeout_seconds" not in columns:
            batch_op.add_column(
                sa.Column(
                    "ollama_sidecar_request_timeout_seconds",
                    sa.Float(),
                    server_default=sa.text("600.0"),
                    nullable=False,
                )
            )
        if "ollama_sidecar_models_cache_ttl_seconds" not in columns:
            batch_op.add_column(
                sa.Column(
                    "ollama_sidecar_models_cache_ttl_seconds",
                    sa.Float(),
                    server_default=sa.text("60.0"),
                    nullable=False,
                )
            )
        if "ollama_sidecar_last_health_status" not in columns:
            batch_op.add_column(sa.Column("ollama_sidecar_last_health_status", sa.String(), nullable=True))
        if "ollama_sidecar_last_health_message" not in columns:
            batch_op.add_column(sa.Column("ollama_sidecar_last_health_message", sa.Text(), nullable=True))
        if "ollama_sidecar_last_checked_at" not in columns:
            batch_op.add_column(sa.Column("ollama_sidecar_last_checked_at", sa.DateTime(), nullable=True))
        if "ollama_sidecar_last_model_count" not in columns:
            batch_op.add_column(sa.Column("ollama_sidecar_last_model_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    columns = _columns(bind, _TABLE_NAME)
    if not columns:
        return
    with op.batch_alter_table(_TABLE_NAME) as batch_op:
        for column_name in (
            "ollama_sidecar_last_model_count",
            "ollama_sidecar_last_checked_at",
            "ollama_sidecar_last_health_message",
            "ollama_sidecar_last_health_status",
            "ollama_sidecar_models_cache_ttl_seconds",
            "ollama_sidecar_request_timeout_seconds",
            "ollama_sidecar_connect_timeout_seconds",
            "ollama_sidecar_full_models_json",
            "ollama_sidecar_model_prefixes_json",
            "ollama_sidecar_api_key_encrypted",
            "ollama_sidecar_base_url",
            "ollama_sidecar_enabled",
        ):
            if column_name in columns:
                batch_op.drop_column(column_name)
