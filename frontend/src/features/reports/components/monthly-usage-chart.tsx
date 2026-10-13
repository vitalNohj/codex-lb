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
import { formatCompactNumber, formatCurrency, formatNumber } from "@/utils/formatters";
import type { MonthlyUsageEntry } from "../schemas";
import { ReportChartCard } from "./report-chart-card";

export type MonthlyUsageChartProps = {
  data: MonthlyUsageEntry[];
};

// Same palette as the model distribution donut so a model keeps a
// recognizable color across the reports page.
const MODEL_COLORS = ["#3b82f6", "#10b981", "#f59e0b", "#ec4899", "#8b5cf6", "#06b6d4"];

type MonthlyTooltipDatum = {
  month: string;
  requests: number;
  inputTokens: number;
  outputTokens: number;
  cachedInputTokens: number;
  costUsd: number;
};

type MonthlyTooltipProps = {
  active?: boolean;
  label?: string | number;
  payload?: ReadonlyArray<{ dataKey?: string | number; name?: string | number; value?: number | string; color?: string }>;
  totals: Map<string, MonthlyTooltipDatum>;
  labels: {
    requests: string;
    inputTokens: string;
    cachedTokens: string;
    outputTokens: string;
    cost: string;
  };
};

function MonthlyTooltip({ active, label, payload, totals, labels }: MonthlyTooltipProps) {
  if (!active || !payload?.length) return null;
  const totalsDatum = totals.get(String(label));

  return (
    <div className="rounded-xl border border-border bg-popover p-2.5 shadow-md">
      <p className="mb-1.5 px-2 text-[11px] font-medium text-muted-foreground">{String(label)}</p>
      {totalsDatum ? (
        <div className="space-y-0.5 px-2 pb-1.5 text-xs text-popover-foreground">
          <div className="flex items-center justify-between gap-4">
            <span>{labels.requests}</span>
            <span className="ml-auto font-semibold tabular-nums">
              {formatNumber(totalsDatum.requests)}
            </span>
          </div>
          <div className="flex items-center justify-between gap-4">
            <span>{labels.inputTokens}</span>
            <span className="ml-auto font-semibold tabular-nums">
              {formatNumber(totalsDatum.inputTokens)}
            </span>
          </div>
          <div className="flex items-center justify-between gap-4">
            <span>{labels.cachedTokens}</span>
            <span className="ml-auto font-semibold tabular-nums">
              {formatNumber(totalsDatum.cachedInputTokens)}
            </span>
          </div>
          <div className="flex items-center justify-between gap-4">
            <span>{labels.outputTokens}</span>
            <span className="ml-auto font-semibold tabular-nums">
              {formatNumber(totalsDatum.outputTokens)}
            </span>
          </div>
          <div className="flex items-center justify-between gap-4">
            <span>{labels.cost}</span>
            <span className="ml-auto font-semibold tabular-nums">
              {formatCurrency(totalsDatum.costUsd)}
            </span>
          </div>
        </div>
      ) : null}
      <div className="space-y-1">
        {payload.map((entry, i) => {
          const color = entry.color ?? "#888";
          return (
            <div
              key={String(entry.dataKey ?? i)}
              className="flex items-center gap-2 rounded-lg px-2.5 py-1.5"
              style={{ backgroundColor: `${color}18` }}
            >
              <span
                className="h-2 w-2 shrink-0 rounded-full"
                style={{ backgroundColor: color }}
              />
              <span className="text-xs text-popover-foreground">{String(entry.dataKey ?? "")}</span>
              <span className="ml-auto pl-2 text-xs font-semibold tabular-nums text-popover-foreground">
                {formatCurrency(Number(entry.value ?? 0))}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function MonthlyUsageChart({ data }: MonthlyUsageChartProps) {
  const { t } = useTranslation();

  const { chartData, totals, models } = useMemo(() => {
    const modelTotals = new Map<string, number>();
    const totalsMap = new Map<string, MonthlyTooltipDatum>();
    const chartRows = data.map((entry) => {
      const row: Record<string, string | number> = {
        month: entry.month,
        requests: entry.requests,
        inputTokens: entry.inputTokens,
        outputTokens: entry.outputTokens,
        cachedInputTokens: entry.cachedInputTokens,
        costUsd: entry.costUsd,
      };
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
    const orderedModels = [...modelTotals.keys()].sort(
      (a, b) => (modelTotals.get(b) ?? 0) - (modelTotals.get(a) ?? 0),
    );
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
    <ReportChartCard title={t("reports.charts.monthlyUsage")} empty={data.length === 0}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={chartData} margin={{ top: 5, right: 10, left: 10, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
          <XAxis
            dataKey="month"
            tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
            axisLine={false}
            tickLine={false}
            tickFormatter={(value: number) => formatCompactNumber(value)}
          />
          <Tooltip
            cursor={{ fill: "hsl(var(--muted))", opacity: 0.4 }}
            content={<MonthlyTooltip totals={totals} labels={labels} />}
          />
          {models.map((model, index) => (
            <Bar
              key={model}
              dataKey={model}
              stackId="cost"
              fill={MODEL_COLORS[index % MODEL_COLORS.length]}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </ReportChartCard>
  );
}