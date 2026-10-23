"""Rollup-served history statements for the reports reads.

The reports lifetime reads must cover history older than raw ``request_logs``
retention, so their windows are split into disjoint time segments served from
the store that holds each one — aggregated entirely in SQL (the outer
statement groups/unions; no rollup or raw ROW is ever materialized in
Python):

- Whole UTC days of the window strictly below the DAILY watermark come from
  ``request_usage_daily_rollups`` (one row per UTC day x dimensions — a
  decade of history is a few thousand rows).
- Whole hours inside the window but not covered by those days (the partial
  leading/trailing UTC days of the window, and days after the daily
  watermark) come from ``request_usage_hourly_rollups`` below the HOURLY
  watermark.
- Everything else — the sub-hour window edges and the live tail at or above
  the hourly watermark — comes from raw ``request_logs``.

Every rollup branch joins the SAME ``account_usage_rollup_state`` row and
binds its upper bounds to that row's OWN watermark columns (expressed in
SQL, not to a Python-read watermark), so a fold slice committing
concurrently can never pair rollup rows from one watermark generation with
bounds from another — the single-snapshot discipline of
``usage_time_rollup_read`` applied inside each branch. The raw tail is
bound to the same state row through an uncorrelated scalar subquery (the
``_conversation_tail_start`` pattern). The segments are exactly
disjoint:

    rolled region  = [ceil_hour(since), min(hourly_w, floor_hour(until)))
    daily segment  = [ceil_day(since), min(daily_w, floor_day(until)))  ⊂ rolled
    hourly segment = rolled minus the daily segment (the daily watermark is
                     day-aligned and the hourly watermark hour-aligned, so
                     the daily/hourly split never splits a day bucket)
    raw windows    = [since, ceil_hour(since)) ∪ [min(hourly_w, floor_hour(until)), until)

With no state row or epoch watermarks the rollup branches are empty and the
raw windows collapse to the full window — the readers degrade to the exact
legacy raw behaviour.

Dimension parity with the legacy raw queries: rollup dimensions are
sentinel-encoded NULLs (``to_dimension``), so dimension filters map through
the same injective encoding and labels unmap through its SQL mirror
(``_unmap_dimension_expr``); the warmup-exclusion part of
``_normal_traffic_clause`` becomes ``request_kind NOT IN warmup`` on the
rollup branches (the ``source = 'limit_warmup'`` half is subsumed — every
row the system writes with that source carries a warmup request kind; see
the fold module). Raw branches keep the full legacy clause. Soft-deleted
rows are included on both sides (the reports reads carry no ``deleted_at``
filter); ``is_deleted`` rides as a dimension.

Measures the rollups do not hold stay raw-only, disclosed by the service
via ``raw_metrics_since``: per-request medians (TTFT/TPS/queue), the
user-agent distribution (``useragent_group`` is not a rollup dimension —
user-agent-filtered reads keep the legacy raw path entirely), and the
reasoning-known request count outside the raw window (a per-ROW predicate
the fold never aggregated).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    ColumnElement,
    Integer,
    Select,
    and_,
    case,
    cast,
    func,
    literal,
    or_,
    select,
    union_all,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.selectable import CompoundSelect

from app.core.usage.logs import CANCELLED_STATUS, NON_ERROR_STATUSES
from app.db.models import (
    AccountUsageRollupState,
    RequestLog,
    RequestUsageDailyRollup,
    RequestUsageHourlyRollup,
)
from app.modules.accounts.usage_time_rollup import (
    _STATE_ROW_ID,
    DAILY_BUCKET_SECONDS,
    DIMENSION_SENTINEL,
    HOURLY_BUCKET_SECONDS,
    WARMUP_REQUEST_KINDS,
    epoch_seconds,
    to_dimension,
)
from app.modules.accounts.usage_time_rollup_read import (
    _greatest_fn,
    _least_fn,
    ceil_to_grid,
    floor_to_grid,
)

# NOTE: the raw clause builders live in ``app.modules.reports.repository``
# and are imported lazily inside ``_raw_dimension_filters`` — repository
# imports this module at its own module level, so a top-level import here
# would be circular.

_STATE = AccountUsageRollupState
_DAILY = RequestUsageDailyRollup
_HOURLY = RequestUsageHourlyRollup
_RAW = RequestLog


def _watermark_epoch_expr(session: AsyncSession, column) -> ColumnElement:
    """Epoch seconds of a state watermark column (whole hours/days, so the
    conversion is exact), dialect-split like the bucket expressions."""
    if session.get_bind().dialect.name == "postgresql":
        return cast(func.extract("epoch", column), BigInteger)
    return cast(func.strftime("%s", column), Integer)


def _floor_epoch_expr(session: AsyncSession, epoch_expr, grid_seconds: int) -> ColumnElement:
    """Dialect-split integer flooring of an epoch expression to a grid —
    SQLAlchemy renders ``/`` as true division (NUMERIC on PostgreSQL, where
    a bigint cast then ROUNDS), so mirror the rollup readers' arithmetic."""
    if session.get_bind().dialect.name == "postgresql":
        return cast(func.floor(epoch_expr / grid_seconds) * grid_seconds, BigInteger)
    return cast(epoch_expr / grid_seconds, Integer) * grid_seconds


