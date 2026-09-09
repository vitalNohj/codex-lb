"""backfill gpt-6-astra request log costs

Revision ID: 20260909_000000_backfill_gpt_6_astra_costs
Revises: 20260903_000000_merge_fork_and_upstream_1_24_heads
Create Date: 2026-09-09 00:00:00.000000

GPT-6 Astra pricing was added to ``DEFAULT_PRICING_MODELS`` after native
Codex traffic had already been logged; those rows persisted
``cost_usd = NULL`` because no price resolved at insert time. Recompute
cost for historical GPT-6 Astra rows that now resolve so dollar reports
cover that usage. Folded usage rollups then receive a cost-only delta for
rows this migration actually repriced; ``folded_through`` is left
unchanged.

Three invariants keep the repair from inventing or double-counting money:

* Rows whose writer already settled their price are never touched. A row
  carrying a ``cost_source`` other than ``static_table``, or any
  ``price_status`` at all, belongs to external price resolution and its
  NULL cost is a deliberate answer, not a gap (the read-side rule is
  ``app.core.usage.logs.declares_price_provenance``).
* The lifetime account rollup folds only the ``max(id)`` row of each
  ``(account_id, request_id, requested_at)`` duplicate group
  (``deduped_usage_aggregate_stmt``). A repriced row that is not its
  group's true maximum contributes nothing to that rollup, because a
  higher-id sibling already does. The per-API-key rollup does not
  deduplicate, so every repriced row still counts there.
* The hourly and demand rollups fold ``sum(cost_usd)`` behind their own
  ``hourly_folded_through`` watermark, so repricing a row underneath it
  leaves those buckets stale. The migration arms the existing post-upgrade
  repair marker instead of hand-patching bucket rows. The conversation
  satellite stores only ``request_count`` and needs no repair.

``downgrade()`` deliberately does not un-price anything: see its docstring.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

from app.core.usage.pricing import UsageTokens, calculate_cost_from_usage, get_pricing_for_model

revision = "20260909_000000_backfill_gpt_6_astra_costs"
down_revision = "20260903_000000_merge_fork_and_upstream_1_24_heads"
branch_labels = None
depends_on = None

_BACKFILL_BATCH_SIZE = 1000
_MODEL_MATCH = "%gpt-6-astra%"
_EXCLUDED_REQUEST_KINDS = ("warmup", "limit_warmup")
_STATIC_TABLE = "static_table"
_HOUR = timedelta(hours=1)


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


def _columns(connection: Connection, table_name: str) -> set[str]:
    if not _has_table(connection, table_name):
        return set()
    return {str(column["name"]) for column in sa.inspect(connection).get_columns(table_name) if column.get("name")}


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


def _rollup_state_table() -> Any:
    return sa.table(
        "account_usage_rollup_state",
        sa.column("hourly_folded_through", sa.DateTime()),
        sa.column("upgrade_repair_from", sa.DateTime()),
    )


def _floor_to_hour(value: datetime) -> datetime:
    return value.replace(minute=0, second=0, microsecond=0)


def _arm_time_rollup_repair(bind: Connection, earliest_repriced: datetime | None) -> None:
    """Re-arm the hourly/demand post-upgrade repair over the repriced range.

    ``_hourly_fold_insert`` and ``_demand_fold_insert`` both fold
    ``sum(cost_usd)``, so every already-folded bucket holding a row this
    migration repriced is now short by that cost. Rather than patching bucket
    rows (which would have to reproduce their full dimension grain), point the
    existing ``upgrade_repair_from`` marker at the earliest repriced hour: the
    next fold pass refolds ``[marker, hourly_folded_through)`` from raw, which
    is idempotent and converges on any input state.

    Only the range already folded needs arming; newer rows are still the live
    tail. An earlier marker already set by another upgrade is preserved, since
    refolding a wider range is safe and dropping its range would not be. The
    conversation satellite folds ``request_count`` only and is untouched.
    """

    if earliest_repriced is None:
        return
    columns = _columns(bind, "account_usage_rollup_state")
    if not {"hourly_folded_through", "upgrade_repair_from"} <= columns:
        return
    rollup_state = _rollup_state_table()
    row = bind.execute(sa.select(rollup_state.c.hourly_folded_through, rollup_state.c.upgrade_repair_from)).first()
    if row is None:
        return
    hourly_watermark = _as_datetime(row[0])
    if hourly_watermark is None or earliest_repriced >= hourly_watermark:
        # Nothing repriced below the hourly watermark: those rows are still in
        # the live tail and will be folded with their cost already present.
        return
    marker = _floor_to_hour(earliest_repriced)
    existing = _as_datetime(row[1])
    if existing is not None and existing <= marker:
        return
    bind.execute(sa.update(rollup_state).values(upgrade_repair_from=marker))


def _request_logs_table() -> Any:
    return sa.table(
        "request_logs",
        sa.column("id", sa.Integer()),
        sa.column("account_id", sa.String()),
        sa.column("api_key_id", sa.String()),
        sa.column("request_id", sa.String()),
        sa.column("model", sa.String()),
        sa.column("service_tier", sa.String()),
        sa.column("request_kind", sa.String()),
        sa.column("deleted_at", sa.DateTime()),
        sa.column("requested_at", sa.DateTime()),
        sa.column("input_tokens", sa.Integer()),
        sa.column("output_tokens", sa.Integer()),
        sa.column("cached_input_tokens", sa.Integer()),
        sa.column("reasoning_tokens", sa.Integer()),
        sa.column("cost_usd", sa.Float()),
        sa.column("cost_source", sa.String()),
        sa.column("price_status", sa.String()),
    )


def _model_match(request_logs: Any) -> Any:
    return request_logs.c.model.like(_MODEL_MATCH)


def _group_max_ids(bind: Connection, rows: list[dict[str, Any]]) -> dict[tuple[object, object, object], int]:
    """True ``max(id)`` per duplicate group, over ALL rows, not just repriced ones.

    ``deduped_usage_aggregate_stmt`` folds one row per ``(account_id,
    request_id, requested_at)`` group: the highest id, whatever its model or
    cost provenance. Taking the maximum within the repriced subset instead
    would credit the account rollup for a lower-id row whose higher-id sibling
    is the row the reader actually sums -- and that sibling's cost is already
    in the rollup, so the account total would gain a duplicate charge.
    """

    request_ids = {row["request_id"] for row in rows if row["account_id"] and row["deleted_at"] is None}
    request_ids.discard(None)
    if not request_ids:
        return {}
    request_logs = _request_logs_table()
    max_ids: dict[tuple[object, object, object], int] = {}
    ids = sorted(request_ids)
    # Grouped in SQL and keyed in Python on the values the driver returns, so
    # both sides of the key comparison come from the same read path. Binding a
    # Python ``datetime`` back into a ``requested_at`` predicate would not
    # match SQLite's stored text (microsecond formatting differs) and would
    # silently find no group at all.
    for chunk_start in range(0, len(ids), _BACKFILL_BATCH_SIZE):
        chunk = ids[chunk_start : chunk_start + _BACKFILL_BATCH_SIZE]
        grouped = bind.execute(
            sa.select(
                request_logs.c.account_id,
                request_logs.c.request_id,
                request_logs.c.requested_at,
                sa.func.max(request_logs.c.id),
            )
            .where(
                request_logs.c.request_id.in_(chunk),
                request_logs.c.account_id.is_not(None),
                request_logs.c.deleted_at.is_(None),
                request_logs.c.request_kind.not_in(_EXCLUDED_REQUEST_KINDS),
            )
            .group_by(
                request_logs.c.account_id,
                request_logs.c.request_id,
                request_logs.c.requested_at,
            )
        ).all()
        for account_id, request_id, requested_at, max_id in grouped:
            if max_id is not None:
                max_ids[(account_id, request_id, requested_at)] = int(max_id)
    return max_ids


def _accumulate_deltas(
    bind: Connection,
    rows: list[dict[str, Any]],
) -> tuple[dict[str, float], dict[str, float]]:
    countable = [
        row for row in rows if row["request_kind"] not in _EXCLUDED_REQUEST_KINDS and row["cost_usd"] is not None
    ]
    key_deltas: dict[str, float] = {}
    for row in countable:
        api_key_id = row["api_key_id"]
        if api_key_id:
            # The per-API-key aggregate does not collapse duplicates, so every
            # repriced row contributes there.
            key_deltas[str(api_key_id)] = key_deltas.get(str(api_key_id), 0.0) + float(row["cost_usd"])
    group_max_ids = _group_max_ids(bind, countable)
    account_deltas: dict[str, float] = {}
    for row in countable:
        account_id = row["account_id"]
        if not account_id or row["deleted_at"] is not None:
            continue
        group = (account_id, row["request_id"], row["requested_at"])
        if group_max_ids.get(group) != int(row["id"]):
            # A higher-id sibling is the row the account rollup folds, and its
            # cost is already counted. Adding this one would double-charge.
            continue
        account_deltas[str(account_id)] = account_deltas.get(str(account_id), 0.0) + float(row["cost_usd"])
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


def _owns_price_elsewhere(request_logs: Any, columns: set[str]) -> Any:
    """Rows whose writer already settled the price; the static table must not answer.

    Mirrors ``app.core.usage.logs.declares_price_provenance``: any
    ``price_status`` marks a row that participates in external price
    resolution, and any ``cost_source`` other than ``static_table`` names a
    resolved owner. For such rows a NULL ``cost_usd`` is the resolver's
    answer, not a gap this substring-matched list price may fill. Legacy rows
    predating both columns carry NULL in each and stay eligible.
    """

    clauses = []
    if "cost_source" in columns:
        clauses.append(
            sa.or_(
                request_logs.c.cost_source.is_(None),
                request_logs.c.cost_source == _STATIC_TABLE,
            )
        )
    if "price_status" in columns:
        clauses.append(request_logs.c.price_status.is_(None))
    return sa.and_(*clauses) if clauses else sa.true()


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, "request_logs"):
        return

    request_logs = _request_logs_table()
    log_columns = _columns(bind, "request_logs")
    has_cost_source = "cost_source" in log_columns
    eligible = _owns_price_elsewhere(request_logs, log_columns)
    watermark = _read_watermark(bind)
    backfilled_folded: list[dict[str, Any]] = []
    earliest_repriced: datetime | None = None

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
                    _model_match(request_logs),
                    request_logs.c.cost_usd.is_(None),
                    eligible,
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
            values: dict[str, Any] = {"cost_usd": cost}
            if has_cost_source:
                values["cost_source"] = _STATIC_TABLE
            bind.execute(sa.update(request_logs).where(request_logs.c.id == row["id"]).values(**values))
            requested_at = _as_datetime(row["requested_at"])
            if requested_at is not None and (earliest_repriced is None or requested_at < earliest_repriced):
                earliest_repriced = requested_at
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

    account_deltas, key_deltas = _accumulate_deltas(bind, backfilled_folded)
    _apply_deltas(bind, account_deltas, key_deltas, sign=1)
    _arm_time_rollup_repair(bind, earliest_repriced)


def downgrade() -> None:
    """Intentionally does not un-price anything.

    Nothing in the schema records which rows this migration filled. A row it
    repriced and a row the request path priced from the same static table are
    byte-for-byte identical afterwards -- same ``cost_usd``, same
    ``cost_source='static_table'`` -- so any reversal keyed on the model name
    or on ``cost_source`` would blank costs the migration never wrote and
    subtract them from rollups that legitimately contain them. That is
    destructive and unrecoverable: the price cannot be re-derived once the
    pricing row is gone.

    Leaving the recomputed costs in place is the safe direction. They are
    correct published list prices for usage that really happened, every rollup
    stays consistent with the rows it folds, and re-running ``upgrade()`` is a
    no-op because those rows are no longer NULL. The same choice was made by
    the useragent-family backfill
    (``20260722_000000_backfill_request_log_useragent_families``).
    """

    return
