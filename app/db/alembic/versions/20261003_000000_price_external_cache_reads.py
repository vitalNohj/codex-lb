"""price external cache reads at the published cache-read rate

Revision ID: 20261003_000000_price_external_cache_reads
Revises: 20260928_000000_pin_claude_sonnet_5_5_full_model
Create Date: 2026-10-03 00:00:00.000000

Until this revision ``external_model_prices`` kept only a catalog's input and
output rate, so every cache-read token was charged at the full input rate even
where the catalog publishes a cache-read rate a tenth of it or less. Claude
traffic served through CLIProxyAPI is almost entirely cache reads, so its
calculated list price was inflated roughly fivefold to twentyfold.

This revision:

1. Adds ``external_model_prices.cached_input_per_1m``. The request path charges
   cached input at that rate, and at the input rate only when the catalog
   published none.
2. Seeds that rate for resolved records priced from the OpenRouter reference
   catalog, from the card OpenRouter published on 2026-10-03 (see
   ``_OPENROUTER_CARDS``). A record is seeded only when its stored input and
   output rates equal that card's, so no record is paired with a cache-read
   rate from a different card. Every other record keeps NULL until
   ``codex-lb model-prices refresh`` re-reads its catalog.
3. Reprices ``catalog_calculated`` request logs whose stored cost provably is
   the full-input-rate figure for a seeded record, and moves every rollup that
   already folded the old figure by exactly the same delta.

Rollup repair, by table:

* The lifetime account and API-key rollups fold rows up to ``folded_through``.
  Each repriced row at or below it adds its delta, with the account rollup's
  ``max(id)`` duplicate rule (same helpers as
  ``20260922_000000_backfill_gpt_6_sol_luna_costs``).
* Hourly and demand buckets that surviving raw rows fully cover (from
  ``ceil_hour(earliest raw row)``) are refolded from raw by arming the
  existing ``upgrade_repair_from`` marker. Retention pauses request-log
  pruning while that marker is set, so the repair never loses its rows.
* A bucket below that floor can never be refolded: retention already pruned
  some or all of its rows. It moves by exactly the deltas of its surviving
  repriced rows.

Not repaired:

* Rows retention already pruned. Their share of a bucket below the floor, and
  of the lifetime totals that folded them, keeps its stored figure. A bucket
  records neither which integration served its rows nor how they were priced,
  so a total that matches the full-input-rate formula can still hold
  upstream-billed or operator-configured costs.
* ``api_key_limits.current_value`` of a ``cost_usd`` limit. That counter
  restarts at each window reset, so an overcount there clears itself.
* Rows priced by any other catalog. Without a dated, published cache-read rate
  for the card they were charged at, a corrected figure would be a guess.

``downgrade()`` drops the column and deliberately keeps the corrected costs:
see its docstring.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any, NamedTuple

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection, RowMapping

revision = "20261003_000000_price_external_cache_reads"
down_revision = "20260928_000000_pin_claude_sonnet_5_5_full_model"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

_PRICES_TABLE = "external_model_prices"
_LOGS_TABLE = "request_logs"
_STATE_TABLE = "account_usage_rollup_state"
_HOURLY_TABLE = "request_usage_hourly_rollups"
_QUARTER_TABLE = "request_demand_quarter_rollups"
_CACHED_COLUMN = "cached_input_per_1m"

_RESOLVED = "resolved"
_CATALOG_CALCULATED = "catalog_calculated"
_OPENROUTER_REFERENCE_SOURCE = "openrouter:reference"
_PER_TOKEN_TO_PER_1M = 1_000_000.0

# The OpenRouter reference catalog (https://openrouter.ai/api/v1/models) as
# published on 2026-10-03: catalog model -> per-token USD ``prompt``,
# ``completion`` and ``input_cache_read`` exactly as served. Converted with the
# runtime parser's arithmetic, so a seeded rate is bit-identical to the one a
# later refresh stores and that refresh reports no change.
#
# This dated snapshot exists only to repair history. The request path never
# reads it, and it can attach a cache-read rate only to a record whose input and
# output rates already equal the same published card.
_OPENROUTER_CARDS: dict[str, tuple[str, str, str]] = {
    "anthropic/claude-sonnet-5.5": ("0.000002", "0.00001", "0.0000002"),
    "anthropic/claude-opus-5.5": ("0.000004", "0.00002", "0.0000002"),
    "anthropic/claude-fable-5.1": ("0.00001", "0.00005", "0.00000025"),
    "anthropic/claude-opus-5": ("0.000005", "0.000025", "0.0000005"),
    "anthropic/claude-sonnet-5": ("0.000002", "0.00001", "0.0000002"),
    "anthropic/claude-fable-5": ("0.00001", "0.00005", "0.000001"),
    "anthropic/claude-opus-4.8": ("0.000005", "0.000025", "0.0000005"),
    "anthropic/claude-opus-4.7": ("0.000005", "0.000025", "0.0000005"),
    "anthropic/claude-sonnet-4.6": ("0.000003", "0.000015", "0.0000003"),
    "anthropic/claude-opus-4.6": ("0.000005", "0.000025", "0.0000005"),
    "anthropic/claude-opus-4.5": ("0.000005", "0.000025", "0.0000005"),
    "anthropic/claude-haiku-4.5": ("0.000001", "0.000005", "0.0000001"),
    "anthropic/claude-sonnet-4.5": ("0.000003", "0.000015", "0.0000003"),
    "anthropic/claude-opus-4.1": ("0.000015", "0.000075", "0.0000015"),
    "anthropic/claude-sonnet-4": ("0.000003", "0.000015", "0.0000003"),
}

# ``RequestLog.source`` -> pricing provider key, frozen from
# ``app.core.usage.external_pricing.providers`` as of this revision.
_LOG_SOURCE_PROVIDERS: dict[str, str] = {
    "openrouter_sidecar": "openrouter",
    "orcarouter_sidecar": "orcarouter",
    "claude_sidecar": "cliproxy",
    "opencode_go_sidecar": "opencode_go",
}
_OPENAI_COMPAT_PROVIDER_PREFIX = "openai_compat:"

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
# Stored costs are recomputed with the request path's own arithmetic, so a
# genuine match agrees to the last bit. The tolerance only absorbs
# floating-point rounding, far below any real difference between two prices.
_REL_TOLERANCE = 1e-9
_ABS_TOLERANCE = 1e-12

_HourlyKey = tuple[int, str, str, str, str, str, bool]
_QuarterKey = tuple[int, str, str, str, str, str, str, bool]


# Alembic executes revision files without registering them in ``sys.modules``,
# where ``dataclasses`` resolves string annotations, so the value types in this
# file are NamedTuples and a plain class.
class _Rates(NamedTuple):
    input_per_1m: float
    output_per_1m: float
    cached_input_per_1m: float


class _Report:
    """What the upgrade changed, for its log lines."""

    def __init__(self) -> None:
        self.seeded: int = 0
        self.unseeded: list[str] = []
        self.repriced_rows: int = 0
        self.row_delta_usd: float = 0.0
        self.unverified_rows: int = 0
        self.hourly_buckets: int = 0
        self.quarter_slots: int = 0


def _same(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=_REL_TOLERANCE, abs_tol=_ABS_TOLERANCE)


def _cost(
    input_tokens: float, output_tokens: float, cached_tokens: float, rates: _Rates, *, cached_rate: float
) -> float:
    """``calculate_cost_breakdown_from_usage`` for a record price, same operation order."""

    billable_input = max(0.0, input_tokens - cached_tokens)
    input_usd = (billable_input / 1_000_000) * rates.input_per_1m
    cached_input_usd = (cached_tokens / 1_000_000) * cached_rate
    output_usd = (output_tokens / 1_000_000) * rates.output_per_1m
    return input_usd + cached_input_usd + output_usd


def _full_rate_cost(input_tokens: float, output_tokens: float, cached_tokens: float, rates: _Rates) -> float:
    return _cost(input_tokens, output_tokens, cached_tokens, rates, cached_rate=rates.input_per_1m)


def _published_cost(input_tokens: float, output_tokens: float, cached_tokens: float, rates: _Rates) -> float:
    return _cost(input_tokens, output_tokens, cached_tokens, rates, cached_rate=rates.cached_input_per_1m)


def _per_1m(per_token: str) -> float:
    return float(per_token) * _PER_TOKEN_TO_PER_1M


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


def _lookup_key(value: str) -> str:
    return value.strip().lower()


def _provider_for_source(source: str | None) -> str | None:
    if not source:
        return None
    lowered = source.strip().lower()
    if lowered.startswith(_OPENAI_COMPAT_PROVIDER_PREFIX):
        return lowered
    return _LOG_SOURCE_PROVIDERS.get(lowered)


def _prices_table() -> Any:
    return sa.table(
        _PRICES_TABLE,
        sa.column("id", sa.Integer()),
        sa.column("provider", sa.String()),
        sa.column("incoming_model", sa.String()),
        sa.column("status", sa.String()),
        sa.column("catalog_model", sa.String()),
        sa.column("catalog_source", sa.String()),
        sa.column("input_per_1m", sa.Float()),
        sa.column("output_per_1m", sa.Float()),
        sa.column(_CACHED_COLUMN, sa.Float()),
    )


def _request_logs_table() -> Any:
    return sa.table(
        _LOGS_TABLE,
        sa.column("id", sa.Integer()),
        sa.column("account_id", sa.String()),
        sa.column("api_key_id", sa.String()),
        sa.column("request_id", sa.String()),
        sa.column("model", sa.String()),
        sa.column("source", sa.String()),
        sa.column("service_tier", sa.String()),
        sa.column("reasoning_effort", sa.String()),
        sa.column("status", sa.String()),
        sa.column("request_kind", sa.String()),
        sa.column("deleted_at", sa.DateTime()),
        sa.column("requested_at", sa.DateTime()),
        sa.column("input_tokens", sa.Integer()),
        sa.column("output_tokens", sa.Integer()),
        sa.column("cached_input_tokens", sa.Integer()),
        sa.column("cost_usd", sa.Float()),
        sa.column("cost_source", sa.String()),
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


def _add_cached_rate_column(bind: Connection) -> None:
    if _CACHED_COLUMN in _columns(bind, _PRICES_TABLE):
        return
    with op.batch_alter_table(_PRICES_TABLE) as batch_op:
        batch_op.add_column(sa.Column(_CACHED_COLUMN, sa.Float(), nullable=True))


def _card_rates(catalog_model: str | None) -> _Rates | None:
    card = _OPENROUTER_CARDS.get(catalog_model or "")
    if card is None:
        return None
    prompt, completion, cache_read = card
    return _Rates(_per_1m(prompt), _per_1m(completion), _per_1m(cache_read))


def _seed_cached_rates(bind: Connection, report: _Report) -> None:
    """Attach the dated OpenRouter cache-read rate to records charged at that card."""

    prices = _prices_table()
    rows = (
        bind.execute(
            sa.select(
                prices.c.id,
                prices.c.provider,
                prices.c.incoming_model,
                prices.c.catalog_model,
                prices.c.catalog_source,
                prices.c.input_per_1m,
                prices.c.output_per_1m,
            ).where(
                prices.c.status == _RESOLVED,
                prices.c[_CACHED_COLUMN].is_(None),
                prices.c.input_per_1m.is_not(None),
                prices.c.output_per_1m.is_not(None),
            )
        )
        .mappings()
        .all()
    )
    unseeded: list[str] = []
    for row in rows:
        card = _card_rates(row["catalog_model"]) if row["catalog_source"] == _OPENROUTER_REFERENCE_SOURCE else None
        if (
            card is None
            or not _same(float(row["input_per_1m"]), card.input_per_1m)
            or not _same(float(row["output_per_1m"]), card.output_per_1m)
        ):
            unseeded.append(f"{row['provider']}:{row['incoming_model']}")
            continue
        bind.execute(
            sa.update(prices).where(prices.c.id == row["id"]).values({_CACHED_COLUMN: card.cached_input_per_1m})
        )
        report.seeded += 1
    report.unseeded = sorted(unseeded)


def _priced_records(bind: Connection) -> dict[tuple[str, str], _Rates]:
    """Rates per ``(provider, model)`` key of every resolved record with a cache-read rate."""

    prices = _prices_table()
    rows = (
        bind.execute(
            sa.select(
                prices.c.provider,
                prices.c.incoming_model,
                prices.c.input_per_1m,
                prices.c.output_per_1m,
                prices.c[_CACHED_COLUMN],
            ).where(
                prices.c.status == _RESOLVED,
                prices.c.input_per_1m.is_not(None),
                prices.c.output_per_1m.is_not(None),
                prices.c[_CACHED_COLUMN].is_not(None),
            )
        )
        .mappings()
        .all()
    )
    return {
        (_lookup_key(row["provider"]), _lookup_key(row["incoming_model"])): _Rates(
            float(row["input_per_1m"]), float(row["output_per_1m"]), float(row[_CACHED_COLUMN])
        )
        for row in rows
    }


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
    retention prunes oldest first, so every row from there on survives. ``None``
    means no raw rows, so nothing can be refolded.
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
    """Per-account and per-API-key deltas for repriced rows the lifetime rollups folded.

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