def _month_expr(session: AsyncSession, epoch_column=None, datetime_column=None) -> ColumnElement:
    """UTC 'YYYY-MM' label of an epoch column or a naive-UTC datetime column."""
    if session.get_bind().dialect.name == "postgresql":
        if epoch_column is not None:
            return func.to_char(func.to_timestamp(epoch_column).op("AT TIME ZONE")("UTC"), "YYYY-MM")
        return func.to_char(datetime_column, "YYYY-MM")
    if epoch_column is not None:
        return func.strftime("%Y-%m", epoch_column, "unixepoch")
    return func.strftime("%Y-%m", datetime_column)


def month_label_expr(session: AsyncSession, *, epoch_column=None, datetime_column=None) -> ColumnElement:
    """Public wrapper around :func:`_month_expr` for raw-path month
    grouping (the UA-filtered monthly fallback)."""
    return _month_expr(session, epoch_column=epoch_column, datetime_column=datetime_column)


def _unmap_dimension_expr(column) -> ColumnElement:
    """SQL mirror of :func:`from_dimension` (sentinel -> NULL, escaped
    sentinel-prefixed values stripped one sentinel) so label/filter
    semantics match the raw queries' NULL handling."""
    return case(
        (column == DIMENSION_SENTINEL, literal(None)),
        (func.substr(column, 1, 1) == DIMENSION_SENTINEL, func.substr(column, 2)),
        else_=column,
    )


def _rollup_dimension_filters(
    table,
    *,
    account_ids: list[str] | None,
    model: str | None,
    api_key_ids: list[str] | None,
) -> list[ColumnElement[bool]]:
    """Report filters translated to rollup dimension clauses (sentinel
    encoding applied at the boundary). User-agent filtering is absent on
    purpose — callers must not take the rollup path for it."""
    clauses: list[ColumnElement[bool]] = []
    if account_ids:
        clauses.append(table.account_id.in_([to_dimension(account_id) for account_id in account_ids]))
    if model:
        clauses.append(table.model == to_dimension(model))
    if api_key_ids:
        clauses.append(table.api_key_id.in_([to_dimension(api_key_id) for api_key_id in api_key_ids]))
    return clauses


def _raw_dimension_filters(
    *,
    account_ids: list[str] | None,
    model: str | None,
    useragent_group: str | None,
    api_key_ids: list[str] | None,
) -> list[ColumnElement[bool]]:
    """The full legacy raw row filter (normal-traffic clause plus every
    report filter — raw is the only store holding the user-agent)."""
    from app.modules.reports.repository import (
        _normal_traffic_clause,
        _useragent_group_filter_clause,
    )

    clauses: list[ColumnElement[bool]] = [_normal_traffic_clause()]
    if account_ids:
        clauses.append(_RAW.account_id.in_(account_ids))
    if model:
        clauses.append(_RAW.model == model)
    useragent_group_clause = _useragent_group_filter_clause(useragent_group)
    if useragent_group_clause is not None:
        clauses.append(useragent_group_clause)
    if api_key_ids:
        clauses.append(_RAW.api_key_id.in_(api_key_ids))
    return clauses


