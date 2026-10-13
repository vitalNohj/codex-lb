import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "@/components/lazy-recharts";
import { getDateDisplayFormat } from "@/hooks/use-date-format";
import { useReducedMotion } from "@/hooks/use-reduced-motion";
import { formatCurrency, formatNumber } from "@/utils/formatters";
import type { MonthlyUsageEntry } from "../schemas";
import { ReportChartCard } from "./report-chart-card";

export type MonthlyUsageChartProps = {
  data: MonthlyUsageEntry[];
};

// Same palette as the model distribution donut so a model keeps a
// recognizable color across the reports page.
const MODEL_COLORS = ["#3b82f6", "#10b981", "#f59e0b", "#ec4899", "#8b5cf6", "#06b6d4"];
const MAX_BAR_SIZE = 56;
const BAR_RADIUS: [number, number, number, number] = [4, 4, 0, 0];

type MonthlyTotals = {
  month: string;
  requests: number;
  inputTokens: number;
  outputTokens: number;
  cachedInputTokens: number;
  costUsd: number;
};

type MonthFormatters = {
  /** Compact axis label, e.g. "Jun 2026" (or "2026-06" in ISO mode). */
  short: (month: string) => string;
  /** Tooltip heading, e.g. "June 2026". */
  long: (month: string) => string;
};

function parseMonth(month: string): Date | null {
  const match = /^(\d{4})-(\d{2})$/.exec(month);
  if (!match) return null;
  return new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, 1));
}

function buildMonthFormatters(language: string | undefined): MonthFormatters {
  if (getDateDisplayFormat() === "iso8601") {
    return { short: (month) => month, long: (month) => month };
  }
  const locale = language || "en";
  const shortFormat = new Intl.DateTimeFormat(locale, { month: "short", year: "numeric", timeZone: "UTC" });
  const longFormat = new Intl.DateTimeFormat(locale, { month: "long", year: "numeric", timeZone: "UTC" });
  const apply = (format: Intl.DateTimeFormat) => (month: string) => {
    const date = parseMonth(month);
    return date ? format.format(date) : month;
  };
  return { short: apply(shortFormat), long: apply(longFormat) };
}

const axisCurrencyFormat = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  notation: "compact",
  maximumFractionDigits: 1,
});

function formatAxisCurrency(value: number): string {
  return axisCurrencyFormat.format(value);
}

type MonthlyTooltipProps = {
  active?: boolean;
  label?: string | number;
  payload?: ReadonlyArray<{ dataKey?: string | number; name?: string | number; value?: number | string; color?: string }>;
  totals: Map<string, MonthlyTotals>;
  formatMonth: (month: string) => string;
  labels: {
    requests: string;
    inputTokens: string;
    cachedTokens: string;
    outputTokens: string;
    cost: string;
  };
};

function MonthlyTooltip({ active, label, payload, totals, formatMonth, labels }: MonthlyTooltipProps) {
  if (!active || !payload?.length) return null;
  const month = String(label);
  const totalsDatum = totals.get(month);
  // Largest share first, and drop models with no usage that month.
  const modelRows = payload
    .filter((entry) => Number(entry.value ?? 0) > 0)
    .sort((a, b) => Number(b.value ?? 0) - Number(a.value ?? 0));

  const stats = totalsDatum
    ? [
        { label: labels.requests, value: totalsDatum.requests },
        { label: labels.inputTokens, value: totalsDatum.inputTokens },
        { label: labels.cachedTokens, value: totalsDatum.cachedInputTokens },
        { label: labels.outputTokens, value: totalsDatum.outputTokens },
      ]
    : [];

  return (
    <div className="min-w-[13rem] rounded-xl border border-border bg-popover p-2.5 shadow-md">
      <div className="mb-1.5 flex items-baseline justify-between gap-4 px-2">
        <p className="text-[11px] font-medium text-muted-foreground">{formatMonth(month)}</p>
        {totalsDatum ? (
          <p className="text-sm font-semibold tabular-nums text-popover-foreground">
            <span className="sr-only">{labels.cost} </span>
            {formatCurrency(totalsDatum.costUsd)}
          </p>
        ) : null}
      </div>
      <div className="space-y-1">
        {modelRows.map((entry, i) => {
          const color = entry.color ?? "#888";
          return (
            <div
              key={String(entry.dataKey ?? i)}
              className="flex items-center gap-2 rounded-lg px-2.5 py-1.5"
              style={{ backgroundColor: `${color}18` }}
            >
              <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: color }} />
              <span className="truncate text-xs text-popover-foreground">{String(entry.dataKey ?? "")}</span>
              <span className="ml-auto pl-2 text-xs font-semibold tabular-nums text-popover-foreground">
                {formatCurrency(Number(entry.value ?? 0))}
              </span>
            </div>
          );
        })}
      </div>
      {stats.length > 0 ? (
        <dl className="mt-1.5 space-y-0.5 border-t border-border px-2 pt-1.5 text-[11px]">
          {stats.map((stat) => (
            <div key={stat.label} className="flex items-center justify-between gap-4">
              <dt className="text-muted-foreground">{stat.label}</dt>
              <dd className="font-medium tabular-nums text-popover-foreground">{formatNumber(stat.value)}</dd>
            </div>
          ))}
        </dl>
      ) : null}
    </div>
  );
}