def _corrected_row_cost(row: RowMapping, rates: _Rates, stored: float) -> float | None:
    """The published-rate cost of a row stored at either figure, else ``None``.

    A row already at the published figure (priced after this fix, by an earlier
    run of this revision, or with no discount to give) maps to its own cost and
    is left alone. ``None`` means the stored cost is neither figure, or the row
    lacks the token counts to tell.
    """

    if row["input_tokens"] is None or row["output_tokens"] is None:
        return None
    input_tokens = float(row["input_tokens"])
    output_tokens = float(row["output_tokens"])
    cached_tokens = max(0.0, min(float(row["cached_input_tokens"]), input_tokens))
    corrected = _published_cost(input_tokens, output_tokens, cached_tokens, rates)
    if _same(stored, corrected) or _same(stored, _full_rate_cost(input_tokens, output_tokens, cached_tokens, rates)):
        return corrected
    return None


class _BelowFloor(NamedTuple):
    """Deltas of surviving repriced rows inside buckets the repair can never refold."""

    hourly: dict[_HourlyKey, float]
    quarter: dict[_QuarterKey, float]


def _reprice_rows(
    bind: Connection,
    rates_by_key: Mapping[tuple[str, str], _Rates],
    *,
    folded_through: datetime | None,
    hourly_watermark: datetime | None,
    refold_floor: datetime | None,
    report: _Report,
) -> tuple[datetime | None, _BelowFloor]:
    """Reprice full-rate rows; returns the earliest repriced time and the unrefoldable bucket deltas."""

    logs = _request_logs_table()
    below = _BelowFloor(defaultdict(float), defaultdict(float))
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
                    logs.c.source,
                    logs.c.service_tier,
                    logs.c.reasoning_effort,
                    logs.c.status,
                    logs.c.request_kind,
                    logs.c.deleted_at,
                    logs.c.requested_at,
                    logs.c.input_tokens,
                    logs.c.output_tokens,
                    logs.c.cached_input_tokens,
                    logs.c.cost_usd,
                )
                .where(
                    logs.c.id > last_seen_id,
                    logs.c.cost_source == _CATALOG_CALCULATED,
                    logs.c.cost_usd.is_not(None),
                    logs.c.cached_input_tokens > 0,
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
            provider = _provider_for_source(row["source"])
            model = row["model"]
            rates = rates_by_key.get((provider, _lookup_key(model))) if provider and model else None
            requested_at = _as_datetime(row["requested_at"])
            if rates is None or requested_at is None:
                continue
            stored = float(row["cost_usd"])
            corrected = _corrected_row_cost(row, rates, stored)
            if corrected is None:
                # Not provably the full-rate figure for this record: missing
                # token counts, a rate that changed since, or a cost something
                # else wrote. Leave the row.
                report.unverified_rows += 1
                continue
            if _same(corrected, stored):
                continue
            delta = corrected - stored
            updates.append({"_request_log_id": row["id"], "_cost_usd": corrected})
            report.repriced_rows += 1
            report.row_delta_usd += delta
            if earliest is None or requested_at < earliest:
                earliest = requested_at
            if folded_through is not None and requested_at <= folded_through:
                folded.append({**row, "delta": delta})
            # Folded into a bucket the post-upgrade repair cannot refold.
            if (
                refold_floor is not None
                and hourly_watermark is not None
                and requested_at < refold_floor
                and requested_at < hourly_watermark
            ):
                below.hourly[_hourly_key(row, requested_at)] += delta
                below.quarter[_quarter_key(row, requested_at)] += delta
        if updates:
            bind.execute(
                sa.update(logs)
                .where(logs.c.id == sa.bindparam("_request_log_id"))
                .values(cost_usd=sa.bindparam("_cost_usd")),
                updates,
            )
        _apply_lifetime_deltas(bind, *_lifetime_deltas(bind, folded))
        last_seen_id = int(rows[-1]["id"])
    return earliest, below


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


def _patch_buckets_below_floor(bind: Connection, below: _BelowFloor, report: _Report) -> None:
    """Move each unrefoldable bucket by exactly the deltas of its surviving repriced rows.

    Only a surviving row shows how it was priced. The rest of such a bucket's
    total belongs to pruned rows, and a bucket records neither which
    integration served them nor their cost source, so that part keeps its
    stored figure even when it matches the full-input-rate formula.
    """

    if below.hourly and _has_table(bind, _HOURLY_TABLE):
        hourly = _hourly_table()
        for key, delta in below.hourly.items():
            result = bind.execute(
                sa.update(hourly)
                .where(*(hourly.c[column] == value for column, value in zip(_HOURLY_KEY_COLUMNS, key, strict=True)))
                .values(cost_usd=hourly.c.cost_usd + delta)
            )
            report.hourly_buckets += result.rowcount
    if below.quarter and _has_table(bind, _QUARTER_TABLE):
        quarter = _quarter_table()
        for key, delta in below.quarter.items():
            result = bind.execute(
                sa.update(quarter)
                .where(*(quarter.c[column] == value for column, value in zip(_QUARTER_KEY_COLUMNS, key, strict=True)))
                .values(cost_usd=quarter.c.cost_usd + delta)
            )
            report.quarter_slots += result.rowcount


def _arm_time_rollup_repair(
    bind: Connection, earliest_repriced: datetime | None, hourly_watermark: datetime | None
) -> None:
    """Point ``upgrade_repair_from`` at the earliest repriced hour (template rules).

    The repair clamps its start to ``ceil_hour(earliest raw row)``, so a marker
    below that floor refolds exactly the range the raw rows still cover. An
    earlier marker already set by another upgrade is kept.
    """

    if earliest_repriced is None or hourly_watermark is None or earliest_repriced >= hourly_watermark:
        return
    marker = _floor_to_hour(earliest_repriced)
    state = _state_table()
    existing = _as_datetime(
        bind.execute(sa.select(state.c.upgrade_repair_from).where(state.c.id == _ROLLUP_STATE_ID)).scalar()
    )
    if existing is not None and existing <= marker:
        return
    bind.execute(sa.update(state).where(state.c.id == _ROLLUP_STATE_ID).values(upgrade_repair_from=marker))


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, _PRICES_TABLE):
        return
    _add_cached_rate_column(bind)

    report = _Report()
    _seed_cached_rates(bind, report)
    if report.unseeded:
        logger.info(
            "external cache-read pricing: no dated card for %d resolved records; "
            "run `codex-lb model-prices refresh` to read their cache-read rates: %s",
            len(report.unseeded),
            ", ".join(report.unseeded),
        )
    if not _has_table(bind, _LOGS_TABLE):
        return
    rates_by_key = _priced_records(bind)
    if not rates_by_key:
        logger.info("external cache-read pricing: no seeded records; nothing to reprice")
        return

    _lock_rollup_state(bind)
    folded_through, hourly_watermark = _read_state(bind)
    earliest, below = _reprice_rows(
        bind,
        rates_by_key,
        folded_through=folded_through,
        hourly_watermark=hourly_watermark,
        refold_floor=_refold_floor(bind),
        report=report,
    )
    _patch_buckets_below_floor(bind, below, report)
    _arm_time_rollup_repair(bind, earliest, hourly_watermark)

    logger.info(
        "external cache-read pricing: seeded %d records; repriced %d request logs (%.2f USD); "
        "left %d unverifiable; moved %d hourly buckets and %d demand slots below the refold floor "
        "by their surviving rows' deltas",
        report.seeded,
        report.repriced_rows,
        report.row_delta_usd,
        report.unverified_rows,
        report.hourly_buckets,
        report.quarter_slots,
    )


def downgrade() -> None:
    """Drop the cache-read rate column. Corrected costs deliberately stay.

    Restoring the inflated figures would need the pre-upgrade costs, which
    nothing records, and they were wrong: the published cache-read rate is what
    those tokens cost. Every rollup stays consistent with the rows it folds,
    and re-running ``upgrade()`` changes nothing more, because corrected rows
    no longer match the full-rate figure.
    """

    bind = op.get_bind()
    if _CACHED_COLUMN in _columns(bind, _PRICES_TABLE):
        with op.batch_alter_table(_PRICES_TABLE) as batch_op:
            batch_op.drop_column(_CACHED_COLUMN)