def _measure_columns(session: AsyncSession, table, *, month: bool) -> list:
    """Uniform branch row shape: (month?, requests, input_tokens,
    output_tokens, reasoning_tokens, reasoning_known, cached_tokens,
    cost_usd, errors, cancelled, account_id, model)."""
    columns: list = []
    if month:
        if table is _DAILY:
            month_expr = _month_expr(session, epoch_column=table.day_epoch)
        elif table is _HOURLY:
            month_expr = _month_expr(session, epoch_column=table.bucket_epoch)
        else:
            month_expr = _month_expr(session, datetime_column=table.requested_at)
        columns.append(month_expr.label("month"))
    columns.extend(
        [
            table.request_count.label("requests"),
            table.input_tokens.label("input_tokens"),
            table.output_or_reasoning_tokens.label("output_tokens"),
            table.reasoning_tokens.label("reasoning_tokens"),
            literal(0).label("reasoning_known"),
            table.cached_input_tokens.label("cached_tokens"),
            table.cost_usd.label("cost_usd"),
            table.error_count.label("errors"),
            table.cancelled_count.label("cancelled"),
        ]
    )
    return columns


def _rollup_branch(
    session: AsyncSession,
    table,
    conditions: list[ColumnElement[bool]],
    *,
    month: bool,
) -> Select:
    """Rollup branch SELECT: the state row INNER-joined to the rollup with
    the branch's range conditions in the join — a missing state row empties
    the branch (the raw branches then cover the full window)."""
    columns: list = []
    if month:
        columns.append(
            _month_expr(
                session,
                epoch_column=table.day_epoch if table is _DAILY else table.bucket_epoch,
            ).label("month")
        )
    columns.extend(_measure_columns(session, table, month=False))
    columns.extend(
        [
            _unmap_dimension_expr(table.account_id).label("account_id"),
            _unmap_dimension_expr(table.model).label("model"),
        ]
    )
    return select(*columns).select_from(_STATE).join(table, and_(*conditions)).where(_STATE.id == _STATE_ROW_ID)


def _daily_branch(
    session: AsyncSession,
    since: datetime,
    until: datetime,
    *,
    account_ids: list[str] | None,
    model: str | None,
    api_key_ids: list[str] | None,
    month: bool,
) -> Select:
    """Whole UTC days below the (state-relative) daily watermark.

    ``until`` is bounded by BOTH the state's daily watermark and the
    window's last whole day, so an already-folded trailing partial day is
    served from the hourly/raw branches at hour precision instead of being
    over-counted as a whole day.
    """
    until_bound = _least_fn(session)(
        _watermark_epoch_expr(session, _STATE.daily_folded_through),
        literal(epoch_seconds(floor_to_grid(until, DAILY_BUCKET_SECONDS))),
    )
    conditions: list[ColumnElement[bool]] = [
        _DAILY.day_epoch >= epoch_seconds(ceil_to_grid(since, DAILY_BUCKET_SECONDS)),
        _DAILY.day_epoch < until_bound,
        _DAILY.request_kind.not_in(WARMUP_REQUEST_KINDS),
        *_rollup_dimension_filters(_DAILY, account_ids=account_ids, model=model, api_key_ids=api_key_ids),
    ]
    return _rollup_branch(session, _DAILY, conditions, month=month)


