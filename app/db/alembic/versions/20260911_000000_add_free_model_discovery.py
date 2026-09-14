"""add free model discovery run, run item, and probe state tables

Revision ID: 20260911_000000_add_free_model_discovery
Revises: 20260909_000000_backfill_gpt_6_astra_costs
Create Date: 2026-09-11 00:00:00.000000

Creates the three tables behind operator-triggered free-model discovery for
the OpenRouter and OrcaRouter sidecars:

* ``free_model_discovery_runs``: one row per operator-started run, durable so
  an in-flight run survives a service restart.
* ``free_model_discovery_run_items``: the frozen candidate set of a run and
  each candidate's probe progress and verdict.
* ``free_model_probe_state``: cross-run verdict memory keyed on
  ``(provider, model_id)`` holding the failure streak and cooldown.

Every change is additive. No existing table is touched.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision = "20260911_000000_add_free_model_discovery"
down_revision = "20260909_000000_backfill_gpt_6_astra_costs"
branch_labels = None
depends_on = None

_RUNS_TABLE = "free_model_discovery_runs"
_ITEMS_TABLE = "free_model_discovery_run_items"
_STATE_TABLE = "free_model_probe_state"


def _has_table(connection: Connection, table_name: str) -> bool:
    return bool(sa.inspect(connection).has_table(table_name))


def upgrade() -> None:
    bind = op.get_bind()

    if not _has_table(bind, _RUNS_TABLE):
        op.create_table(
            _RUNS_TABLE,
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("deadline_at", sa.DateTime(), nullable=False),
            sa.Column("cancel_requested", sa.Boolean(), server_default=sa.false(), nullable=False),
            sa.Column("pacing_floor_seconds", sa.Float(), nullable=False),
            sa.Column("pacing_cap_seconds", sa.Float(), nullable=False),
            sa.Column("max_attempts_per_item", sa.Integer(), nullable=False),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("idx_free_model_discovery_runs_status_started", _RUNS_TABLE, ["status", "started_at"])

    if not _has_table(bind, _ITEMS_TABLE):
        op.create_table(
            _ITEMS_TABLE,
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("run_id", sa.String(), nullable=False),
            sa.Column("provider", sa.String(length=32), nullable=False),
            sa.Column("model_id", sa.String(), nullable=False),
            sa.Column("candidate_group", sa.String(length=16), nullable=False),
            sa.Column("state", sa.String(length=16), nullable=False),
            sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
            sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
            sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
            sa.Column("last_http_status", sa.Integer(), nullable=True),
            sa.Column("last_outcome", sa.String(length=255), nullable=True),
            sa.Column("content_chars", sa.Integer(), nullable=True),
            sa.Column("content_ok_match", sa.Boolean(), nullable=True),
            sa.Column("reasoning_chars", sa.Integer(), nullable=True),
            sa.Column("added_to_full_models", sa.Boolean(), server_default=sa.false(), nullable=False),
            sa.Column("resolved_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["run_id"], [f"{_RUNS_TABLE}.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("run_id", "provider", "model_id", name="uq_free_model_discovery_run_items_identity"),
        )
        op.create_index("idx_free_model_discovery_run_items_run_state", _ITEMS_TABLE, ["run_id", "state"])

    if not _has_table(bind, _STATE_TABLE):
        op.create_table(
            _STATE_TABLE,
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("provider", sa.String(length=32), nullable=False),
            sa.Column("model_id", sa.String(), nullable=False),
            sa.Column("last_verdict", sa.String(length=16), nullable=False),
            sa.Column("last_verdict_at", sa.DateTime(), nullable=False),
            sa.Column("last_run_id", sa.String(), nullable=True),
            sa.Column("failure_streak", sa.Integer(), server_default=sa.text("0"), nullable=False),
            sa.Column("cooldown_until", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("provider", "model_id", name="uq_free_model_probe_state_identity"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    if _has_table(bind, _STATE_TABLE):
        op.drop_table(_STATE_TABLE)
    if _has_table(bind, _ITEMS_TABLE):
        op.drop_index("idx_free_model_discovery_run_items_run_state", table_name=_ITEMS_TABLE)
        op.drop_table(_ITEMS_TABLE)
    if _has_table(bind, _RUNS_TABLE):
        op.drop_index("idx_free_model_discovery_runs_status_started", table_name=_RUNS_TABLE)
        op.drop_table(_RUNS_TABLE)
