from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from itertools import batched
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, func, literal, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.retention.job import get_effective_retention
from app.core.usage.logs import CANCELLED_STATUS, NON_ERROR_STATUSES
from app.core.utils.time import utcnow
from app.db.models import Account, RequestLog
from app.modules.accounts.usage_time_rollup import conversation_id_expr
from app.modules.accounts.usage_time_rollup_read import (
    conversation_labeled_day_counts_stmt,
    conversation_labeled_presence_union,
    conversation_presence_union,
    earliest_daily_bucket_at,
    earliest_hourly_bucket_at,
)
from app.modules.reports import history

_INTERNAL_LIMIT_WARMUP_SOURCE = "limit_warmup"
_INTERNAL_WARMUP_REQUEST_KINDS = ("warmup", "limit_warmup")
_SQLITE_COMPOUND_SELECT_LIMIT = 500
# Generous enough for the All-time range (a decade of daily rows is a few
# thousand); the rollup-served day rows are grouped by day index in a single
# statement, and the raw-only per-day statements are chunked below.
MAX_DAILY_REPORT_DAYS = 3650
UNKNOWN_USERAGENT_GROUP = "Unknown"
MISSING_USERAGENT_GROUP = "Missing User-Agent"


class DailyReportRangeTooLargeError(ValueError):
    pass


@dataclass(frozen=True)
class DailyReportAggregateRow:
    date: str
    requests: int
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int | None
    cached_input_tokens: int
    cost_usd: float
    active_accounts: int
    error_count: int
    # Raw-only per-day measures: zeroed on rollup-served rows (pruned days)
    # and re-merged from the raw day rows by the caller.
    median_ttft_ms: float = 0.0
    median_tps: float = 0.0
    median_queue_ms: float = 0.0
    conversation_count: int = 0
    cancelled_count: int = 0


@dataclass(frozen=True)
class SummaryAggregateRow:
    total_cost_usd: float
    total_input_tokens: int
    total_output_tokens: int
    total_reasoning_tokens: int
    reasoning_usage_known_requests: int
    total_cached_tokens: int
    total_requests: int
    total_errors: int
    active_accounts: int
    conversation_count: int = 0
    total_cancelled: int = 0


@dataclass(frozen=True)
class ModelAggregateRow:
    model: str
    cost_usd: float
    request_count: int


@dataclass(frozen=True)
class AccountAggregateRow:
    account_id: str | None
    alias: str | None
    cost_usd: float
    request_count: int


@dataclass(frozen=True)
class UserAgentAggregateRow:
    useragent_group: str
    cost_usd: float
    request_count: int


@dataclass(frozen=True)
class MonthlyAggregateRow:
    """One (UTC month, model) group of the lifetime monthly view; model is
    None for rows the model split filters out but monthly totals include."""

    month: str
    model: str | None
    requests: int
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    cost_usd: float


class ReportsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _conversation_id_expr():
        return conversation_id_expr()

    async def aggregate_daily_rows(
        self,
        start_date: date,
        end_date: date,
        timezone_info: ZoneInfo | timezone,
        account_ids: list[str] | None = None,
        model: str | None = None,
        useragent_group: str | None = None,
        api_key_ids: list[str] | None = None,
    ) -> list[DailyReportAggregateRow]:
        window_days = (end_date - start_date).days + 1
        if window_days > MAX_DAILY_REPORT_DAYS:
            raise DailyReportRangeTooLargeError(f"report date range must be {MAX_DAILY_REPORT_DAYS} days or less")
        day_ranges = list(_daily_bucket_ranges(start_date, end_date, timezone_info))
        if not day_ranges:
            return []

        # Same filtered-vs-unfiltered split as `aggregate_summary`: only the
        # unfiltered per-day conversation counts are served from the
        # conversation satellite (one extra statement per batch, replacing
        # the raw COUNT(DISTINCT ...) column in the main statement).
        use_satellite = not (account_ids or model or useragent_group or api_key_ids)
        raw_floor = await _raw_retention_floor()
        # Rollup-served per-day rows are only needed where raw retention cuts
        # into the window (they fill the pruned days); a user-agent filter
        # pins the whole read to raw (not a rollup dimension). The union is
        # bounded to the pruned PREFIX (contiguous days starting before the
        # floor) so rollup-served day rows never extend over a raw-served
        # neighbour day: hour-grain local-day labelling shifts boundary-hour
        # content between adjacent rows, and a rollup row reaching into a
        # raw-served day would double-count that day's boundary content.
        rollup_days: dict[str, DailyReportAggregateRow] = {}
        if raw_floor is not None and not useragent_group:
            pruned_ranges = [day_range for day_range in day_ranges if day_range[1] < raw_floor]
            if pruned_ranges:
                rollup_days = await self._rollup_daily_rows(
                    pruned_ranges, timezone_info, account_ids, model, api_key_ids
                )
        rows: list[DailyReportAggregateRow] = []
        # SQLite caps compound SELECTs at 500 terms, so long report ranges are
        # executed in chunks instead of building a single oversized UNION ALL.
        for day_ranges_batch in batched(day_ranges, _SQLITE_COMPOUND_SELECT_LIMIT):
            day_ranges_list = list(day_ranges_batch)
            speed_result = await self._session.execute(
                _daily_speed_medians_stmt(day_ranges_list, account_ids, model, useragent_group, api_key_ids)
            )
            speed_values = {
                speed_row.report_date: (
                    float(speed_row.median_ttft_ms or 0.0),
                    float(speed_row.median_tps or 0.0),
                    float(speed_row.median_queue_ms or 0.0),
                )
                for speed_row in speed_result.all()
            }
            conversation_values: dict[str, int] = {}
            if use_satellite:
                # Same offset the rollup/history unions label their local
                # days with (see _rollup_daily_rows), so both label spaces
                # agree on which date a window maps to.
                first_date = date.fromisoformat(day_ranges_list[0][0])
                offset_seconds = int(
                    (
                        timezone_info.utcoffset(datetime.combine(first_date, datetime.min.time())) or timedelta(0)
                    ).total_seconds()
                )
                day_counts_stmt = conversation_labeled_day_counts_stmt(
                    self._session,
                    day_ranges_list,
                    offset_seconds=offset_seconds,
                    raw_conditions=(_normal_traffic_clause(),),
                )
                if day_counts_stmt is not None:
                    # Flat fast path for the per-day series shape (contiguous
                    # exact-24h hour-grid-aligned windows under a whole-hour
                    # offset): one grouped scan instead of a per-window
                    # compound union, whose literal windows CTE dominates
                    # long All-time reads (measured 8.8s vs 0.3s at 401
                    # windows on SQLite).
                    day_counts = await self._session.execute(day_counts_stmt)
                    conversation_values = {
                        datetime.fromtimestamp(int(day_index) * 86400, tz=timezone.utc).date().isoformat(): int(count)
                        for day_index, count in day_counts.all()
                    }
                else:
                    conv_union = conversation_labeled_presence_union(
                        self._session,
                        day_ranges_list,
                        raw_conditions=(_normal_traffic_clause(),),
                    ).subquery()
                    conversation_result = await self._session.execute(
                        select(conv_union.c.label, func.count(func.distinct(conv_union.c.cid))).group_by(
                            conv_union.c.label
                        )
                    )
                    conversation_values = {label: int(count) for label, count in conversation_result.all()}

            raw_values = {
                row.report_date: row
                for row in (
                    await self._session.execute(
                        _daily_rows_stmt(
                            day_ranges_list,
                            account_ids,
                            model,
                            useragent_group,
                            api_key_ids,
                            include_conversations=not use_satellite,
                        )
                    )
                ).all()
            }
            for report_date, day_start, _day_end in day_ranges_list:
                # Fill-the-gaps merge: raw day rows are exact (local-day
                # buckets, medians, filtered conversation counts) wherever raw
                # still holds the whole day; only days raw retention has cut
                # into (day starts before the raw floor) fall back to the
                # rollup-served union row, which is complete for the whole
                # day (rolled segments from daily/hourly rollups, the live
                # tail from raw — see app/modules/reports/history.py). With
                # retention disabled `rollup_days` is empty and every day is
                # the exact legacy raw row.
                rollup_row = rollup_days.get(report_date) if raw_floor is not None and day_start < raw_floor else None
                row = rollup_row if rollup_row is not None else raw_values.get(report_date)
                if row is None:
                    continue
                speed_defaults = speed_values.get(report_date, (0.0, 0.0, 0.0))
                rows.append(
                    DailyReportAggregateRow(
                        date=report_date,
                        requests=int(row.requests or 0),
                        input_tokens=int(row.input_tokens or 0),
                        output_tokens=int(row.output_tokens or 0),
                        reasoning_tokens=int(row.reasoning_tokens) if row.reasoning_tokens is not None else None,
                        cached_input_tokens=int(row.cached_input_tokens or 0),
                        cost_usd=float(row.cost_usd or 0.0),
                        active_accounts=int(row.active_accounts or 0),
                        error_count=int(row.error_count or 0),
                        cancelled_count=int(row.cancelled_count or 0),
                        median_ttft_ms=speed_defaults[0],
                        median_tps=speed_defaults[1],
                        median_queue_ms=speed_defaults[2],
                        conversation_count=(
                            conversation_values.get(report_date, 0)
                            if use_satellite
                            else int(row.conversation_count or 0)
                        ),
                    )
                )
        return rows

    async def _rollup_daily_rows(
        self,
        day_ranges: list[tuple[str, datetime, datetime]],
        timezone_info: ZoneInfo | timezone,
        account_ids: list[str] | None,
        model: str | None,
        api_key_ids: list[str] | None,
    ) -> dict[str, DailyReportAggregateRow]:
        """Per-local-day measures served from the rollup/history union
        (one SQL statement over the whole window; rows grouped by local-day
        index entirely in SQL). Raw-only per-day measures (speed medians,
        filtered conversation counts) are absent here — the caller merges
        them from the raw day rows or leaves them zeroed for pruned days."""
        first_date_iso, window_start, window_end = day_ranges[0][0], day_ranges[0][1], day_ranges[-1][2]
        first_date = date.fromisoformat(first_date_iso)
        offset_seconds = int(
            (timezone_info.utcoffset(datetime.combine(first_date, datetime.min.time())) or timedelta(0)).total_seconds()
        )
        union = history.history_series_union(
            self._session,
            window_start,
            window_end,
            offset_seconds=offset_seconds,
            account_ids=account_ids,
            model=model,
            api_key_ids=api_key_ids,
        ).subquery()
        result = await self._session.execute(
            select(
                union.c.day_index,
                func.coalesce(func.sum(union.c.requests), 0).label("requests"),
                func.coalesce(func.sum(union.c.input_tokens), 0).label("input_tokens"),
                func.coalesce(func.sum(union.c.output_tokens), 0).label("output_tokens"),
                func.coalesce(func.sum(union.c.reasoning_tokens), 0).label("reasoning_tokens"),
                func.coalesce(func.sum(union.c.cached_tokens), 0).label("cached_tokens"),
                func.coalesce(func.sum(union.c.cost_usd), 0.0).label("cost_usd"),
                func.coalesce(func.sum(union.c.errors), 0).label("errors"),
                func.coalesce(func.sum(union.c.cancelled), 0).label("cancelled"),
                func.count(func.distinct(union.c.account_id)).label("active_accounts"),
            ).group_by(union.c.day_index)
        )
        rows: dict[str, DailyReportAggregateRow] = {}
        for row in result.all():
            # day_index is the local date's own UTC-midnight day count
            # (floor((epoch + offset) / 86400) — see history_series_union),
            # so the local date is the UTC date of day_index * 86400.
            local_date = datetime.fromtimestamp(int(row.day_index) * 86400, tz=timezone.utc).date()
            rows[local_date.isoformat()] = DailyReportAggregateRow(
                date=local_date.isoformat(),
                requests=int(row.requests or 0),
                input_tokens=int(row.input_tokens or 0),
                output_tokens=int(row.output_tokens or 0),
                reasoning_tokens=int(row.reasoning_tokens or 0),
                cached_input_tokens=int(row.cached_tokens or 0),
                cost_usd=float(row.cost_usd or 0.0),
                active_accounts=int(row.active_accounts or 0),
                error_count=int(row.errors or 0),
                cancelled_count=int(row.cancelled or 0),
            )
        return rows

    async def aggregate_summary(
        self,
        start_date: datetime,
        end_date: datetime,
        account_ids: list[str] | None = None,
        model: str | None = None,
        useragent_group: str | None = None,
        api_key_ids: list[str] | None = None,
    ) -> SummaryAggregateRow:
        conditions = _report_conditions(start_date, end_date, account_ids, model, useragent_group, api_key_ids)

        # The conversation satellite carries no model/useragent dimensions
        # and pre-merges accounts, so only the unfiltered read is served from
        # it (rollup + raw tail, split out of the single statement the same
        # way the dashboard activity read splits its conversation metrics);
        # filtered summaries keep the legacy raw count for conversations.
        use_satellite = not (account_ids or model or useragent_group or api_key_ids)

        if useragent_group:
            # The user-agent group is a raw-only dimension: a UA-filtered
            # summary keeps the exact legacy raw single statement (its
            # coverage is disclosed to the client via raw_metrics_since).
            columns = [
                func.coalesce(func.sum(RequestLog.cost_usd), 0.0).label("total_cost_usd"),
                func.coalesce(func.sum(RequestLog.input_tokens), 0).label("total_input_tokens"),
                func.coalesce(
                    func.sum(func.coalesce(RequestLog.output_tokens, RequestLog.reasoning_tokens, 0)),
                    0,
                ).label("total_output_tokens"),
                func.coalesce(func.sum(RequestLog.reasoning_tokens), 0).label("total_reasoning_tokens"),
                func.count(RequestLog.reasoning_tokens).label("reasoning_usage_known_requests"),
                func.coalesce(func.sum(RequestLog.cached_input_tokens), 0).label("total_cached_tokens"),
                func.count().label("total_requests"),
                func.coalesce(
                    func.sum(case((RequestLog.status.not_in(NON_ERROR_STATUSES), 1), else_=0)),
                    0,
                ).label("total_errors"),
                func.coalesce(
                    func.sum(case((RequestLog.status == CANCELLED_STATUS, 1), else_=0)),
                    0,
                ).label("total_cancelled"),
                func.count(func.distinct(RequestLog.account_id)).label("active_accounts"),
                func.count(func.distinct(self._conversation_id_expr())).label("conversation_count"),
            ]
            row = (await self._session.execute(select(*columns).where(and_(*conditions)))).one()
            conversation_count = row.conversation_count
        else:
            # History-served summary: the union splits the window into daily
            # rollups / hourly rollups / raw tail (exact, disjoint — see
            # app/modules/reports/history.py) and aggregates it in SQL; the
            # reasoning-known count is a per-RAW-row predicate the rollups do
            # not hold, so it keeps a legacy raw count over the window (its
            # coverage beyond raw retention is disclosed via raw_metrics_since).
            union = history.history_window_union(
                self._session,
                start_date,
                end_date,
                account_ids=account_ids,
                model=model,
                api_key_ids=api_key_ids,
            ).subquery()
            row = (
                await self._session.execute(
                    select(
                        func.coalesce(func.sum(union.c.cost_usd), 0.0).label("total_cost_usd"),
                        func.coalesce(func.sum(union.c.input_tokens), 0).label("total_input_tokens"),
                        func.coalesce(func.sum(union.c.output_tokens), 0).label("total_output_tokens"),
                        func.coalesce(func.sum(union.c.reasoning_tokens), 0).label("total_reasoning_tokens"),
                        func.coalesce(func.sum(union.c.reasoning_known), 0).label("reasoning_known_rollup"),
                        func.coalesce(func.sum(union.c.cached_tokens), 0).label("total_cached_tokens"),
                        func.coalesce(func.sum(union.c.requests), 0).label("total_requests"),
                        func.coalesce(func.sum(union.c.errors), 0).label("total_errors"),
                        func.coalesce(func.sum(union.c.cancelled), 0).label("total_cancelled"),
                        func.count(func.distinct(union.c.account_id)).label("active_accounts"),
                    )
                )
            ).one()
            reasoning_known_count = (
                await self._session.execute(select(func.count(RequestLog.reasoning_tokens)).where(and_(*conditions)))
            ).scalar_one()
            conversation_count = 0
            if use_satellite:
                conv_union = conversation_presence_union(
                    self._session,
                    start_date,
                    end_date,
                    include_deleted=True,
                    raw_conditions=(_normal_traffic_clause(),),
                ).subquery()
                conversation_count = (
                    await self._session.execute(select(func.count(func.distinct(conv_union.c.cid))))
                ).scalar_one()
            else:
                conversation_count = (
                    await self._session.execute(
                        select(func.count(func.distinct(self._conversation_id_expr()))).where(and_(*conditions))
                    )
                ).scalar_one()
            return SummaryAggregateRow(
                total_cost_usd=float(row.total_cost_usd),
                total_input_tokens=int(row.total_input_tokens),
                total_output_tokens=int(row.total_output_tokens),
                total_reasoning_tokens=int(row.total_reasoning_tokens),
                reasoning_usage_known_requests=int(reasoning_known_count or 0),
                total_cached_tokens=int(row.total_cached_tokens),
                total_requests=int(row.total_requests),
                total_errors=int(row.total_errors),
                active_accounts=int(row.active_accounts),
                conversation_count=int(conversation_count or 0),
                total_cancelled=int(row.total_cancelled),
            )
        return SummaryAggregateRow(
            total_cost_usd=float(row.total_cost_usd),
            total_input_tokens=int(row.total_input_tokens),
            total_output_tokens=int(row.total_output_tokens),
            total_reasoning_tokens=int(row.total_reasoning_tokens),
            reasoning_usage_known_requests=int(row.reasoning_usage_known_requests),
            total_cached_tokens=int(row.total_cached_tokens),
            total_requests=int(row.total_requests),
            total_errors=int(row.total_errors),
            active_accounts=int(row.active_accounts),
            conversation_count=int(conversation_count or 0),
            total_cancelled=int(row.total_cancelled),
        )

    async def aggregate_by_model(
        self,
        start_date: datetime,
        end_date: datetime,
        account_ids: list[str] | None = None,
        model: str | None = None,
        useragent_group: str | None = None,
        api_key_ids: list[str] | None = None,
    ) -> list[ModelAggregateRow]:
        if not useragent_group:
            # History-served model breakdown: the union covers the window
            # exactly (daily/hourly rollups + raw tail); NULL models are
            # filtered on the union subquery, mirroring the legacy
            # `model IS NOT NULL` condition.
            union = history.history_window_union(
                self._session,
                start_date,
                end_date,
                account_ids=account_ids,
                model=model,
                api_key_ids=api_key_ids,
            ).subquery()
            stmt = (
                select(
                    union.c.model,
                    func.coalesce(func.sum(union.c.cost_usd), 0.0).label("cost_usd"),
                    func.coalesce(func.sum(union.c.requests), 0).label("request_count"),
                )
                .where(union.c.model.is_not(None))
                .group_by(union.c.model)
                .order_by(func.coalesce(func.sum(union.c.cost_usd), 0.0).desc())
            )
            result = await self._session.execute(stmt)
            return [
                ModelAggregateRow(
                    model=row.model,
                    cost_usd=float(row.cost_usd),
                    request_count=int(row.request_count),
                )
                for row in result.all()
            ]

        conditions = [
            *_report_conditions(start_date, end_date, account_ids, model, useragent_group, api_key_ids),
            RequestLog.model.is_not(None),
        ]

        stmt = (
            select(
                RequestLog.model,
                func.coalesce(func.sum(RequestLog.cost_usd), 0.0).label("cost_usd"),
                func.count().label("request_count"),
            )
            .where(and_(*conditions))
            .group_by(RequestLog.model)
            .order_by(func.coalesce(func.sum(RequestLog.cost_usd), 0.0).desc())
        )
        result = await self._session.execute(stmt)
        return [
            ModelAggregateRow(
                model=row.model,
                cost_usd=float(row.cost_usd),
                request_count=int(row.request_count),
            )
            for row in result.all()
        ]

    async def aggregate_by_account(
        self,
        start_date: datetime,
        end_date: datetime,
        account_ids: list[str] | None = None,
        model: str | None = None,
        useragent_group: str | None = None,
        api_key_ids: list[str] | None = None,
    ) -> list[AccountAggregateRow]:
        if not useragent_group:
            # History-served account breakdown (same union as by-model; NULL
            # accounts are a legitimate group and stay included).
            union = history.history_window_union(
                self._session,
                start_date,
                end_date,
                account_ids=account_ids,
                model=model,
                api_key_ids=api_key_ids,
            ).subquery()
            stmt = (
                select(
                    union.c.account_id,
                    func.coalesce(func.sum(union.c.cost_usd), 0.0).label("cost_usd"),
                    func.coalesce(func.sum(union.c.requests), 0).label("request_count"),
                )
                .group_by(union.c.account_id)
                .order_by(func.coalesce(func.sum(union.c.cost_usd), 0.0).desc())
            )
            result = await self._session.execute(stmt)
            rows = result.all()
        else:
            conditions = _report_conditions(start_date, end_date, account_ids, model, useragent_group, api_key_ids)

            stmt = (
                select(
                    RequestLog.account_id,
                    func.coalesce(func.sum(RequestLog.cost_usd), 0.0).label("cost_usd"),
                    func.count().label("request_count"),
                )
                .where(and_(*conditions))
                .group_by(RequestLog.account_id)
                .order_by(func.coalesce(func.sum(RequestLog.cost_usd), 0.0).desc())
            )
            result = await self._session.execute(stmt)
            rows = result.all()

        account_ids_found = [row.account_id for row in rows if row.account_id]
        alias_map: dict[str | None, str | None] = {}
        if account_ids_found:
            alias_result = await self._session.execute(
                select(Account.id, Account.alias).where(Account.id.in_(account_ids_found))
            )
            alias_map = {account_id: alias for account_id, alias in alias_result.all()}

        return [
            AccountAggregateRow(
                account_id=row.account_id,
                alias=alias_map.get(row.account_id),
                cost_usd=float(row.cost_usd),
                request_count=int(row.request_count),
            )
            for row in rows
        ]

    async def aggregate_monthly(
        self,
        start_date: datetime,
        end_date: datetime,
        account_ids: list[str] | None = None,
        model: str | None = None,
        useragent_group: str | None = None,
        api_key_ids: list[str] | None = None,
    ) -> list[MonthlyAggregateRow]:
        """Per-UTC-month x model measures over the window (the lifetime
        monthly view), history-served from the daily rollups like the other
        breakdowns. Rows with ``model=None`` are kept so monthly totals can
        include NULL-model cost; the model split filters them out. A
        user-agent filter (raw-only dimension) keeps the legacy raw path."""
        if useragent_group:
            month_bucket = history.month_label_expr(self._session, datetime_column=RequestLog.requested_at)
            conditions = _report_conditions(start_date, end_date, account_ids, model, useragent_group, api_key_ids)
            stmt = (
                select(
                    month_bucket.label("month"),
                    RequestLog.model,
                    func.count().label("requests"),
                    func.coalesce(func.sum(RequestLog.input_tokens), 0).label("input_tokens"),
                    func.coalesce(
                        func.sum(func.coalesce(RequestLog.output_tokens, RequestLog.reasoning_tokens, 0)),
                        0,
                    ).label("output_tokens"),
                    func.coalesce(func.sum(RequestLog.cached_input_tokens), 0).label("cached_tokens"),
                    func.coalesce(func.sum(RequestLog.cost_usd), 0.0).label("cost_usd"),
                )
                .where(and_(*conditions))
                .group_by(month_bucket, RequestLog.model)
                .order_by(month_bucket.asc(), func.coalesce(func.sum(RequestLog.cost_usd), 0.0).desc())
            )
            result = await self._session.execute(stmt)
            return [
                MonthlyAggregateRow(
                    month=row.month,
                    model=row.model,
                    requests=int(row.requests or 0),
                    input_tokens=int(row.input_tokens or 0),
                    output_tokens=int(row.output_tokens or 0),
                    cached_input_tokens=int(row.cached_tokens or 0),
                    cost_usd=float(row.cost_usd or 0.0),
                )
                for row in result.all()
            ]

        union = history.history_window_union(
            self._session,
            start_date,
            end_date,
            account_ids=account_ids,
            model=model,
            api_key_ids=api_key_ids,
            month=True,
        ).subquery()
        stmt = (
            select(
                union.c.month,
                union.c.model,
                func.coalesce(func.sum(union.c.requests), 0).label("requests"),
                func.coalesce(func.sum(union.c.input_tokens), 0).label("input_tokens"),
                func.coalesce(func.sum(union.c.output_tokens), 0).label("output_tokens"),
                func.coalesce(func.sum(union.c.cached_tokens), 0).label("cached_tokens"),
                func.coalesce(func.sum(union.c.cost_usd), 0.0).label("cost_usd"),
            )
            .group_by(union.c.month, union.c.model)
            .order_by(union.c.month.asc(), func.coalesce(func.sum(union.c.cost_usd), 0.0).desc())
        )
        result = await self._session.execute(stmt)
        return [
            MonthlyAggregateRow(
                month=row.month,
                model=row.model,
                requests=int(row.requests or 0),
                input_tokens=int(row.input_tokens or 0),
                output_tokens=int(row.output_tokens or 0),
                cached_input_tokens=int(row.cached_tokens or 0),
                cost_usd=float(row.cost_usd or 0.0),
            )
            for row in result.all()
        ]

    async def aggregate_by_useragent(
        self,
        start_date: datetime,
        end_date: datetime,
        account_ids: list[str] | None = None,
        model: str | None = None,
        useragent_group: str | None = None,
        api_key_ids: list[str] | None = None,
    ) -> list[UserAgentAggregateRow]:
        useragent_group_bucket = _useragent_group_bucket_expr()
        conditions = [
            *_report_conditions(start_date, end_date, account_ids, model, useragent_group, api_key_ids),
            or_(RequestLog.useragent_group.is_(None), func.trim(RequestLog.useragent_group) != ""),
        ]

        stmt = (
            select(
                useragent_group_bucket.label("useragent_group"),
                func.coalesce(func.sum(RequestLog.cost_usd), 0.0).label("cost_usd"),
                func.count().label("request_count"),
            )
            .where(and_(*conditions))
            .group_by(useragent_group_bucket)
            .order_by(func.coalesce(func.sum(RequestLog.cost_usd), 0.0).desc())
        )
        result = await self._session.execute(stmt)
        return [
            UserAgentAggregateRow(
                useragent_group=row.useragent_group,
                cost_usd=float(row.cost_usd),
                request_count=int(row.request_count),
            )
            for row in result.all()
        ]

    async def count_active_accounts(
        self,
        start_date: datetime,
        end_date: datetime,
        account_ids: list[str] | None = None,
        model: str | None = None,
        useragent_group: str | None = None,
        api_key_ids: list[str] | None = None,
    ) -> int:
        conditions = [
            *_report_conditions(start_date, end_date, account_ids, model, useragent_group, api_key_ids),
            RequestLog.account_id.is_not(None),
        ]

        result = await self._session.execute(
            select(func.count(func.distinct(RequestLog.account_id))).where(and_(*conditions))
        )
        return int(result.scalar_one() or 0)

    async def earliest_report_activity_at(
        self,
        account_ids: list[str] | None = None,
        model: str | None = None,
        useragent_group: str | None = None,
        api_key_ids: list[str] | None = None,
    ) -> datetime | None:
        conditions = [_normal_traffic_clause()]
        if account_ids:
            conditions.append(RequestLog.account_id.in_(account_ids))
        if model:
            conditions.append(RequestLog.model == model)
        useragent_group_clause = _useragent_group_filter_clause(useragent_group)
        if useragent_group_clause is not None:
            conditions.append(useragent_group_clause)
        if api_key_ids:
            conditions.append(RequestLog.api_key_id.in_(api_key_ids))

        result = await self._session.execute(select(func.min(RequestLog.requested_at)).where(and_(*conditions)))
        value = result.scalar_one_or_none()
        earliest = value if isinstance(value, datetime) else None
        if useragent_group or account_ids or model or api_key_ids:
            # Filtered reads keep exact raw semantics (the rollup fallbacks
            # cannot express the filters); the unfiltered earliest — the
            # All-time range origin — may fall back to the permanent
            # rollups at day/hour precision once raw is pruned.
            return earliest
        for rollup_earliest in (
            await earliest_daily_bucket_at(self._session),
            await earliest_hourly_bucket_at(self._session),
        ):
            if rollup_earliest is not None and (earliest is None or rollup_earliest < earliest):
                earliest = rollup_earliest
        return earliest