def _hourly_branch(
    session: AsyncSession,
    since: datetime,
    until: datetime,
    *,
    account_ids: list[str] | None,
    model: str | None,
    api_key_ids: list[str] | None,
    month: bool,
    whole_days_only: bool = False,
) -> Select:
    """Whole hours of the rolled region, optionally excluding the days the
    daily branch covers.

    The rolled region is ``[ceil_hour(since), min(hourly watermark,
    floor_hour(until)))`` (the upper bound state-relative); the daily
    segment inside it is ``[ceil_day(since), min(daily watermark,
    floor_day(until)))`` — excluded here so the two branches never overlap.
    """
    hourly_hi = _least_fn(session)(
        _watermark_epoch_expr(session, _STATE.hourly_folded_through),
        literal(epoch_seconds(floor_to_grid(until, HOURLY_BUCKET_SECONDS))),
    )
    conditions: list[ColumnElement[bool]] = [
        _HOURLY.bucket_epoch >= epoch_seconds(ceil_to_grid(since, HOURLY_BUCKET_SECONDS)),
        _HOURLY.bucket_epoch < hourly_hi,
    ]
    if whole_days_only:
        conditions.append(
            _HOURLY.bucket_epoch
            >= _least_fn(session)(
                _watermark_epoch_expr(session, _STATE.daily_folded_through),
                literal(epoch_seconds(floor_to_grid(until, DAILY_BUCKET_SECONDS))),
            )
        )
    else:
        conditions.append(
            or_(
                _HOURLY.bucket_epoch < epoch_seconds(ceil_to_grid(since, DAILY_BUCKET_SECONDS)),
                _HOURLY.bucket_epoch
                >= _least_fn(session)(
                    _watermark_epoch_expr(session, _STATE.daily_folded_through),
                    literal(epoch_seconds(floor_to_grid(until, DAILY_BUCKET_SECONDS))),
                ),
            )
        )
    conditions.extend(
        [
            _HOURLY.request_kind.not_in(WARMUP_REQUEST_KINDS),
            *_rollup_dimension_filters(_HOURLY, account_ids=account_ids, model=model, api_key_ids=api_key_ids),
        ]
    )
    return _rollup_branch(session, _HOURLY, conditions, month=month)


def _raw_tail_start_expr(session: AsyncSession, since: datetime, until: datetime) -> ColumnElement:
    """Where the raw tail after the rolled region starts, state-relative and
    NULL-watermark safe (a missing state row or epoch watermark degrades the
    tail to the first whole hour, so raw then covers the caller's full
    window) — the ``_conversation_tail_start`` pattern."""
    watermark = _STATE.hourly_folded_through
    lo_bound = literal(ceil_to_grid(since, HOURLY_BUCKET_SECONDS), type_=_RAW.requested_at.type)
    clamped = _least_fn(session)(
        watermark,
        literal(floor_to_grid(until, HOURLY_BUCKET_SECONDS), type_=_RAW.requested_at.type),
    )
    tail_start = (
        select(case((watermark.is_(None), lo_bound), else_=clamped)).where(_STATE.id == _STATE_ROW_ID).scalar_subquery()
    )
    return _greatest_fn(session)(lo_bound, func.coalesce(tail_start, lo_bound))


def _raw_branches(
    session: AsyncSession,
    since: datetime,
    until: datetime,
    *,
    account_ids: list[str] | None,
    model: str | None,
    useragent_group: str | None,
    api_key_ids: list[str] | None,
    month: bool,
) -> list[Select]:
    """The exact raw complement of the rolled region as two disjoint
    ``requested_at`` ranges: the sub-hour leading edge and the tail from the
    state-relative bound (uncorrelated scalar subquery, so the planner can
    range-scan ``requested_at`` instead of filtering every row)."""
    tail_start = _raw_tail_start_expr(session, since, until)
    shared: list[ColumnElement[bool]] = [
        _RAW.requested_at < until,
        *_raw_dimension_filters(
            account_ids=account_ids,
            model=model,
            useragent_group=useragent_group,
            api_key_ids=api_key_ids,
        ),
    ]
    reasoning_known = case((_RAW.reasoning_tokens.is_(None), 0), else_=1)
    columns: list = []
    if month:
        columns.append(_month_expr(session, datetime_column=_RAW.requested_at).label("month"))
    columns.extend(
        [
            literal(1).label("requests"),
            _RAW.input_tokens.label("input_tokens"),
            func.coalesce(_RAW.output_tokens, _RAW.reasoning_tokens, 0).label("output_tokens"),
            _RAW.reasoning_tokens.label("reasoning_tokens"),
            reasoning_known.label("reasoning_known"),
            _RAW.cached_input_tokens.label("cached_tokens"),
            _RAW.cost_usd.label("cost_usd"),
            case((_RAW.status.not_in(NON_ERROR_STATUSES), 1), else_=0).label("errors"),
            case((_RAW.status == CANCELLED_STATUS, 1), else_=0).label("cancelled"),
            _RAW.account_id.label("account_id"),
            _RAW.model.label("model"),
        ]
    )
    head = select(*columns).where(
        _RAW.requested_at >= since,
        _RAW.requested_at < ceil_to_grid(since, HOURLY_BUCKET_SECONDS),
        *shared,
    )
    tail = select(*columns).where(_RAW.requested_at >= tail_start, *shared)
    return [head, tail]


