import { useTranslation } from "react-i18next";

import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "@/components/lazy-recharts";
import type { DailyReportRow } from "../schemas";
import { buildContinuousDailyRows } from "../daily-series";
import { ChartTooltip } from "./chart-tooltip";
import { ReportChartCard } from "./report-chart-card";
import { isBeforeRawWindow } from "../raw-window";
import { PrunedRangeShade, RawWindowBadge } from "./raw-window-indicators";

export type QueueWaitChartProps = {
  startDate: string;
  endDate: string;
  data: DailyReportRow[];
  /** Start of the raw request-log window; earlier days have no per-request data. */
  rawMetricsSince?: string | null;
};

function formatQueueMs(value: number): string {
  if (value >= 1000) {
    return `${(value / 1000).toFixed(1)}s`;
  }
  return `${Math.round(value)}ms`;
}

export function QueueWaitChart({ startDate, endDate, data, rawMetricsSince }: QueueWaitChartProps) {
  const { t } = useTranslation();
  const rows = buildContinuousDailyRows(startDate, endDate, data);
  const chartData = rows.map((d) => ({
    date: d.date.slice(5),
    // Pruned days have no per-request samples: plot a gap, not a zero.
    queue: isBeforeRawWindow(d.date, rawMetricsSince) ? null : (d.medianQueueMs ?? 0),
  }));
  const showRawWindow = Boolean(rawMetricsSince && rows.some((d) => isBeforeRawWindow(d.date, rawMetricsSince)));

  return (
    <ReportChartCard
      title={t("reports.charts.queueWait")}
      empty={data.length === 0}
      aside={showRawWindow && rawMetricsSince ? <RawWindowBadge since={rawMetricsSince} /> : null}
    >
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chartData} margin={{ top: 5, right: 10, left: 10, bottom: 0 }}>
            <defs>
              <linearGradient id="queueGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#8b5cf6" stopOpacity={0.3} />
                <stop offset="100%" stopColor="#8b5cf6" stopOpacity={0.05} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
            <PrunedRangeShade dates={rows.map((d) => d.date)} rawMetricsSince={rawMetricsSince} />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
              axisLine={false}
              tickLine={false}
              tickFormatter={formatQueueMs}
            />
            <Tooltip
              filterNull={false}
              content={
                <ChartTooltip emptyLabel={t("reports.charts.rawWindowTooltip")} names={{ queue: t("reports.charts.medianQueueWait") }} formatValue={formatQueueMs} />
              }
            />
            <Area
              type="monotone"
              dataKey="queue"
              stroke="#8b5cf6"
              strokeWidth={2}
              fill="url(#queueGrad)"
              dot={false}
              activeDot={{ r: 4, strokeWidth: 1.5, fill: "var(--popover)" }}
            />
          </AreaChart>
        </ResponsiveContainer>
    </ReportChartCard>
  );
}