async def _raw_retention_floor() -> datetime | None:
    """Oldest ``requested_at`` raw retention still guarantees (None when
    retention is disabled — raw then covers everything it ever held). Rows
    below the floor are pruned (or will be at the next retention pass); the
    daily/hourly rollups are the only store covering them."""
    retention_days = (await get_effective_retention()).request_log_days
    if not retention_days:
        return None
    return utcnow() - timedelta(days=retention_days)


def _report_conditions(
    start_date: datetime,
    end_date: datetime,
    account_ids: list[str] | None,
    model: str | None,
    useragent_group: str | None,
    api_key_ids: list[str] | None = None,
) -> list:
    conditions = [
        RequestLog.requested_at >= start_date,
        RequestLog.requested_at < end_date,
        _normal_traffic_clause(),
    ]
    if account_ids:
        conditions.append(RequestLog.account_id.in_(account_ids))
    if model:
        conditions.append(RequestLog.model == model)
    useragent_group_clause = _useragent_group_filter_clause(useragent_group)
    if useragent_group_clause is not None:
        conditions.append(useragent_group_clause)
    if api_key_ids:
        conditions.append(RequestLog.api_key_id.in_(api_key_ids))
    return conditions


def _useragent_group_bucket_expr():
    return case(
        (RequestLog.useragent_group.is_(None), literal(MISSING_USERAGENT_GROUP)),
        else_=RequestLog.useragent_group,
    )


