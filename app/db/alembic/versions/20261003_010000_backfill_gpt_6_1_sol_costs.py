"""backfill gpt-6.1-sol request log costs

Revision ID: 20261003_010000_backfill_gpt_6_1_sol_costs
Revises: 20261003_000000_price_external_cache_reads
Create Date: 2026-10-03 01:00:00.000000

GPT-6.1 Sol traffic was logged before ``DEFAULT_PRICING_MODELS`` had a price
for it, so those rows persisted ``cost_usd = NULL`` and every cost report left
them out. This revision prices them at the list rates OpenAI publishes for
``gpt-6.1-sol``, exactly as the request path now prices new traffic, and moves
every rollup that already folded those rows by exactly the cost it added.

It follows ``20260922_000000_backfill_gpt_6_sol_luna_costs`` with two changes:

* The rates and the id rule are frozen in this file (``_GPT61_SOL_PRICE`` and
  ``_is_gpt61_sol``), so a later edit to the live table can neither change
  what this revision writes nor leave it pricing nothing.
* A row below the first hour the post-upgrade repair can refold
  (``ceil_hour(earliest raw row)``) adds its cost to its hourly bucket and
  demand slot directly, as ``20261003_000000_price_external_cache_reads``
  does. Retention already pruned part of that hour, so the repair never
  refolds it. Pruned rows themselves stay unpriced: a bucket keeps only token
  sums, not the per-request tier and context size a price needs.

Invariants kept from the template:

* Rows whose writer already settled their price are never touched: any
  ``price_status``, or a ``cost_source`` other than ``static_table``
  (``app.core.usage.logs.declares_price_provenance``).
* The lifetime rollups fold rows up to ``folded_through``. The account rollup
  gains a row's cost only when that row is its ``(account_id, request_id,
  requested_at)`` group's true ``max(id)``; the API-key rollup gains every
  non-warmup row, soft-deleted included.
* Hourly and demand buckets the surviving raw rows cover are refolded from raw
  by arming ``upgrade_repair_from``.

Not repaired: ``api_key_limits.current_value`` of a ``cost_usd`` limit. That
counter restarts at each window reset, and raising it now could block a key
for usage it was already allowed.

``downgrade()`` deliberately does not un-price anything: see its docstring.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection, RowMapping

from app.core.usage.pricing import ModelPrice, UsageTokens, calculate_cost_from_usage

revision = "20261003_010000_backfill_gpt_6_1_sol_costs"
down_revision = "20261003_000000_price_external_cache_reads"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

# Frozen copy of the ``gpt-6.1-sol`` entry of ``DEFAULT_PRICING_MODELS``: the
# list rates OpenAI publishes, USD per 1M tokens (developers.openai.com/api/docs/pricing).
_GPT61_SOL_PRICE = ModelPrice(
    input_per_1m=2.0,
    cached_input_per_1m=0.10,
    output_per_1m=10.0,
    priority_input_per_1m=4.0,
    priority_cached_input_per_1m=0.20,
    priority_output_per_1m=20.0,
    flex_input_per_1m=1.0,
    flex_cached_input_per_1m=0.05,
    flex_output_per_1m=5.0,
    long_context_threshold_tokens=272_000,
    long_context_input_per_1m=4.0,
    long_context_cached_input_per_1m=0.20,
    long_context_output_per_1m=15.0,
)
# Frozen copy of the ids ``get_pricing_for_model`` resolves to this entry: the
# bounded versioned identity ``app.core.usage.model_ids._GPT61_SOL_ID``, or the
# exact key behind one leading ``cc/``, ``cp-`` or ``cp_`` routing prefix. The
# LIKE prefilter also matches lookalikes such as ``gpt-6.1-sol-pro``; only these
# ids receive the list price.
_GPT61_SOL_KEY = "gpt-6.1-sol"
_GPT61_SOL_ID = re.compile(
    r"(?:(?:codex|openai)/)?gpt-6\.1-sol(?:-\d{4}-\d{2}-\d{2}|-\d{8})?",
    re.IGNORECASE,
)
_SIDECAR_PREFIXES = ("cc/", "cp-", "cp_")
_MODEL_MATCH = "%gpt-6.1-sol%"

_LOGS_TABLE = "request_logs"
_STATE_TABLE = "account_usage_rollup_state"
_HOURLY_TABLE = "request_usage_hourly_rollups"
_QUARTER_TABLE = "request_demand_quarter_rollups"
_STATIC_TABLE = "static_table"

_ROLLUP_STATE_ID = 1
_EXCLUDED_REQUEST_KINDS = ("warmup", "limit_warmup")
_DIMENSION_SENTINEL = "\x1f"
_HOUR_SECONDS = 3600
_QUARTER_SECONDS = 900
_EPOCH = datetime(1970, 1, 1)
_HOUR = timedelta(hours=1)
_BATCH_SIZE = 1000
# One bind parameter per id in the duplicate-group ``IN`` list. SQLite builds
# older than 3.32 allow 999, so chunk conservatively (as the template does).
_IN_CHUNK_SIZE = 250

_HourlyKey = tuple[int, str, str, str, str, str, bool]
_QuarterKey = tuple[int, str, str, str, str, str, str, bool]

_HOURLY_KEY_COLUMNS = (
    "bucket_epoch",
    "account_id",
    "api_key_id",
    "model",
    "service_tier",
    "request_kind",
    "is_deleted",
)
_QUARTER_KEY_COLUMNS = (
    "slot_epoch",
    "account_id",
    "api_key_id",
    "model",
    "reasoning_effort",
    "request_kind",
    "status",
    "is_deleted",
)


# Alembic executes revision files without registering them in ``sys.modules``,
# where ``dataclasses`` resolves string annotations, so the value types in this
# file are plain classes.
class _BelowFloor:
    """Cost and priced-row count each unrefoldable bucket gains."""

    def __init__(self) -> None:
        self.hourly_cost: dict[_HourlyKey, float] = defaultdict(float)
        self.hourly_count: dict[_HourlyKey, int] = defaultdict(int)
        self.quarter_cost: dict[_QuarterKey, float] = defaultdict(float)


class _Report:
    """What the upgrade changed, for its log line."""

    def __init__(self) -> None:
        self.priced_rows: int = 0
        self.priced_usd: float = 0.0
        self.hourly_buckets: int = 0
        self.quarter_slots: int = 0


def _is_gpt61_sol(model: str) -> bool:
    """Whether the request path prices ``model`` as ``gpt-6.1-sol``."""

    if _GPT61_SOL_ID.fullmatch(model.strip()) is not None:
        return True
    lowered = model.lower()
    for prefix in _SIDECAR_PREFIXES:
        if lowered.startswith(prefix):
            return lowered[len(prefix) :] == _GPT61_SOL_KEY
    return False


def _model_match(logs: Any) -> Any:
    """Prefilter for rows whose model could be ``gpt-6.1-sol``."""

    # PostgreSQL LIKE is case-sensitive. A lowercase pattern on the raw column
    # would skip GPT-6.1-SOL-20261001 before the case-insensitive id check runs.
    return sa.func.lower(logs.c.model).like(_MODEL_MATCH)


def _calculate_cost(row: RowMapping) -> float | None:
    """``calculated_cost_from_log`` at the frozen rates, or ``None`` when the row cannot be priced."""

    model = row["model"]
    if not model or not _is_gpt61_sol(model):
        return None
    input_tokens = row["input_tokens"]
    if input_tokens is None:
        return None
    output_tokens = row["output_tokens"] if row["output_tokens"] is not None else row["reasoning_tokens"]
    if output_tokens is None:
        return None
    cached_tokens = max(0, min(int(row["cached_input_tokens"] or 0), int(input_tokens)))
    return calculate_cost_from_usage(
        UsageTokens(
            input_tokens=float(input_tokens),
            output_tokens=float(output_tokens),
            cached_input_tokens=float(cached_tokens),
        ),
        _GPT61_SOL_PRICE,
        service_tier=row["service_tier"],
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


def _epoch_seconds(value: datetime) -> int:
    """Mirror of ``usage_time_rollup.epoch_seconds`` (sub-seconds truncated)."""

    return int((value - _EPOCH).total_seconds())


def _floor_to_hour(value: datetime) -> datetime:
    return _EPOCH + timedelta(seconds=(_epoch_seconds(value) // _HOUR_SECONDS) * _HOUR_SECONDS)


def _ceil_to_hour(value: datetime) -> datetime:
    floored = _floor_to_hour(value)
    return floored if floored == value else floored + _HOUR


def _to_dimension(value: str | None) -> str:
    """Mirror of ``usage_time_rollup.to_dimension``."""

    if value is None:
        return _DIMENSION_SENTINEL
    if value.startswith(_DIMENSION_SENTINEL):
        return _DIMENSION_SENTINEL + value
    return value


def _request_logs_table() -> Any:
    return sa.table(
        _LOGS_TABLE,
        sa.column("id", sa.Integer()),
        sa.column("account_id", sa.String()),
        sa.column("api_key_id", sa.String()),
        sa.column("request_id", sa.String()),
        sa.column("model", sa.String()),
        sa.column("service_tier", sa.String()),
        sa.column("reasoning_effort", sa.String()),
        sa.column("status", sa.String()),
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


def _state_table() -> Any:
    return sa.table(
        _STATE_TABLE,
        sa.column("id", sa.Integer()),
        sa.column("folded_through", sa.DateTime()),
        sa.column("hourly_folded_through", sa.DateTime()),
        sa.column("upgrade_repair_from", sa.DateTime()),
    )


def _hourly_table() -> Any:
    return sa.table(
        _HOURLY_TABLE,
        sa.column("bucket_epoch", sa.BigInteger()),
        sa.column("account_id", sa.String()),
        sa.column("api_key_id", sa.String()),
        sa.column("model", sa.String()),
        sa.column("service_tier", sa.String()),
        sa.column("request_kind", sa.String()),
        sa.column("is_deleted", sa.Boolean()),
        sa.column("cost_usd", sa.Float()),
        sa.column("cost_count", sa.BigInteger()),
    )


def _quarter_table() -> Any:
    return sa.table(
        _QUARTER_TABLE,
        sa.column("slot_epoch", sa.BigInteger()),
        sa.column("account_id", sa.String()),
        sa.column("api_key_id", sa.String()),
        sa.column("model", sa.String()),
        sa.column("reasoning_effort", sa.String()),
        sa.column("request_kind", sa.String()),
        sa.column("status", sa.String()),
        sa.column("is_deleted", sa.Boolean()),
        sa.column("cost_usd", sa.Float()),
    )


def _lock_rollup_state(bind: Connection) -> None:
    """Hold the fold-state row until this migration commits (see the template).

    PostgreSQL honors ``FOR UPDATE``, which the fold passes also take. SQLite
    ignores it, so a same-value update reserves the writer lock instead.
    """

    if not _has_table(bind, _STATE_TABLE):
        return
    state = _state_table()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.select(state.c.folded_through).where(state.c.id == _ROLLUP_STATE_ID).with_for_update())
        return
    bind.execute(sa.update(state).where(state.c.id == _ROLLUP_STATE_ID).values(folded_through=state.c.folded_through))


def _read_state(bind: Connection) -> tuple[datetime | None, datetime | None]:
    """``(folded_through, hourly_folded_through)``."""

    columns = _columns(bind, _STATE_TABLE)
    if not {"folded_through", "hourly_folded_through", "upgrade_repair_from"} <= columns:
        return None, None
    state = _state_table()
    row = bind.execute(
        sa.select(state.c.folded_through, state.c.hourly_folded_through).where(state.c.id == _ROLLUP_STATE_ID)
    ).first()
    if row is None:
        return None, None
    return _as_datetime(row[0]), _as_datetime(row[1])


def _refold_floor(bind: Connection) -> datetime | None:
    """First hour the post-upgrade repair can refold: ``ceil_hour(earliest raw row)``.

    Mirrors ``_repair_next_upgrade_chunk``: an unfiltered minimum, because
    retention prunes oldest first, so every row from there on survives.
    """

    logs = _request_logs_table()
    earliest = _as_datetime(bind.execute(sa.select(sa.func.min(logs.c.requested_at))).scalar())
    return None if earliest is None else _ceil_to_hour(earliest)


def _group_max_ids(bind: Connection, rows: list[dict[str, Any]]) -> dict[tuple[object, object, object], int]:
    """True ``max(id)`` per ``(account_id, request_id, requested_at)`` over all rows.

    Copied from ``20260922_000000_backfill_gpt_6_sol_luna_costs``: the account
    rollup folds only each duplicate group's highest id, whatever its model.
    """

    request_ids = {row["request_id"] for row in rows if row["account_id"] and row["deleted_at"] is None}
    request_ids.discard(None)
    if not request_ids:
        return {}
    logs = _request_logs_table()
    max_ids: dict[tuple[object, object, object], int] = {}
    ids = sorted(request_ids)
    for chunk_start in range(0, len(ids), _IN_CHUNK_SIZE):
        chunk = ids[chunk_start : chunk_start + _IN_CHUNK_SIZE]
        grouped = bind.execute(
            sa.select(logs.c.account_id, logs.c.request_id, logs.c.requested_at, sa.func.max(logs.c.id))
            .where(
                logs.c.request_id.in_(chunk),
                logs.c.account_id.is_not(None),
                logs.c.deleted_at.is_(None),
                logs.c.request_kind.not_in(_EXCLUDED_REQUEST_KINDS),
            )
            .group_by(logs.c.account_id, logs.c.request_id, logs.c.requested_at)
        ).all()
        for account_id, request_id, requested_at, max_id in grouped:
            if max_id is not None:
                max_ids[(account_id, request_id, requested_at)] = int(max_id)
    return max_ids


def _lifetime_deltas(bind: Connection, rows: list[dict[str, Any]]) -> tuple[dict[str, float], dict[str, float]]:
    """Per-account and per-API-key deltas for priced rows the lifetime rollups folded.

    The API-key rollup counts every non-warmup row, soft-deleted included. The
    account rollup counts one row per duplicate group, the group's true
    ``max(id)``, and skips soft-deleted rows.
    """

    countable = [row for row in rows if row["request_kind"] not in _EXCLUDED_REQUEST_KINDS]
    key_deltas: dict[str, float] = defaultdict(float)
    for row in countable:
        if row["api_key_id"]:
            key_deltas[str(row["api_key_id"])] += row["delta"]
    group_max_ids = _group_max_ids(bind, countable)
    account_deltas: dict[str, float] = defaultdict(float)
    for row in countable:
        account_id = row["account_id"]
        if not account_id or row["deleted_at"] is not None:
            continue
        if group_max_ids.get((account_id, row["request_id"], row["requested_at"])) != int(row["id"]):
            continue
        account_deltas[str(account_id)] += row["delta"]
    return account_deltas, key_deltas


def _apply_lifetime_deltas(
    bind: Connection, account_deltas: Mapping[str, float], key_deltas: Mapping[str, float]
) -> None:
    for table_name, id_column, deltas in (
        ("account_usage_rollups", "account_id", account_deltas),
        ("api_key_usage_rollups", "api_key_id", key_deltas),
    ):
        if not deltas or not _has_table(bind, table_name):
            continue
        rollups = sa.table(table_name, sa.column(id_column, sa.String()), sa.column("total_cost_usd", sa.Float()))
        for owner_id, delta in deltas.items():
            if delta:
                bind.execute(
                    sa.update(rollups)
                    .where(rollups.c[id_column] == owner_id)
                    .values(total_cost_usd=rollups.c.total_cost_usd + delta)
                )


def _hourly_key(row: RowMapping, requested_at: datetime) -> _HourlyKey:
    bucket = (_epoch_seconds(requested_at) // _HOUR_SECONDS) * _HOUR_SECONDS
    return (
        bucket,
        _to_dimension(row["account_id"]),
        _to_dimension(row["api_key_id"]),
        row["model"],
        _to_dimension(row["service_tier"]),
        row["request_kind"],
        row["deleted_at"] is not None,
    )


def _quarter_key(row: RowMapping, requested_at: datetime) -> _QuarterKey:
    slot = (_epoch_seconds(requested_at) // _QUARTER_SECONDS) * _QUARTER_SECONDS
    return (
        slot,
        _to_dimension(row["account_id"]),
        _to_dimension(row["api_key_id"]),
        row["model"],
        _to_dimension(row["reasoning_effort"]),
        row["request_kind"],
        row["status"],
        row["deleted_at"] is not None,
    )


def _price_rows(
    bind: Connection,
    *,
    folded_through: datetime | None,
    hourly_watermark: datetime | None,
    refold_floor: datetime | None,
    report: _Report,
) -> tuple[datetime | None, _BelowFloor]:
    """Price NULL-cost rows; returns the earliest priced time and the unrefoldable bucket deltas."""

    logs = _request_logs_table()
    below = _BelowFloor()
    earliest: datetime | None = None
    last_seen_id = 0
    while True:
        rows = (
            bind.execute(
                sa.select(
                    logs.c.id,
                    logs.c.account_id,
                    logs.c.api_key_id,
                    logs.c.request_id,
                    logs.c.model,
                    logs.c.service_tier,
                    logs.c.reasoning_effort,
                    logs.c.status,
                    logs.c.request_kind,
                    logs.c.deleted_at,
                    logs.c.requested_at,
                    logs.c.input_tokens,
                    logs.c.output_tokens,
                    logs.c.cached_input_tokens,
                    logs.c.reasoning_tokens,
                )
                .where(
                    logs.c.id > last_seen_id,
                    _model_match(logs),
                    logs.c.cost_usd.is_(None),
                    sa.or_(logs.c.cost_source.is_(None), logs.c.cost_source == _STATIC_TABLE),
                    logs.c.price_status.is_(None),
                )
                .order_by(logs.c.id)
                .limit(_BATCH_SIZE)
            )
            .mappings()
            .all()
        )
        if not rows:
            break
        updates: list[dict[str, Any]] = []
        folded: list[dict[str, Any]] = []
        for row in rows:
            cost = _calculate_cost(row)
            requested_at = _as_datetime(row["requested_at"])
            if cost is None or requested_at is None:
                continue
            updates.append({"_request_log_id": row["id"], "_cost_usd": cost})
            report.priced_rows += 1
            report.priced_usd += cost
            if earliest is None or requested_at < earliest:
                earliest = requested_at
            if folded_through is not None and requested_at <= folded_through:
                folded.append({**row, "delta": cost})
            # Folded into a bucket the post-upgrade repair cannot refold.
            if (
                refold_floor is not None
                and hourly_watermark is not None
                and requested_at < refold_floor
                and requested_at < hourly_watermark
            ):
                hourly_key = _hourly_key(row, requested_at)
                below.hourly_cost[hourly_key] += cost
                below.hourly_count[hourly_key] += 1
                below.quarter_cost[_quarter_key(row, requested_at)] += cost
        if updates:
            bind.execute(
                sa.update(logs)
                .where(logs.c.id == sa.bindparam("_request_log_id"))
                .values(cost_usd=sa.bindparam("_cost_usd"), cost_source=_STATIC_TABLE),
                updates,
            )
        _apply_lifetime_deltas(bind, *_lifetime_deltas(bind, folded))
        last_seen_id = int(rows[-1]["id"])
    return earliest, below


def _patch_buckets_below_floor(bind: Connection, below: _BelowFloor, report: _Report) -> None:
    """Add each unrefoldable bucket's priced rows, as the fold would have counted them.

    The hourly fold sums ``cost_usd`` and counts non-NULL costs in
    ``cost_count``; the demand fold sums ``cost_usd`` only. A zero-cost row
    still counts, exactly as it would have at insert time.
    """

    if below.hourly_count and _has_table(bind, _HOURLY_TABLE):
        hourly = _hourly_table()
        for key, count in below.hourly_count.items():
            result = bind.execute(
                sa.update(hourly)
                .where(*(hourly.c[column] == value for column, value in zip(_HOURLY_KEY_COLUMNS, key, strict=True)))
                .values(cost_usd=hourly.c.cost_usd + below.hourly_cost[key], cost_count=hourly.c.cost_count + count)
            )
            report.hourly_buckets += result.rowcount
    if below.quarter_cost and _has_table(bind, _QUARTER_TABLE):
        quarter = _quarter_table()
        for key, cost in below.quarter_cost.items():
            result = bind.execute(
                sa.update(quarter)
                .where(*(quarter.c[column] == value for column, value in zip(_QUARTER_KEY_COLUMNS, key, strict=True)))
                .values(cost_usd=quarter.c.cost_usd + cost)
            )
            report.quarter_slots += result.rowcount


def _arm_time_rollup_repair(
    bind: Connection, earliest_priced: datetime | None, hourly_watermark: datetime | None
) -> None:
    """Point ``upgrade_repair_from`` at the earliest priced hour (template rules).

    The repair clamps its start to ``ceil_hour(earliest raw row)``, so a marker
    below that floor refolds exactly the range the raw rows still cover. An
    earlier marker already set by another upgrade is kept.
    """

    if earliest_priced is None or hourly_watermark is None or earliest_priced >= hourly_watermark:
        return
    marker = _floor_to_hour(earliest_priced)
    state = _state_table()
    existing = _as_datetime(
        bind.execute(sa.select(state.c.upgrade_repair_from).where(state.c.id == _ROLLUP_STATE_ID)).scalar()
    )
    if existing is not None and existing <= marker:
        return
    bind.execute(sa.update(state).where(state.c.id == _ROLLUP_STATE_ID).values(upgrade_repair_from=marker))


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, _LOGS_TABLE):
        return

    _lock_rollup_state(bind)
    folded_through, hourly_watermark = _read_state(bind)
    report = _Report()
    earliest, below = _price_rows(
        bind,
        folded_through=folded_through,
        hourly_watermark=hourly_watermark,
        refold_floor=_refold_floor(bind),
        report=report,
    )
    _patch_buckets_below_floor(bind, below, report)
    _arm_time_rollup_repair(bind, earliest, hourly_watermark)

    logger.info(
        "gpt-6.1-sol cost backfill: priced %d request logs (%.2f USD); "
        "patched %d hourly buckets and %d demand slots below the refold floor",
        report.priced_rows,
        report.priced_usd,
        report.hourly_buckets,
        report.quarter_slots,
    )


def downgrade() -> None:
    """Intentionally does not un-price anything.

    Nothing in the schema records which rows this revision filled. A row it
    priced and a row the request path priced from the same table are identical
    afterwards (same ``cost_usd``, same ``cost_source='static_table'``), so a
    reversal keyed on the model or on ``cost_source`` would blank costs this
    revision never wrote and subtract them from rollups that legitimately hold
    them. The costs are the published list price of usage that really
    happened, every rollup stays consistent with the rows it folds, and
    re-running ``upgrade()`` is a no-op because those rows are no longer NULL.
    The same choice was made by ``20260922_000000_backfill_gpt_6_sol_luna_costs``.
    """

    return
