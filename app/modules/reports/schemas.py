from __future__ import annotations

from pydantic import Field

from app.modules.shared.schemas import DashboardModel


class DailyReportRow(DashboardModel):
    date: str
    requests: int
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int | None
    cached_input_tokens: int
    cost_usd: float
    active_accounts: int
    conversations: int = 0
    error_count: int = 0
    cancelled_count: int = 0
    median_ttft_ms: float = 0.0
    median_tps: float = 0.0
    median_queue_ms: float = 0.0


class ModelCostEntry(DashboardModel):
    model: str
    cost_usd: float
    requests: int = 0
    percentage: float = 0.0


class AccountCostEntry(DashboardModel):
    account_id: str | None
    alias: str | None = None
    cost_usd: float = 0.0
    requests: int = 0


class UserAgentCostEntry(DashboardModel):
    useragent: str
    cost_usd: float = 0.0
    requests: int = 0
    percentage: float = 0.0


class ReportSummary(DashboardModel):
    total_cost_usd: float
    total_input_tokens: int
    total_output_tokens: int
    total_reasoning_tokens: int
    reasoning_usage_known_requests: int
    total_cached_tokens: int
    total_requests: int
    total_errors: int
    total_cancelled: int = 0
    active_accounts: int
    total_conversations: int = 0
    avg_cost_per_day: float = 0.0
    avg_requests_per_day: float = 0.0


class ReportComparisonPrevious(DashboardModel):
    total_cost_usd: float
    total_tokens: int
    total_requests: int


class ReportComparison(DashboardModel):
    can_compare: bool
    previous: ReportComparisonPrevious


class MonthlyModelEntry(DashboardModel):
    """One model's share of a month (NULL-model rows are excluded from the
    split; they still count toward the month totals)."""

    model: str
    cost_usd: float = 0.0
    requests: int = 0
    percentage: float = 0.0


class MonthlyUsageEntry(DashboardModel):
    """One UTC month of the lifetime monthly view, grouped from the
    permanent daily rollups (+ raw live tail)."""

    month: str
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    cost_usd: float = 0.0
    models: list[MonthlyModelEntry] = Field(default_factory=list)


class ReportsResponse(DashboardModel):
    summary: ReportSummary
    comparison: ReportComparison
    daily: list[DailyReportRow] = Field(default_factory=list)
    by_model: list[ModelCostEntry] = Field(default_factory=list)
    by_account: list[AccountCostEntry] = Field(default_factory=list)
    by_useragent: list[UserAgentCostEntry] = Field(default_factory=list)
    monthly: list[MonthlyUsageEntry] = Field(default_factory=list)
    # Inclusive UTC date from which the request-log window is guaranteed
    # (None when retention is disabled): raw-only measures — per-request
    # speed medians, the user-agent distribution, the reasoning-usage-known
    # request count — cover this window and are disclosed as such.
    raw_metrics_since: str | None = None
    # Inclusive UTC date of the earliest countable activity (rollup-backed
    # once raw is pruned); the All-time range origin.
    earliest_activity_at: str | None = None