def history_window_union(
    session: AsyncSession,
    since: datetime,
    until: datetime,
    *,
    account_ids: list[str] | None = None,
    model: str | None = None,
    useragent_group: str | None = None,
    api_key_ids: list[str] | None = None,
    month: bool = False,
) -> CompoundSelect:
    """UNION ALL of pre-aggregated measure rows over ``[since, until)``:
    daily rollups for whole UTC days, hourly rollups for the remaining
    whole hours, raw for the exact complement (see the module docstring).

    ``month=True`` adds the UTC 'YYYY-MM' label column for the monthly
    grouping. Model-breakdown callers mirror the legacy
    ``model IS NOT NULL`` filter on the union's subquery (NULL models are
    already labelled NULL by the sentinel unmapping); measures the rollups
    do not hold must come from raw-only statements.
    """
    branches = [
        _daily_branch(
            session, since, until, month=month, account_ids=account_ids, model=model, api_key_ids=api_key_ids
        ),
        _hourly_branch(
            session, since, until, month=month, account_ids=account_ids, model=model, api_key_ids=api_key_ids
        ),
        *_raw_branches(
            session,
            since,
            until,
            account_ids=account_ids,
            model=model,
            useragent_group=useragent_group,
            api_key_ids=api_key_ids,
            month=month,
        ),
    ]
    return union_all(*branches)