def _useragent_group_filter_clause(useragent_group: str | None):
    if not useragent_group:
        return None
    if useragent_group == MISSING_USERAGENT_GROUP:
        return RequestLog.useragent_group.is_(None)
    return RequestLog.useragent_group == useragent_group


def _normal_traffic_clause():
    return and_(
        or_(RequestLog.source.is_(None), RequestLog.source != _INTERNAL_LIMIT_WARMUP_SOURCE),
        or_(
            RequestLog.request_kind.is_(None),
            RequestLog.request_kind.not_in(_INTERNAL_WARMUP_REQUEST_KINDS),
        ),
    )


def _day_ranges_cte(day_ranges: list[tuple[str, datetime, datetime]]):
    day_range_rows = [
        select(
            literal(report_date).label("report_date"),
            literal(day_start).label("day_start"),
            literal(day_end).label("day_end"),
        )
        for report_date, day_start, day_end in day_ranges
    ]
    day_ranges_query = day_range_rows[0] if len(day_range_rows) == 1 else union_all(*day_range_rows)
    return day_ranges_query.cte("report_days")


def _daily_speed_medians_stmt(
    day_ranges: list[tuple[str, datetime, datetime]],
    account_ids: list[str] | None,
    model: str | None,
    useragent_group: str | None,
    api_key_ids: list[str] | None = None,
):
    useragent_group_clause = _useragent_group_filter_clause(useragent_group)
    day_ranges_cte = _day_ranges_cte(day_ranges)
    traffic_join = day_ranges_cte.join(
        RequestLog,
        and_(
            RequestLog.requested_at >= day_ranges_cte.c.day_start,
            RequestLog.requested_at < day_ranges_cte.c.day_end,
            _normal_traffic_clause(),
            *([RequestLog.account_id.in_(account_ids)] if account_ids else []),
            *([RequestLog.model == model] if model else []),
            *([useragent_group_clause] if useragent_group_clause is not None else []),
            *([RequestLog.api_key_id.in_(api_key_ids)] if api_key_ids else []),
        ),
    )
    token_count = RequestLog.output_tokens - func.coalesce(RequestLog.reasoning_tokens, 0)
    ttft_values_cte = (
        select(
            day_ranges_cte.c.report_date,
            RequestLog.latency_first_token_ms.label("ttft_ms"),
        )
        .select_from(traffic_join)
        .where(RequestLog.latency_first_token_ms.is_not(None))
        .cte("daily_ttft_values")
    )
    tps_values_cte = (
        select(
            day_ranges_cte.c.report_date,
            (token_count * 1000.0 / (RequestLog.latency_ms - RequestLog.latency_first_token_ms)).label("tps"),
        )
        .select_from(traffic_join)
        .where(
            token_count.is_not(None),
            token_count > 0,
            RequestLog.latency_ms.is_not(None),
            RequestLog.latency_first_token_ms.is_not(None),
            RequestLog.latency_ms > RequestLog.latency_first_token_ms,
        )
        .cte("daily_tps_values")
    )
    queue_values_cte = (
        select(
            day_ranges_cte.c.report_date,
            RequestLog.latency_queue_ms.label("queue_ms"),
        )
        .select_from(traffic_join)
        .where(RequestLog.latency_queue_ms.is_not(None))
        .cte("daily_queue_values")
    )
    ttft_count = func.count().over(partition_by=ttft_values_cte.c.report_date)
    ttft_ranked_cte = select(
        ttft_values_cte.c.report_date,
        ttft_values_cte.c.ttft_ms,
        ttft_count.label("sample_count"),
        func.row_number()
        .over(partition_by=ttft_values_cte.c.report_date, order_by=ttft_values_cte.c.ttft_ms)
        .label("ttft_rank"),
    ).cte("daily_ttft_ranks")
    tps_count = func.count().over(partition_by=tps_values_cte.c.report_date)
    tps_ranked_cte = select(
        tps_values_cte.c.report_date,
        tps_values_cte.c.tps,
        tps_count.label("sample_count"),
        func.row_number()
        .over(partition_by=tps_values_cte.c.report_date, order_by=tps_values_cte.c.tps)
        .label("tps_rank"),
    ).cte("daily_tps_ranks")
    queue_count = func.count().over(partition_by=queue_values_cte.c.report_date)
    queue_ranked_cte = select(
        queue_values_cte.c.report_date,
        queue_values_cte.c.queue_ms,
        queue_count.label("sample_count"),
        func.row_number()
        .over(partition_by=queue_values_cte.c.report_date, order_by=queue_values_cte.c.queue_ms)
        .label("queue_rank"),
    ).cte("daily_queue_ranks")

    # A median contains the one center row for odd samples and both center rows
    # for even samples. Multiplication avoids dialect-specific integer division.
    ttft_is_middle = and_(
        ttft_ranked_cte.c.ttft_rank * 2 >= ttft_ranked_cte.c.sample_count,
        ttft_ranked_cte.c.ttft_rank * 2 <= ttft_ranked_cte.c.sample_count + 2,
    )
    tps_is_middle = and_(
        tps_ranked_cte.c.tps_rank * 2 >= tps_ranked_cte.c.sample_count,
        tps_ranked_cte.c.tps_rank * 2 <= tps_ranked_cte.c.sample_count + 2,
    )
    queue_is_middle = and_(
        queue_ranked_cte.c.queue_rank * 2 >= queue_ranked_cte.c.sample_count,
        queue_ranked_cte.c.queue_rank * 2 <= queue_ranked_cte.c.sample_count + 2,
    )
    ttft_medians_cte = (
        select(
            ttft_ranked_cte.c.report_date,
            func.avg(case((ttft_is_middle, ttft_ranked_cte.c.ttft_ms), else_=None)).label("median_ttft_ms"),
        )
        .group_by(ttft_ranked_cte.c.report_date)
        .cte("daily_ttft_medians")
    )
    tps_medians_cte = (
        select(
            tps_ranked_cte.c.report_date,
            func.avg(case((tps_is_middle, tps_ranked_cte.c.tps), else_=None)).label("median_tps"),
        )
        .group_by(tps_ranked_cte.c.report_date)
        .cte("daily_tps_medians")
    )
    queue_medians_cte = (
        select(
            queue_ranked_cte.c.report_date,
            func.avg(case((queue_is_middle, queue_ranked_cte.c.queue_ms), else_=None)).label("median_queue_ms"),
        )
        .group_by(queue_ranked_cte.c.report_date)
        .cte("daily_queue_medians")
    )
    return (
        select(
            day_ranges_cte.c.report_date,
            func.coalesce(ttft_medians_cte.c.median_ttft_ms, 0.0).label("median_ttft_ms"),
            func.coalesce(tps_medians_cte.c.median_tps, 0.0).label("median_tps"),
            func.coalesce(queue_medians_cte.c.median_queue_ms, 0.0).label("median_queue_ms"),
        )
        .select_from(
            day_ranges_cte.outerjoin(
                ttft_medians_cte,
                ttft_medians_cte.c.report_date == day_ranges_cte.c.report_date,
            )
            .outerjoin(
                tps_medians_cte,
                tps_medians_cte.c.report_date == day_ranges_cte.c.report_date,
            )
            .outerjoin(
                queue_medians_cte,
                queue_medians_cte.c.report_date == day_ranges_cte.c.report_date,
            )
        )
        .order_by(day_ranges_cte.c.report_date)
    )