function ModelLegend({ models }: { models: Array<{ model: string; color: string }> }) {
  return (
    <ul className="flex min-w-0 flex-wrap justify-end gap-x-3 gap-y-1">
      {models.map(({ model, color }) => (
        <li key={model} className="flex min-w-0 items-center gap-1.5 text-[11px] text-muted-foreground">
          <span aria-hidden="true" className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: color }} />
          <span className="truncate">{model}</span>
        </li>
      ))}
    </ul>
  );
}

export function MonthlyUsageChart({ data }: MonthlyUsageChartProps) {
  const { t, i18n } = useTranslation();
  const reducedMotion = useReducedMotion();
  const language = i18n.resolvedLanguage ?? i18n.language;
  const monthFormat = useMemo(() => buildMonthFormatters(language), [language]);

  const { chartData, totals, models } = useMemo(() => {
    const modelTotals = new Map<string, number>();
    const totalsMap = new Map<string, MonthlyTotals>();
    const chartRows = data.map((entry) => {
      const row: Record<string, string | number> = { month: entry.month };
      for (const modelEntry of entry.models) {
        row[modelEntry.model] = modelEntry.costUsd;
        modelTotals.set(
          modelEntry.model,
          (modelTotals.get(modelEntry.model) ?? 0) + modelEntry.costUsd,
        );
      }
      totalsMap.set(entry.month, {
        month: entry.month,
        requests: entry.requests,
        inputTokens: entry.inputTokens,
        outputTokens: entry.outputTokens,
        cachedInputTokens: entry.cachedInputTokens,
        costUsd: entry.costUsd,
      });
      return row;
    });
    const orderedModels = [...modelTotals.keys()]
      .sort((a, b) => (modelTotals.get(b) ?? 0) - (modelTotals.get(a) ?? 0))
      .map((model, index) => ({ model, color: MODEL_COLORS[index % MODEL_COLORS.length] }));
    return { chartData: chartRows, totals: totalsMap, models: orderedModels };
  }, [data]);

  const labels = useMemo(
    () => ({
      requests: t("reports.monthly.requests"),
      inputTokens: t("reports.monthly.inputTokens"),
      cachedTokens: t("reports.monthly.cachedTokens"),
      outputTokens: t("reports.monthly.outputTokens"),
      cost: t("reports.dailyBreakdown.columns.cost"),
    }),
    [t],
  );

  return (
    <ReportChartCard
      title={t("reports.charts.monthlyUsage")}
      empty={data.length === 0}
      aside={models.length > 0 ? <ModelLegend models={models} /> : null}
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={chartData}
          margin={{ top: 5, right: 10, left: 10, bottom: 0 }}
          barCategoryGap="24%"
        >
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
          <XAxis
            dataKey="month"
            tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
            tickFormatter={monthFormat.short}
            axisLine={false}
            tickLine={false}
            minTickGap={8}
          />
          <YAxis
            tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
            axisLine={false}
            tickLine={false}
            tickFormatter={formatAxisCurrency}
            width={48}
          />
          <Tooltip
            cursor={{ fill: "var(--muted)", opacity: 0.5 }}
            content={<MonthlyTooltip totals={totals} labels={labels} formatMonth={monthFormat.long} />}
          />
          {models.map(({ model, color }, index) => (
            <Bar
              key={model}
              dataKey={model}
              stackId="cost"
              fill={color}
              maxBarSize={MAX_BAR_SIZE}
              radius={index === models.length - 1 ? BAR_RADIUS : undefined}
              isAnimationActive={!reducedMotion}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </ReportChartCard>
  );
}
