from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest

from app.modules.reports.repository import (
    ApiKeyDailyAggregateRow,
    DailyReportRangeTooLargeError,
    ReportsRepository,
)
from app.modules.reports.service import InvalidReportDateRangeError, ReportsService, build_api_key_report

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("start_date", "end_date", "report_timezone"),
    [
        pytest.param(
            date(2026, 2, 15),
            date(2026, 2, 16),
            "Africa/Casablanca",
            id="casablanca-offset-to-zero",
        ),
        pytest.param(
            date(2026, 3, 22),
            date(2026, 3, 23),
            "Africa/Casablanca",
            id="casablanca-offset-from-zero",
        ),
        pytest.param(date(2026, 6, 1), date(2026, 6, 2), "UTC", id="utc"),
        pytest.param(
            date(2026, 6, 1),
            date(2026, 6, 2),
            "Africa/Casablanca",
            id="casablanca-stable-offset",
        ),
        pytest.param(
            date(2026, 6, 1),
            date(2026, 6, 2),
            "Mars/Olympus_Mons",
            id="invalid-zone-utc-fallback",
        ),
    ],
)
async def test_get_reports_averages_use_inclusive_local_calendar_days(
    start_date: date,
    end_date: date,
    report_timezone: str,
) -> None:
    summary = SimpleNamespace(
        total_cost_usd=60.0,
        total_input_tokens=0,
        total_output_tokens=0,
        total_reasoning_tokens=0,
        reasoning_usage_known_requests=0,
        total_cached_tokens=0,
        total_requests=30,
        conversation_count=0,
        total_errors=0,
        total_cancelled=0,
        active_accounts=1,
    )
    repo = SimpleNamespace(
        aggregate_summary=AsyncMock(side_effect=[summary, summary]),
        aggregate_daily_rows=AsyncMock(return_value=[]),
        aggregate_by_model=AsyncMock(return_value=[]),
        aggregate_by_account=AsyncMock(return_value=[]),
        aggregate_by_useragent=AsyncMock(return_value=[]),
        aggregate_daily_by_api_key=AsyncMock(return_value=[]),
        list_api_key_labels=AsyncMock(return_value={}),
        earliest_report_activity_at=AsyncMock(return_value=None),
    )
    service = ReportsService(cast(ReportsRepository, repo))

    result = await service.get_reports(
        start_date=start_date,
        end_date=end_date,
        report_timezone=report_timezone,
    )

    assert result.summary.avg_cost_per_day == 30.0
    assert result.summary.avg_requests_per_day == 15.0


