"""add nvidia sidecar dashboard settings

Revision ID: 20260916_010000_add_nvidia_sidecar_dashboard_settings
Revises: 20260916_000000_add_free_model_discovery_limit_scope
Create Date: 2026-09-16 01:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision = "20260916_010000_add_nvidia_sidecar_dashboard_settings"
down_revision = "20260916_000000_add_free_model_discovery_limit_scope"
branch_labels = None
depends_on = None

_TABLE_NAME = "dashboard_settings"
_PREFIX_COLUMN = "nvidia_sidecar_model_prefixes_json"


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
        if "nvidia_sidecar_enabled" not in columns:
            batch_op.add_column(
                sa.Column("nvidia_sidecar_enabled", sa.Boolean(), server_default=sa.false(), nullable=False)
            )
        if "nvidia_sidecar_base_url" not in columns:
            batch_op.add_column(
                sa.Column(
                    "nvidia_sidecar_base_url",
                    sa.String(),
                    server_default=sa.text("'https://integrate.api.nvidia.com/v1'"),
                    nullable=False,
                )
            )
        if "nvidia_sidecar_api_key_encrypted" not in columns:
            batch_op.add_column(sa.Column("nvidia_sidecar_api_key_encrypted", sa.LargeBinary(), nullable=True))
        if _PREFIX_COLUMN not in columns:
            batch_op.add_column(
                sa.Column(
                    _PREFIX_COLUMN,
                    sa.Text(),
                    server_default=sa.text("'[]'"),
                    nullable=False,
                )
            )
        if "nvidia_sidecar_full_models_json" not in columns:
            batch_op.add_column(
                sa.Column(
                    "nvidia_sidecar_full_models_json",
                    sa.Text(),
                    server_default=sa.text("'[]'"),
                    nullable=False,
                )
            )
        if "nvidia_sidecar_connect_timeout_seconds" not in columns:
            batch_op.add_column(
                sa.Column(
                    "nvidia_sidecar_connect_timeout_seconds",
                    sa.Float(),
                    server_default=sa.text("8.0"),
                    nullable=False,
                )
            )
        if "nvidia_sidecar_request_timeout_seconds" not in columns:
            batch_op.add_column(
                sa.Column(
                    "nvidia_sidecar_request_timeout_seconds",
                    sa.Float(),
                    server_default=sa.text("600.0"),
                    nullable=False,
                )
            )
        if "nvidia_sidecar_models_cache_ttl_seconds" not in columns:
            batch_op.add_column(
                sa.Column(
                    "nvidia_sidecar_models_cache_ttl_seconds",
                    sa.Float(),
                    server_default=sa.text("60.0"),
                    nullable=False,
                )
            )
        if "nvidia_sidecar_last_health_status" not in columns:
            batch_op.add_column(sa.Column("nvidia_sidecar_last_health_status", sa.String(), nullable=True))
        if "nvidia_sidecar_last_health_message" not in columns:
            batch_op.add_column(sa.Column("nvidia_sidecar_last_health_message", sa.Text(), nullable=True))
        if "nvidia_sidecar_last_checked_at" not in columns:
            batch_op.add_column(sa.Column("nvidia_sidecar_last_checked_at", sa.DateTime(), nullable=True))
        if "nvidia_sidecar_last_model_count" not in columns:
            batch_op.add_column(sa.Column("nvidia_sidecar_last_model_count", sa.Integer(), nullable=True))
        if "nvidia_sidecar_default_reasoning_effort" not in columns:
            batch_op.add_column(sa.Column("nvidia_sidecar_default_reasoning_effort", sa.String(), nullable=True))

    # The fresh-install prefix seed that used to live here read
    # ``CODEX_LB_NVIDIA_SIDECAR_MODEL_PREFIXES``. That setting no longer exists
    # (the integration was folded into the OpenAI-compat endpoint list by
    # ``20260925_000000_fold_nvidia_into_openai_compat``) and its default was
    # always empty, so the seed is dropped rather than kept as dead code.


def downgrade() -> None:
    bind = op.get_bind()
    columns = _columns(bind, _TABLE_NAME)
    if not columns:
        return
    with op.batch_alter_table(_TABLE_NAME) as batch_op:
        for column_name in (
            "nvidia_sidecar_default_reasoning_effort",
            "nvidia_sidecar_last_model_count",
            "nvidia_sidecar_last_checked_at",
            "nvidia_sidecar_last_health_message",
            "nvidia_sidecar_last_health_status",
            "nvidia_sidecar_models_cache_ttl_seconds",
            "nvidia_sidecar_request_timeout_seconds",
            "nvidia_sidecar_connect_timeout_seconds",
            "nvidia_sidecar_full_models_json",
            "nvidia_sidecar_model_prefixes_json",
            "nvidia_sidecar_api_key_encrypted",
            "nvidia_sidecar_base_url",
            "nvidia_sidecar_enabled",
        ):
            if column_name in columns:
                batch_op.drop_column(column_name)
