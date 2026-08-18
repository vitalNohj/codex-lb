"""backfill claude opus-5 and sonnet-5 request log costs

Revision ID: 20260818_000000_backfill_claude_opus_5_sonnet_5_costs
Revises: 20260727_000000_merge_fork_and_upstream_1_22_heads
Create Date: 2026-08-18 00:00:00.000000

Claude Opus 5 and Sonnet 5 pricing was added to ``DEFAULT_PRICING_MODELS``
after sidecar traffic had already been logged; those rows persisted
``cost_usd = NULL`` because no price resolved at insert time. Recompute
cost for historical Claude sidecar rows that now resolve so dollar reports
cover Opus 5 / Sonnet 5 usage. Folded usage rollups then receive a cost-only
delta for rows this migration actually repriced; ``folded_through`` is left
unchanged.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

from app.core.usage.pricing import UsageTokens, calculate_cost_from_usage, get_pricing_for_model

revision = "20260818_000000_backfill_claude_opus_5_sonnet_5_costs"
down_revision = "20260727_000000_merge_fork_and_upstream_1_22_heads"
branch_labels = None
depends_on = None

_BACKFILL_BATCH_SIZE = 1000
_DOWNGRADE_MODEL_MATCH = ("%claude-opus-5%", "%claude-sonnet-5%")
_EXCLUDED_REQUEST_KINDS = ("warmup", "limit_warmup")


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


def _as_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return None


def _read_watermark(bind: Connection) -> datetime | None:
    if not _has_table(bind, "account_usage_rollup_state"):
        return None
    rollup_state = sa.table(
        "account_usage_rollup_state",
        sa.column("folded_through", sa.DateTime()),
    )
    return _as_datetime(bind.execute(sa.select(rollup_state.c.folded_through)).scalar())


def _request_logs_table() -> Any:
    return sa.table(
        "request_logs",
        sa.column("id", sa.Integer()),
        sa.column("account_id", sa.String()),
        sa.column("api_key_id", sa.String()),
        sa.column("request_id", sa.String()),
        sa.column("model", sa.String()),
        sa.column("source", sa.String()),
        sa.column("service_tier", sa.String()),
        sa.column("request_kind", sa.String()),
        sa.column("deleted_at", sa.DateTime()),
        sa.column("requested_at", sa.DateTime()),
        sa.column("input_tokens", sa.Integer()),
        sa.column("output_tokens", sa.Integer()),
        sa.column("cached_input_tokens", sa.Integer()),
        sa.column("reasoning_tokens", sa.Integer()),
        sa.column("cost_usd", sa.Float()),
    )


def _accumulate_deltas(rows: list[dict[str, Any]]) -> tuple[dict[str, float], dict[str, float]]:
    latest_account: dict[tuple[object, object, object], dict[str, Any]] = {}
    key_deltas: dict[str, float] = {}
    for row in rows:
        if row["request_kind"] in _EXCLUDED_REQUEST_KINDS:
            continue
        cost = row["cost_usd"]
        if cost is None:
            continue
        cost_f = float(cost)
        api_key_id = row["api_key_id"]
        if api_key_id:
            key_deltas[str(api_key_id)] = key_deltas.get(str(api_key_id), 0.0) + cost_f
        account_id = row["account_id"]
        if account_id and row["deleted_at"] is None:
            group = (account_id, row["request_id"], row["requested_at"])
            prev = latest_account.get(group)
            if prev is None or int(row["id"]) > int(prev["id"]):
                latest_account[group] = row
    account_deltas: dict[str, float] = {}
    for row in latest_account.values():
        account_id = str(row["account_id"])
        account_deltas[account_id] = account_deltas.get(account_id, 0.0) + float(row["cost_usd"])
    return account_deltas, key_deltas


def _apply_deltas(
    bind: Connection,
    account_deltas: dict[str, float],
    key_deltas: dict[str, float],
    *,
    sign: int,
) -> None:
    if account_deltas and _has_table(bind, "account_usage_rollups"):
        rollups = sa.table(
            "account_usage_rollups",
            sa.column("account_id", sa.String()),
            sa.column("total_cost_usd", sa.Float()),
        )
        for account_id, delta in account_deltas.items():
            if not delta:
                continue
            bind.execute(
                sa.update(rollups)
                .where(rollups.c.account_id == account_id)
                .values(total_cost_usd=rollups.c.total_cost_usd + (sign * delta))
            )
    if key_deltas and _has_table(bind, "api_key_usage_rollups"):
        rollups = sa.table(
            "api_key_usage_rollups",
            sa.column("api_key_id", sa.String()),
            sa.column("total_cost_usd", sa.Float()),
        )
        for api_key_id, delta in key_deltas.items():
            if not delta:
                continue
            bind.execute(
                sa.update(rollups)
                .where(rollups.c.api_key_id == api_key_id)
                .values(total_cost_usd=rollups.c.total_cost_usd + (sign * delta))
            )


def _folded_opus5_sonnet5_rows(bind: Connection, watermark: datetime) -> list[dict[str, Any]]:
    request_logs = _request_logs_table()
    model_match = sa.or_(
        request_logs.c.model.like(_DOWNGRADE_MODEL_MATCH[0]),
        request_logs.c.model.like(_DOWNGRADE_MODEL_MATCH[1]),
    )
    return (
        bind.execute(
            sa.select(
                request_logs.c.id,
                request_logs.c.account_id,
                request_logs.c.api_key_id,
                request_logs.c.request_id,
                request_logs.c.request_kind,
                request_logs.c.deleted_at,
                request_logs.c.requested_at,
                request_logs.c.cost_usd,
            ).where(
                request_logs.c.source == "claude_sidecar",
                model_match,
                request_logs.c.cost_usd.is_not(None),
                request_logs.c.requested_at <= watermark,
            )
        )
        .mappings()
        .all()
    )


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, "request_logs"):
        return

    request_logs = _request_logs_table()
    watermark = _read_watermark(bind)
    backfilled_folded: list[dict[str, Any]] = []

    last_seen_id = 0
    while True:
        rows = (
            bind.execute(
                sa.select(
                    request_logs.c.id,
                    request_logs.c.account_id,
                    request_logs.c.api_key_id,
                    request_logs.c.request_id,
                    request_logs.c.request_kind,
                    request_logs.c.deleted_at,
                    request_logs.c.requested_at,
                    request_logs.c.model,
                    request_logs.c.service_tier,
                    request_logs.c.input_tokens,
                    request_logs.c.output_tokens,
                    request_logs.c.cached_input_tokens,
                    request_logs.c.reasoning_tokens,
                )
                .where(
                    request_logs.c.id > last_seen_id,
                    request_logs.c.source == "claude_sidecar",
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
            requested_at = _as_datetime(row["requested_at"])
            if watermark is None or requested_at is None or requested_at > watermark:
                continue
            backfilled_folded.append(
                {
                    "id": row["id"],
                    "account_id": row["account_id"],
                    "api_key_id": row["api_key_id"],
                    "request_id": row["request_id"],
                    "request_kind": row["request_kind"],
                    "deleted_at": row["deleted_at"],
                    "requested_at": row["requested_at"],
                    "cost_usd": cost,
                }
            )
        last_seen_id = int(rows[-1]["id"])

    account_deltas, key_deltas = _accumulate_deltas(backfilled_folded)
    _apply_deltas(bind, account_deltas, key_deltas, sign=1)


def downgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, "request_logs"):
        return
    request_logs = _request_logs_table()
    watermark = _read_watermark(bind)
    if watermark is not None:
        account_deltas, key_deltas = _accumulate_deltas(list(_folded_opus5_sonnet5_rows(bind, watermark)))
        _apply_deltas(bind, account_deltas, key_deltas, sign=-1)
    bind.execute(
        sa.update(request_logs)
        .where(
            request_logs.c.source == "claude_sidecar",
            sa.or_(
                request_logs.c.model.like(_DOWNGRADE_MODEL_MATCH[0]),
                request_logs.c.model.like(_DOWNGRADE_MODEL_MATCH[1]),
            ),
        )
        .values(cost_usd=None)
    )
