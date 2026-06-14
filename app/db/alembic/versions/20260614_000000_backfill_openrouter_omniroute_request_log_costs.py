"""backfill openrouter/omniroute sidecar request log costs

Revision ID: 20260614_000000_backfill_openrouter_omniroute_request_log_costs
Revises: 20260612_000000_add_omniroute_sidecar_dashboard_settings
Create Date: 2026-06-14 00:00:00.000000

OpenRouter and OmniRoute pricing was added to ``DEFAULT_PRICING_MODELS`` after
sidecar traffic had already been logged; those rows persisted ``cost_usd = NULL``
or ``0`` because no price resolved at insert time. Recompute the cost for
historical sidecar rows so dollar reports cover past OpenRouter/OmniRoute usage.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

from app.core.usage.pricing import UsageTokens, calculate_cost_from_usage, get_pricing_for_model

revision = "20260614_000000_backfill_openrouter_omniroute_request_log_costs"
down_revision = "20260612_000000_add_omniroute_sidecar_dashboard_settings"
branch_labels = None
depends_on = None

_BACKFILL_BATCH_SIZE = 1000


def _calculate_cost(
    *,
    model: str | None,
    service_tier: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
    cached_input_tokens: int | None,
    reasoning_tokens: int | None,
) -> float | None:
    if not model or input_tokens is None:
        return None
    resolved_output_tokens = output_tokens if output_tokens is not None else reasoning_tokens
    if resolved_output_tokens is None:
        return None
    resolved = get_pricing_for_model(model, None, None)
    if resolved is None:
        return None
    _, price = resolved
    normalized_cached_tokens = max(0, min(int(cached_input_tokens or 0), int(input_tokens)))
    return calculate_cost_from_usage(
        UsageTokens(
            input_tokens=float(input_tokens),
            output_tokens=float(resolved_output_tokens),
            cached_input_tokens=float(normalized_cached_tokens),
        ),
        price,
        service_tier=service_tier,
    )


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
        sa.column("service_tier", sa.String()),
        sa.column("input_tokens", sa.Integer()),
        sa.column("output_tokens", sa.Integer()),
        sa.column("cached_input_tokens", sa.Integer()),
        sa.column("reasoning_tokens", sa.Integer()),
        sa.column("cost_usd", sa.Float()),
        sa.column("source", sa.String()),
    )

    last_seen_id = 0
    while True:
        rows = (
            bind.execute(
                sa.select(
                    request_logs.c.id,
                    request_logs.c.model,
                    request_logs.c.service_tier,
                    request_logs.c.input_tokens,
                    request_logs.c.output_tokens,
                    request_logs.c.cached_input_tokens,
                    request_logs.c.reasoning_tokens,
                )
                .where(
                    request_logs.c.id > last_seen_id,
                    request_logs.c.source.in_(["openrouter_sidecar", "omniroute_sidecar"]),
                    sa.or_(request_logs.c.cost_usd.is_(None), request_logs.c.cost_usd == 0),
                )
                .order_by(request_logs.c.id)
                .limit(_BACKFILL_BATCH_SIZE)
            )
            .mappings()
            .all()
        )
        if not rows:
            break
        for row in rows:
            cost = _calculate_cost(
                model=row["model"],
                service_tier=row["service_tier"],
                input_tokens=row["input_tokens"],
                output_tokens=row["output_tokens"],
                cached_input_tokens=row["cached_input_tokens"],
                reasoning_tokens=row["reasoning_tokens"],
            )
            if cost is None:
                continue
            bind.execute(sa.update(request_logs).where(request_logs.c.id == row["id"]).values(cost_usd=cost))
        last_seen_id = int(rows[-1]["id"])


def downgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, "request_logs"):
        return
    request_logs = sa.table(
        "request_logs",
        sa.column("cost_usd", sa.Float()),
        sa.column("source", sa.String()),
    )
    bind.execute(
        sa.update(request_logs)
        .where(request_logs.c.source.in_(["openrouter_sidecar", "omniroute_sidecar"]))
        .values(cost_usd=None)
    )