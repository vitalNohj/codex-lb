"""add nvidia sidecar dashboard settings

Revision ID: 20260916_010000_add_nvidia_sidecar_dashboard_settings
Revises: 20260916_000000_add_free_model_discovery_limit_scope
Create Date: 2026-09-16 01:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

from app.core.config.settings import get_settings
from app.core.config.sidecar_prefix_seed import dump_configured_sidecar_prefixes

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

    _seed_fresh_install_prefixes(bind, previously_present=_PREFIX_COLUMN in columns)


def _seed_fresh_install_prefixes(bind: Connection, *, previously_present: bool) -> None:
    """Seed configured prefixes only when this migration creates the database.

    Existing deployments keep an empty prefix list so the operator opts in from
    the Settings UI. NVIDIA has no seeded prefix; ``CODEX_LB_NVIDIA_SIDECAR_MODEL_PREFIXES``
    is empty by default. On a fresh install the seed comes from that env through
    the same settings object ``SettingsRepository.get_or_create`` reads.
    """

    if previously_present:
        return
    config = op.get_context().config
    if config is None or not bool(config.attributes.get("codex_lb_fresh_install")):
        return
    seed = dump_configured_sidecar_prefixes(get_settings().nvidia_sidecar_model_prefixes)
    bind.execute(
        sa.text(f"UPDATE {_TABLE_NAME} SET {_PREFIX_COLUMN} = :prefixes WHERE id = 1"),
        {"prefixes": seed},
    )


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