def history_series_union(
    session: AsyncSession,
    since: datetime,
    until: datetime,
    *,
    offset_seconds: int,
    account_ids: list[str] | None = None,
    model: str | None = None,
    api_key_ids: list[str] | None = None,
) -> CompoundSelect:
    """UNION ALL of measure rows labelled by LOCAL day for the per-day
    series, grouped by the caller on the ``day_index`` column — the local
    date's own UTC-midnight day count (``floor((epoch + offset) / 86400)``
    puts each local midnight on a shifted-timeline day boundary), so
    ``date.fromtimestamp(day_index * 86400, tz=UTC).date()`` recovers the
    local date.

    With a zero UTC offset the local day IS the UTC day, so whole days
    below the daily watermark are served from the DAILY table (the only
    store guaranteed to outlive hourly retention) and the live tail from
    hourly/raw. Any other whole-hour offset cannot split a UTC-day rollup
    row across local-midnight boundaries, so those reads are served at
    hour grain (hourly + raw tail) and only span history retained by the
    hourly rollups — permanent unless hourly retention is enabled, in which
    case the service discloses the coverage. Offsets that are not whole
    hours (e.g. +5:30) put the local midnight inside a UTC hour; hour-start
    labelling then attributes that boundary hour's content to the earlier
    local day, so per-day rows are approximate at the two boundary hours
    per day while the series SUMS stay exact (the branches are disjoint
    and window-complete, and the window edges themselves are local
    midnights covered by the exact per-request raw branch).

    The offset must be CONSTANT across ``[since, until)``: a caller whose
    window spans a timezone-offset transition partitions the window at the
    transition instants and combines the correctly labelled per-segment
    unions (see ``ReportsRepository._rollup_daily_rows``). The
    summary/monthly reads are UTC-bucketed and need no partitioning.
    """
    rollup_kwargs = {
        "account_ids": account_ids,
        "model": model,
        "api_key_ids": api_key_ids,
    }

    def label_columns(table, is_raw: bool) -> list:
        if is_raw:
            epoch_expr = (
                cast(func.strftime("%s", table.requested_at), BigInteger)
                if session.get_bind().dialect.name != "postgresql"
                else cast(func.extract("epoch", table.requested_at), BigInteger)
            )
        else:
            epoch_expr = cast(table.day_epoch, BigInteger) if table is _DAILY else cast(table.bucket_epoch, BigInteger)
        shifted = _floor_epoch_expr(session, epoch_expr + offset_seconds, DAILY_BUCKET_SECONDS) / DAILY_BUCKET_SECONDS
        return [cast(shifted, Integer).label("day_index")]

    def branch_columns(table, is_raw: bool) -> Select:
        columns = [*label_columns(table, is_raw)]
        if is_raw:
            reasoning_known = case((table.reasoning_tokens.is_(None), 0), else_=1)
            columns.extend(
                [
                    literal(1).label("requests"),
                    table.input_tokens.label("input_tokens"),
                    func.coalesce(table.output_tokens, table.reasoning_tokens, 0).label("output_tokens"),
                    table.reasoning_tokens.label("reasoning_tokens"),
                    reasoning_known.label("reasoning_known"),
                    table.cached_input_tokens.label("cached_tokens"),
                    table.cost_usd.label("cost_usd"),
                    case((table.status.not_in(NON_ERROR_STATUSES), 1), else_=0).label("errors"),
                    case((table.status == CANCELLED_STATUS, 1), else_=0).label("cancelled"),
                    table.account_id.label("account_id"),
                ]
            )
        else:
            columns.extend(_measure_columns(session, table, month=False))
            columns.append(_unmap_dimension_expr(table.account_id).label("account_id"))
        return select(*columns)

    raw_filters = _raw_dimension_filters(
        account_ids=account_ids, model=model, useragent_group=None, api_key_ids=api_key_ids
    )
    branches: list[Select] = []
    hourly_hi = _least_fn(session)(
        _watermark_epoch_expr(session, _STATE.hourly_folded_through),
        literal(epoch_seconds(floor_to_grid(until, HOURLY_BUCKET_SECONDS))),
    )
    hourly_conditions: list[ColumnElement[bool]] = [
        _HOURLY.bucket_epoch >= epoch_seconds(ceil_to_grid(since, HOURLY_BUCKET_SECONDS)),
        _HOURLY.bucket_epoch < hourly_hi,
    ]
    if offset_seconds == 0:
        daily_hi = _least_fn(session)(
            _watermark_epoch_expr(session, _STATE.daily_folded_through),
            literal(epoch_seconds(floor_to_grid(until, DAILY_BUCKET_SECONDS))),
        )
        daily_conditions: list[ColumnElement[bool]] = [
            _DAILY.day_epoch >= epoch_seconds(ceil_to_grid(since, DAILY_BUCKET_SECONDS)),
            _DAILY.day_epoch < daily_hi,
            _DAILY.request_kind.not_in(WARMUP_REQUEST_KINDS),
            *_rollup_dimension_filters(_DAILY, **rollup_kwargs),
        ]
        daily_select = branch_columns(_DAILY, is_raw=False)
        branches.append(
            daily_select.select_from(_STATE).join(_DAILY, and_(*daily_conditions)).where(_STATE.id == _STATE_ROW_ID)
        )
        # Exact complement of the daily segment inside the rolled region —
        # the same or-condition as `_hourly_branch` (never splits a day
        # bucket: daily watermark is day-aligned, hourly hour-aligned).
        hourly_conditions.append(
            or_(
                _HOURLY.bucket_epoch < epoch_seconds(ceil_to_grid(since, DAILY_BUCKET_SECONDS)),
                _HOURLY.bucket_epoch >= daily_hi,
            )
        )
    hourly_conditions.extend(
        [
            _HOURLY.request_kind.not_in(WARMUP_REQUEST_KINDS),
            *_rollup_dimension_filters(_HOURLY, **rollup_kwargs),
        ]
    )
    hourly_select = branch_columns(_HOURLY, is_raw=False)
    branches.append(
        hourly_select.select_from(_STATE).join(_HOURLY, and_(*hourly_conditions)).where(_STATE.id == _STATE_ROW_ID)
    )

    tail_start = _raw_tail_start_expr(session, since, until)
    raw_shared: list[ColumnElement[bool]] = [_RAW.requested_at < until, *raw_filters]
    raw_select = branch_columns(_RAW, is_raw=True)
    branches.append(
        raw_select.where(
            _RAW.requested_at >= since,
            _RAW.requested_at < ceil_to_grid(since, HOURLY_BUCKET_SECONDS),
            *raw_shared,
        )
    )
    branches.append(raw_select.where(_RAW.requested_at >= tail_start, *raw_shared))
    return union_all(*branches)