def _daily_rows_stmt(
    day_ranges: list[tuple[str, datetime, datetime]],
    account_ids: list[str] | None,
    model: str | None,
    useragent_group: str | None,
    api_key_ids: list[str] | None = None,
    *,
    include_conversations: bool = True,
):
    useragent_group_clause = _useragent_group_filter_clause(useragent_group)
    day_ranges_cte = _day_ranges_cte(day_ranges)
    columns = [
        day_ranges_cte.c.report_date,
        func.count(RequestLog.id).label("requests"),
        func.coalesce(func.sum(RequestLog.input_tokens), 0).label("input_tokens"),
        func.coalesce(
            func.sum(func.coalesce(RequestLog.output_tokens, RequestLog.reasoning_tokens, 0)),
            0,
        ).label("output_tokens"),
        func.sum(RequestLog.reasoning_tokens).label("reasoning_tokens"),
        func.coalesce(func.sum(RequestLog.cached_input_tokens), 0).label("cached_input_tokens"),
        func.coalesce(func.sum(RequestLog.cost_usd), 0.0).label("cost_usd"),
        func.count(func.distinct(RequestLog.account_id)).label("active_accounts"),
        func.coalesce(
            func.sum(case((RequestLog.status.not_in(NON_ERROR_STATUSES), 1), else_=0)),
            0,
        ).label("error_count"),
        func.coalesce(
            func.sum(case((RequestLog.status == CANCELLED_STATUS, 1), else_=0)),
            0,
        ).label("cancelled_count"),
    ]
    if include_conversations:
        columns.append(func.count(func.distinct(ReportsRepository._conversation_id_expr())).label("conversation_count"))
    return (
        select(*columns)
        .select_from(
            day_ranges_cte.join(
                RequestLog,
                and_(
                    RequestLog.requested_at >= day_ranges_cte.c.day_start,
                    RequestLog.requested_at < day_ranges_cte.c.day_end,
                    _normal_traffic_clause(),
                    *([RequestLog.account_id.in_(account_ids)] if account_ids else []),
                    *([RequestLog.model == model] if model else []),
                    *([useragent_group_clause] if useragent_group_clause is not None else []),
                    *([RequestLog.api_key_id.in_(api_key_ids)] if api_key_ids else []),
                ),
            )
        )
        .group_by(day_ranges_cte.c.report_date)
        .order_by(day_ranges_cte.c.report_date)
    )


def _daily_bucket_ranges(
    start_date: date,
    end_date: date,
    timezone_info: ZoneInfo | timezone,
) -> list[tuple[str, datetime, datetime]]:
    ranges: list[tuple[str, datetime, datetime]] = []
    current_date = start_date
    while current_date <= end_date:
        day_start = datetime.combine(current_date, datetime.min.time(), tzinfo=timezone_info)
        next_day_start = datetime.combine(current_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone_info)
        ranges.append(
            (
                current_date.isoformat(),
                day_start.astimezone(timezone.utc).replace(tzinfo=None),
                next_day_start.astimezone(timezone.utc).replace(tzinfo=None),
            )
        )
        current_date += timedelta(days=1)
    return ranges
