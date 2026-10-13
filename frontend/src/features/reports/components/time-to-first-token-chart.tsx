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

export type TimeToFirstTokenChartProps = {
  startDate: string;
  endDate: string;
  data: DailyReportRow[];
  /** Start of the raw request-log window; earlier days have no per-request data. */
  rawMetricsSince?: string | null;
};

function formatSeconds(value: number): string {
  return `${(value / 1000).toFixed(1)}s`;
}

export function TimeToFirstTokenChart({ startDate, endDate, data, rawMetricsSince }: TimeToFirstTokenChartProps) {
  const { t } = useTranslation();
  const rows = buildContinuousDailyRows(startDate, endDate, data);
  const chartData = rows.map((d) => ({
    date: d.date.slice(5),
    // Pruned days have no per-request samples: plot a gap, not a zero.
    ttft: isBeforeRawWindow(d.date, rawMetricsSince) ? null : (d.medianTtftMs ?? 0),
  }));
  const showRawWindow = Boolean(rawMetricsSince && rows.some((d) => isBeforeRawWindow(d.date, rawMetricsSince)));

  return (
    <ReportChartCard
      title={t("reports.charts.timeToFirstToken")}
      empty={data.length === 0}
      aside={showRawWindow && rawMetricsSince ? <RawWindowBadge since={rawMetricsSince} /> : null}
    >
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chartData} margin={{ top: 5, right: 10, left: 10, bottom: 0 }}>
            <defs>
              <linearGradient id="ttftGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#f97316" stopOpacity={0.3} />
                <stop offset="100%" stopColor="#f97316" stopOpacity={0.05} />
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
              tickFormatter={formatSeconds}
            />
            <Tooltip
              filterNull={false}
              content={<ChartTooltip emptyLabel={t("reports.charts.rawWindowTooltip")} names={{ ttft: t("reports.charts.medianTtft") }} formatValue={formatSeconds} />}
            />
            <Area
              type="monotone"
              dataKey="ttft"
              stroke="#f97316"
              strokeWidth={2}
              fill="url(#ttftGrad)"
              dot={false}
              activeDot={{ r: 4, strokeWidth: 1.5, fill: "var(--popover)" }}
            />
          </AreaChart>
        </ResponsiveContainer>
    </ReportChartCard>
  );
}
