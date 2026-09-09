from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.utils.time import to_utc_naive, utcnow
from app.modules.reports.repository import (
    MAX_DAILY_REPORT_DAYS,
    ApiKeyDailyAggregateRow,
    DailyReportRangeTooLargeError,
    ReportsRepository,
)
from app.modules.reports.schemas import (
    AccountCostEntry,
    ApiKeyCostEntry,
    ApiKeyDailyRow,
    DailyReportRow,
    ModelCostEntry,
    ReportComparison,
    ReportComparisonPrevious,
    ReportsResponse,
    ReportSummary,
    UserAgentCostEntry,
)


class InvalidReportDateRangeError(ValueError):
    """Raised when a report starts after it ends."""


class ReportsService:
    def __init__(self, repository: ReportsRepository) -> None:
        self._repository = repository

    async def get_reports(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        report_timezone: str | None = None,
        account_ids: list[str] | None = None,
        model: str | None = None,
        useragent_group: str | None = None,
        api_key_ids: list[str] | None = None,
    ) -> ReportsResponse:
        timezone_info = _resolve_timezone(report_timezone)
        now = utcnow().replace(tzinfo=timezone.utc).astimezone(timezone_info)
        if end_date is None:
            end_date = now.date()
        if start_date is None:
            start_date = end_date - timedelta(days=6)
        if start_date > end_date:
            raise InvalidReportDateRangeError("start_date must be on or before end_date")
        window_days = (end_date - start_date).days + 1
        if window_days > MAX_DAILY_REPORT_DAYS:
            raise DailyReportRangeTooLargeError(f"report date range must be {MAX_DAILY_REPORT_DAYS} days or less")

        start_at = _local_midnight_to_utc_naive(start_date, timezone_info)
        end_at = _local_midnight_to_utc_naive(end_date + timedelta(days=1), timezone_info)
        previous_end_date = start_date - timedelta(days=1)
        previous_start_date = previous_end_date - timedelta(days=window_days - 1)
        previous_start_at = _local_midnight_to_utc_naive(previous_start_date, timezone_info)
        previous_end_at = _local_midnight_to_utc_naive(previous_end_date + timedelta(days=1), timezone_info)

        summary = await self._repository.aggregate_summary(
            start_at, end_at, account_ids, model, useragent_group, api_key_ids
        )
        previous_summary = await self._repository.aggregate_summary(
            previous_start_at,
            previous_end_at,
            account_ids,
            model,
            useragent_group,
            api_key_ids,
        )
        earliest_activity_at = await self._repository.earliest_report_activity_at(
            account_ids, model, useragent_group, api_key_ids
        )
        daily_rows = await self._repository.aggregate_daily_rows(
            start_date,
            end_date,
            timezone_info,
            account_ids,
            model,
            useragent_group,
            api_key_ids,
        )
        daily = [
            DailyReportRow(
                date=row.date,
                requests=row.requests,
                input_tokens=row.input_tokens,
                output_tokens=row.output_tokens,
                reasoning_tokens=row.reasoning_tokens,
                cached_input_tokens=row.cached_input_tokens,
                cost_usd=round(row.cost_usd, 4),
                active_accounts=row.active_accounts,
                conversations=row.conversation_count,
                error_count=row.error_count,
                cancelled_count=row.cancelled_count,
                median_ttft_ms=round(row.median_ttft_ms, 2),
                median_tps=round(row.median_tps, 2),
                median_queue_ms=round(row.median_queue_ms, 2),
            )
            for row in daily_rows
        ]
        by_model = await self._repository.aggregate_by_model(
            start_at, end_at, account_ids, model, useragent_group, api_key_ids
        )
        by_account = await self._repository.aggregate_by_account(
            start_at, end_at, account_ids, model, useragent_group, api_key_ids
        )
        by_useragent = await self._repository.aggregate_by_useragent(
            start_at,
            end_at,
            account_ids,
            model,
            useragent_group,
            api_key_ids,
        )
        daily_by_api_key_rows = await self._repository.aggregate_daily_by_api_key(
            start_date,
            end_date,
            timezone_info,
            account_ids,
            model,
            useragent_group,
            api_key_ids,
        )
        api_key_ids_found = sorted({row.api_key_id for row in daily_by_api_key_rows if row.api_key_id})
        api_key_labels = await self._repository.list_api_key_labels(api_key_ids_found)
        by_api_key, daily_by_api_key = build_api_key_report(
            daily_by_api_key_rows,
            api_key_labels,
            window_days,
        )

        model_total = sum(m.cost_usd for m in by_model)
        useragent_total = sum(u.cost_usd for u in by_useragent)
        comparison = ReportComparison(
            can_compare=earliest_activity_at is not None and earliest_activity_at <= previous_start_at,
            previous=ReportComparisonPrevious(
                total_cost_usd=round(previous_summary.total_cost_usd, 4),
                total_tokens=previous_summary.total_input_tokens + previous_summary.total_output_tokens,
                total_requests=previous_summary.total_requests,
            ),
        )

        return ReportsResponse(
            summary=ReportSummary(
                total_cost_usd=round(summary.total_cost_usd, 4),
                total_input_tokens=summary.total_input_tokens,
                total_output_tokens=summary.total_output_tokens,
                total_reasoning_tokens=summary.total_reasoning_tokens,
                reasoning_usage_known_requests=summary.reasoning_usage_known_requests,
                total_cached_tokens=summary.total_cached_tokens,
                total_requests=summary.total_requests,
                total_errors=summary.total_errors,
                total_cancelled=summary.total_cancelled,
                active_accounts=summary.active_accounts,
                total_conversations=summary.conversation_count,
                avg_cost_per_day=round(summary.total_cost_usd / window_days, 4),
                avg_requests_per_day=round(summary.total_requests / window_days, 2),
            ),
            comparison=comparison,
            daily=daily,
            by_model=[
                ModelCostEntry(
                    model=m.model,
                    cost_usd=round(m.cost_usd, 4),
                    requests=m.request_count,
                    percentage=round((m.cost_usd / model_total * 100), 1) if model_total > 0 else 0,
                )
                for m in by_model
            ],
            by_account=[
                AccountCostEntry(
                    account_id=a.account_id,
                    alias=a.alias,
                    cost_usd=round(a.cost_usd, 4),
                    requests=a.request_count,
                )
                for a in by_account
            ],
            by_useragent=[
                UserAgentCostEntry(
                    useragent=u.useragent_group,
                    cost_usd=round(u.cost_usd, 4),
                    requests=u.request_count,
                    percentage=round((u.cost_usd / useragent_total * 100), 1) if useragent_total > 0 else 0,
                )
                for u in by_useragent
            ],
            by_api_key=by_api_key,
            daily_by_api_key=daily_by_api_key,
        )


