"""backfill free sidecar request log costs

Revision ID: 20260614_010000_backfill_free_sidecar_request_log_costs
Revises: 20260614_000000_backfill_openrouter_omniroute_request_log_costs
Create Date: 2026-06-14 01:00:00.000000

OpenRouter and OmniRoute both expose free models with names such as
``*:free``, ``*-free``, or ``free-stack``. The first sidecar cost backfill left
those rows as ``cost_usd = NULL`` because no paid pricing entry resolved. Mark
explicitly free sidecar rows as zero-cost so dashboards show ``$0.00`` instead
of an unknown-cost placeholder.
"""

from __future__ import annotations

import re

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision = "20260614_010000_backfill_free_sidecar_request_log_costs"
down_revision = "20260614_000000_backfill_openrouter_omniroute_request_log_costs"
branch_labels = None
depends_on = None

_FREE_MODEL_RE = re.compile(r"(^|[/:_-])free($|[/:_-])")
_OPAQUE_FREE_MODELS = frozenset(
    {
        "big-pickle",
        "oc/big-pickle",
    }
)
_SIDECAR_SOURCES = ("openrouter_sidecar", "omniroute_sidecar")
_BACKFILL_BATCH_SIZE = 1000


def _is_known_free_model(model: str | None) -> bool:
    if not model:
        return False
    normalized = model.strip().lower()
    return normalized in _OPAQUE_FREE_MODELS or bool(_FREE_MODEL_RE.search(normalized))


def _has_table(connection: Connection, table_name: str) -> bool:
    return sa.inspect(connection).has_table(table_name)


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, "request_logs"):
        return

    request_logs = sa.table(
        "request_logs",
        sa.column("id", sa.Integer()),
        sa.column("model", sa.String()),
        sa.column("cost_usd", sa.Float()),
        sa.column("source", sa.String()),
    )

    last_seen_id = 0
    while True:
        rows = (
            bind.execute(
                sa.select(request_logs.c.id, request_logs.c.model)
                .where(
                    request_logs.c.id > last_seen_id,
                    request_logs.c.source.in_(_SIDECAR_SOURCES),
                    request_logs.c.cost_usd.is_(None),
                )
                .order_by(request_logs.c.id)
                .limit(_BACKFILL_BATCH_SIZE)
            )
            .mappings()
            .all()
        )
        if not rows:
            break
        free_ids = [row["id"] for row in rows if _is_known_free_model(row["model"])]
        if free_ids:
            bind.execute(sa.update(request_logs).where(request_logs.c.id.in_(free_ids)).values(cost_usd=0.0))
        last_seen_id = int(rows[-1]["id"])


def downgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, "request_logs"):
        return

    request_logs = sa.table(
        "request_logs",
        sa.column("id", sa.Integer()),
        sa.column("model", sa.String()),
        sa.column("cost_usd", sa.Float()),
        sa.column("source", sa.String()),
    )

    last_seen_id = 0
    while True:
        rows = (
            bind.execute(
                sa.select(request_logs.c.id, request_logs.c.model)
                .where(
                    request_logs.c.id > last_seen_id,
                    request_logs.c.source.in_(_SIDECAR_SOURCES),
                    request_logs.c.cost_usd == 0.0,
                )
                .order_by(request_logs.c.id)
                .limit(_BACKFILL_BATCH_SIZE)
            )
            .mappings()
            .all()
        )
        if not rows:
            break
        free_ids = [row["id"] for row in rows if _is_known_free_model(row["model"])]
        if free_ids:
            bind.execute(sa.update(request_logs).where(request_logs.c.id.in_(free_ids)).values(cost_usd=None))
        last_seen_id = int(rows[-1]["id"])