@pytest.mark.asyncio
async def test_get_reports_rejects_oversized_range_after_applying_default_end_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = SimpleNamespace(
        aggregate_summary=AsyncMock(),
        aggregate_daily_rows=AsyncMock(),
        aggregate_by_model=AsyncMock(),
        aggregate_by_account=AsyncMock(),
        earliest_report_activity_at=AsyncMock(),
    )
    service = ReportsService(cast(ReportsRepository, repo))
    fixed_now = datetime(2026, 6, 12, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("app.modules.reports.service.utcnow", lambda: fixed_now)

    with pytest.raises(DailyReportRangeTooLargeError, match="730 days or less"):
        await service.get_reports(start_date=date(2020, 1, 1))

    repo.aggregate_summary.assert_not_awaited()
    repo.aggregate_daily_rows.assert_not_awaited()
    repo.aggregate_by_model.assert_not_awaited()
    repo.aggregate_by_account.assert_not_awaited()
    repo.earliest_report_activity_at.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_reports_rejects_inverted_defaulted_range_before_repository_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = SimpleNamespace(
        aggregate_summary=AsyncMock(),
        aggregate_daily_rows=AsyncMock(),
        aggregate_by_model=AsyncMock(),
        aggregate_by_account=AsyncMock(),
        aggregate_by_useragent=AsyncMock(),
        earliest_report_activity_at=AsyncMock(),
    )
    service = ReportsService(cast(ReportsRepository, repo))
    fixed_now = datetime(2026, 6, 12, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("app.modules.reports.service.utcnow", lambda: fixed_now)

    with pytest.raises(
        InvalidReportDateRangeError,
        match="start_date must be on or before end_date",
    ):
        await service.get_reports(start_date=date(2026, 6, 13))

    repo.aggregate_summary.assert_not_awaited()
    repo.aggregate_daily_rows.assert_not_awaited()
    repo.aggregate_by_model.assert_not_awaited()
    repo.aggregate_by_account.assert_not_awaited()
    repo.aggregate_by_useragent.assert_not_awaited()
    repo.earliest_report_activity_at.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_reports_serializes_conversation_and_breakdown_request_counts() -> None:
    repo = SimpleNamespace(
        aggregate_summary=AsyncMock(
            side_effect=[
                SimpleNamespace(
                    total_cost_usd=1.2,
                    total_input_tokens=12,
                    total_output_tokens=6,
                    total_reasoning_tokens=4,
                    reasoning_usage_known_requests=2,
                    total_cached_tokens=2,
                    total_requests=2,
                    conversation_count=1,
                    total_errors=0,
                    total_cancelled=0,
                    active_accounts=1,
                ),
                SimpleNamespace(
                    total_cost_usd=0.4,
                    total_input_tokens=4,
                    total_output_tokens=2,
                    total_reasoning_tokens=2,
                    reasoning_usage_known_requests=1,
                    total_cached_tokens=0,
                    total_requests=1,
                    conversation_count=0,
                    total_errors=0,
                    total_cancelled=0,
                    active_accounts=1,
                ),
            ]
        ),
        aggregate_daily_rows=AsyncMock(
            return_value=[
                SimpleNamespace(
                    date="2026-06-01",
                    requests=2,
                    conversation_count=1,
                    input_tokens=12,
                    output_tokens=6,
                    reasoning_tokens=None,
                    cached_input_tokens=2,
                    cost_usd=1.2,
                    active_accounts=1,
                    error_count=0,
                    cancelled_count=0,
                    median_ttft_ms=123.456,
                    median_tps=78.901,
                    median_queue_ms=45.678,
                )
            ]
        ),
        aggregate_by_model=AsyncMock(return_value=[SimpleNamespace(model="gpt-5.1", cost_usd=1.2, request_count=2)]),
        aggregate_by_account=AsyncMock(
            return_value=[SimpleNamespace(account_id="acc_reports", alias="Reports", cost_usd=1.2, request_count=2)]
        ),
        aggregate_by_useragent=AsyncMock(
            return_value=[SimpleNamespace(useragent_group="opencode", cost_usd=1.2, request_count=2)]
        ),
        aggregate_daily_by_api_key=AsyncMock(return_value=[]),
        list_api_key_labels=AsyncMock(return_value={}),
        earliest_report_activity_at=AsyncMock(return_value=datetime(2026, 5, 1, 0, 0, 0)),
    )
    service = ReportsService(cast(ReportsRepository, repo))

    result = await service.get_reports(
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 1),
        useragent_group="opencode",
    )

    repo.aggregate_summary.assert_any_await(
        datetime(2026, 6, 1, 0, 0, 0),
        datetime(2026, 6, 2, 0, 0, 0),
        None,
        None,
        "opencode",
        None,
    )
    repo.aggregate_daily_rows.assert_awaited_once_with(
        date(2026, 6, 1),
        date(2026, 6, 1),
        timezone.utc,
        None,
        None,
        "opencode",
        None,
    )
    repo.aggregate_by_model.assert_awaited_once_with(
        datetime(2026, 6, 1, 0, 0, 0),
        datetime(2026, 6, 2, 0, 0, 0),
        None,
        None,
        "opencode",
        None,
    )
    repo.aggregate_by_account.assert_awaited_once_with(
        datetime(2026, 6, 1, 0, 0, 0),
        datetime(2026, 6, 2, 0, 0, 0),
        None,
        None,
        "opencode",
        None,
    )
    repo.aggregate_by_useragent.assert_awaited_once_with(
        datetime(2026, 6, 1, 0, 0, 0),
        datetime(2026, 6, 2, 0, 0, 0),
        None,
        None,
        "opencode",
        None,
    )
    repo.aggregate_daily_by_api_key.assert_awaited_once_with(
        date(2026, 6, 1),
        date(2026, 6, 1),
        timezone.utc,
        None,
        None,
        "opencode",
        None,
    )
    repo.list_api_key_labels.assert_awaited_once_with([])
    repo.earliest_report_activity_at.assert_awaited_once_with(None, None, "opencode", None)

    assert result.daily[0].median_ttft_ms == 123.46
    assert result.daily[0].conversations == 1
    assert result.daily[0].median_tps == 78.9
    assert result.daily[0].median_queue_ms == 45.68
    assert result.daily[0].reasoning_tokens is None
    assert result.by_model[0].model == "gpt-5.1"
    assert result.summary.total_conversations == 1
    assert result.summary.total_reasoning_tokens == 4
    assert result.summary.reasoning_usage_known_requests == 2
    assert result.comparison.previous.total_tokens == 6
    assert result.by_model[0].requests == 2
    assert result.by_useragent[0].useragent == "opencode"
    assert result.by_useragent[0].requests == 2
    assert result.by_useragent[0].percentage == 100.0
    assert result.by_api_key == []
    assert result.daily_by_api_key == []


def test_build_api_key_report_compares_bursty_and_steady_keys() -> None:
    by_api_key, daily_by_api_key = build_api_key_report(
        [
            ApiKeyDailyAggregateRow(
                date="2026-06-01",
                api_key_id="batch",
                requests=70,
                input_tokens=70,
                output_tokens=70,
                cost_usd=7.0,
            ),
            *[
                ApiKeyDailyAggregateRow(
                    date=f"2026-06-0{day}",
                    api_key_id="agent",
                    requests=10,
                    input_tokens=10,
                    output_tokens=10,
                    cost_usd=1.0,
                )
                for day in range(1, 8)
            ],
            ApiKeyDailyAggregateRow(
                date="2026-06-02",
                api_key_id=None,
                requests=3,
                input_tokens=3,
                output_tokens=1,
                cost_usd=0.3,
            ),
            ApiKeyDailyAggregateRow(
                date="2026-06-03",
                api_key_id="gone",
                requests=2,
                input_tokens=2,
                output_tokens=2,
                cost_usd=0.2,
            ),
        ],
        {"batch": ("Batch job", "sk-batch"), "agent": ("Agent", "sk-agent")},
        7,
    )

    by_id = {entry.api_key_id: entry for entry in by_api_key}
    assert by_id["batch"].requests == 70
    assert by_id["batch"].avg_day_requests == 10
    assert by_id["batch"].peak_day_requests == 70
    assert by_id["batch"].peak_day_date == "2026-06-01"
    assert by_id["batch"].burst_ratio == 7
    assert by_id["batch"].name == "Batch job"
    assert by_id["agent"].requests == 70
    assert by_id["agent"].avg_day_requests == 10
    assert by_id["agent"].peak_day_requests == 10
    assert by_id["agent"].burst_ratio == 1
    assert by_id[None].api_key_id is None
    assert by_id[None].name is None
    assert by_id["gone"].name is None
    assert by_id["gone"].key_prefix is None
    assert [row.api_key_id for row in daily_by_api_key if row.date == "2026-06-01"] == ["batch", "agent"]


def test_build_api_key_report_breaks_peak_ties_with_the_latest_date() -> None:
    by_api_key, _ = build_api_key_report(
        [
            ApiKeyDailyAggregateRow(
                date="2026-06-01",
                api_key_id="key-1",
                requests=5,
                input_tokens=5,
                output_tokens=1,
                cost_usd=0.5,
            ),
            ApiKeyDailyAggregateRow(
                date="2026-06-03",
                api_key_id="key-1",
                requests=5,
                input_tokens=5,
                output_tokens=1,
                cost_usd=0.4,
            ),
        ],
        {"key-1": ("One", "sk-one")},
        3,
    )

    assert by_api_key[0].peak_day_date == "2026-06-03"
    assert by_api_key[0].peak_day_requests == 5
    assert by_api_key[0].peak_day_cost_usd == 0.4
    assert by_api_key[0].avg_day_requests == 3.33
    assert by_api_key[0].burst_ratio == 1.5