def build_api_key_report(
    daily_rows: list[ApiKeyDailyAggregateRow],
    labels: dict[str, tuple[str, str]],
    window_days: int,
) -> tuple[list[ApiKeyCostEntry], list[ApiKeyDailyRow]]:
    totals: dict[str | None, _ApiKeyTotals] = {}
    peaks: dict[str | None, ApiKeyDailyAggregateRow] = {}
    for row in daily_rows:
        current = totals.get(row.api_key_id)
        if current is None:
            totals[row.api_key_id] = _ApiKeyTotals(
                requests=row.requests,
                input_tokens=row.input_tokens,
                output_tokens=row.output_tokens,
                cost_usd=row.cost_usd,
            )
        else:
            current.requests += row.requests
            current.input_tokens += row.input_tokens
            current.output_tokens += row.output_tokens
            current.cost_usd += row.cost_usd
        peak = peaks.get(row.api_key_id)
        if peak is None or row.requests > peak.requests or (row.requests == peak.requests and row.date > peak.date):
            peaks[row.api_key_id] = row

    cost_total = sum(total.cost_usd for total in totals.values())
    by_api_key = [
        _api_key_cost_entry(
            api_key_id,
            total,
            peaks[api_key_id],
            labels,
            window_days,
            cost_total,
        )
        for api_key_id, total in totals.items()
    ]
    by_api_key.sort(key=lambda entry: (-entry.cost_usd, entry.api_key_id or ""))
    daily_by_api_key = [
        ApiKeyDailyRow(
            date=row.date,
            api_key_id=row.api_key_id,
            requests=row.requests,
            cost_usd=round(row.cost_usd, 4),
        )
        for row in daily_rows
    ]
    return by_api_key, daily_by_api_key


class _ApiKeyTotals:
    __slots__ = ("requests", "input_tokens", "output_tokens", "cost_usd")

    def __init__(self, requests: int, input_tokens: int, output_tokens: int, cost_usd: float) -> None:
        self.requests = requests
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cost_usd = cost_usd


def _api_key_cost_entry(
    api_key_id: str | None,
    total: _ApiKeyTotals,
    peak: ApiKeyDailyAggregateRow,
    labels: dict[str, tuple[str, str]],
    window_days: int,
    cost_total: float,
) -> ApiKeyCostEntry:
    name, key_prefix = labels.get(api_key_id, (None, None)) if api_key_id else (None, None)
    avg_day_requests = total.requests / window_days if window_days > 0 else 0.0
    burst_ratio = peak.requests / avg_day_requests if avg_day_requests > 0 else 0.0
    return ApiKeyCostEntry(
        api_key_id=api_key_id,
        name=name,
        key_prefix=key_prefix,
        cost_usd=round(total.cost_usd, 4),
        requests=total.requests,
        tokens=total.input_tokens + total.output_tokens,
        percentage=round((total.cost_usd / cost_total * 100), 1) if cost_total > 0 else 0,
        avg_day_requests=round(avg_day_requests, 2),
        peak_day_date=peak.date,
        peak_day_requests=peak.requests,
        peak_day_cost_usd=round(peak.cost_usd, 4),
        burst_ratio=round(burst_ratio, 2),
    )


def _resolve_timezone(timezone_name: str | None) -> ZoneInfo | timezone:
    if not timezone_name:
        return timezone.utc
    try:
        return ZoneInfo(timezone_name)
    except (ValueError, ZoneInfoNotFoundError):
        return timezone.utc


def _local_midnight_to_utc_naive(value: date, timezone_info: ZoneInfo | timezone) -> datetime:
    return to_utc_naive(datetime.combine(value, datetime.min.time(), tzinfo=timezone_info))
