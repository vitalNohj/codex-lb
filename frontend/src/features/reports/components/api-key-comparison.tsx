import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown, Download, KeyRound } from "lucide-react";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";

import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "@/components/lazy-recharts";
import { EmptyState } from "@/components/empty-state";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useDateDisplayFormatStore } from "@/hooks/use-date-format";
import { formatCurrency } from "@/utils/formatters";
import {
  API_KEY_OTHER_SERIES_ID,
  apiKeySeriesId,
  buildApiKeyChartModel,
  burstPattern,
  type BurstPattern,
} from "../api-key-comparison";
import { formatReportBucketDate } from "../date";
import type { ApiKeyCostEntry, ApiKeyDailyRow } from "../schemas";
import { ChartTooltip } from "./chart-tooltip";
import { DistributionMetricToggle, type DistributionMetric } from "./distribution-metric-toggle";

export type ApiKeyComparisonProps = {
  startDate: string;
  endDate: string;
  byApiKey: ApiKeyCostEntry[];
  dailyByApiKey: ApiKeyDailyRow[];
};

type SortKey =
  | "name"
  | "requests"
  | "costUsd"
  | "tokens"
  | "avgDayRequests"
  | "peakDayRequests"
  | "burstRatio";
type SortDirection = "asc" | "desc";

const BURST_STYLES: Record<BurstPattern, string> = {
  burst: "bg-orange-500/10 text-orange-700 dark:text-orange-300",
  uneven: "bg-amber-500/10 text-amber-700 dark:text-amber-300",
  steady: "bg-muted text-muted-foreground",
};

export function ApiKeyComparison({
  startDate,
  endDate,
  byApiKey,
  dailyByApiKey,
}: ApiKeyComparisonProps) {
  const { t } = useTranslation();
  const dateDisplayFormat = useDateDisplayFormatStore((state) => state.dateDisplayFormat);
  const [metric, setMetric] = useState<DistributionMetric>("req");
  const [sort, setSort] = useState<{ key: SortKey; direction: SortDirection }>({
    key: "requests",
    direction: "desc",
  });
  const totalRequests = byApiKey.reduce((sum, entry) => sum + entry.requests, 0);
  const chartModel = useMemo(
    () => buildApiKeyChartModel(startDate, endDate, byApiKey, dailyByApiKey, metric),
    [startDate, endDate, byApiKey, dailyByApiKey, metric],
  );
  const seriesNames = useMemo(() => {
    const names: Record<string, string> = {};
    for (const entry of byApiKey) {
      names[apiKeySeriesId(entry.apiKeyId)] = formatApiKeyLabel(entry, t);
    }
    names[API_KEY_OTHER_SERIES_ID] = t("reports.apiKeys.other");
    return names;
  }, [byApiKey, t]);
  const rows = sortApiKeyRows(byApiKey, sort);

  const toggleSort = (key: SortKey) => {
    setSort((current) =>
      current.key === key
        ? { key, direction: current.direction === "asc" ? "desc" : "asc" }
        : { key, direction: key === "name" ? "asc" : "desc" },
    );
  };

  return (
    <div className="rounded-xl border bg-card p-5" data-testid="api-key-comparison">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-foreground">{t("reports.apiKeys.title")}</div>
          <p className="mt-0.5 text-xs text-muted-foreground">{t("reports.apiKeys.subtitle")}</p>
        </div>
        <div className="flex items-center gap-2">
          <DistributionMetricToggle metric={metric} onChange={setMetric} />
          <Button
            variant="outline"
            size="sm"
            className="h-7 gap-1 text-xs"
            disabled={byApiKey.length === 0}
            onClick={() => exportApiKeyCsv(rows, t)}
          >
            <Download className="h-3 w-3" />
            {t("reports.apiKeys.csv")}
          </Button>
        </div>
      </div>
      {byApiKey.length === 0 ? (
        <EmptyState icon={KeyRound} title={t("reports.apiKeys.empty")} />
      ) : (
        <div className="space-y-4">
          <div className="h-[200px]" data-testid="api-key-daily-chart">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartModel.points} margin={{ top: 5, right: 10, left: 10, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
                <XAxis
                  dataKey="displayDate"
                  tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
                  axisLine={false}
                  tickLine={false}
                  tickFormatter={metric === "cost" ? formatCurrency : formatCompact}
                />
                <Tooltip
                  content={
                    <ChartTooltip
                      names={seriesNames}
                      formatValue={metric === "cost" ? formatCurrency : formatCompact}
                    />
                  }
                />
                {chartModel.series.map((item) => (
                  <Area
                    key={item.id}
                    type="monotone"
                    dataKey={item.id}
                    name={seriesNames[item.id]}
                    stackId="api-keys"
                    stroke={item.color}
                    fill={item.color}
                    fillOpacity={0.35}
                    strokeWidth={1.5}
                    dot={false}
                  />
                ))}
              </AreaChart>
            </ResponsiveContainer>
          </div>
          <div className="flex flex-wrap gap-2 text-[11px] text-muted-foreground">
            {chartModel.series.map((item) => (
              <span key={item.id} className="inline-flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-sm" style={{ background: item.color }} />
                {seriesNames[item.id]}
              </span>
            ))}
          </div>
          <div className="max-h-[17.5rem] overflow-x-auto overflow-y-auto">
            <table className="w-full min-w-[860px] table-fixed text-xs">
              <thead className="sticky top-0 z-10 bg-card">
                <tr className="border-b text-left text-muted-foreground">
                  <SortableHeader
                    align="left"
                    label={t("reports.apiKeys.columns.key")}
                    isActive={sort.key === "name"}
                    direction={sort.direction}
                    onClick={() => toggleSort("name")}
                  />
                  <SortableHeader
                    label={t("reports.apiKeys.columns.requests")}
                    isActive={sort.key === "requests"}
                    direction={sort.direction}
                    onClick={() => toggleSort("requests")}
                  />
                  <SortableHeader
                    label={t("reports.apiKeys.columns.cost")}
                    isActive={sort.key === "costUsd"}
                    direction={sort.direction}
                    onClick={() => toggleSort("costUsd")}
                  />
                  <SortableHeader
                    label={t("reports.apiKeys.columns.tokens")}
                    isActive={sort.key === "tokens"}
                    direction={sort.direction}
                    onClick={() => toggleSort("tokens")}
                  />
                  <SortableHeader
                    label={t("reports.apiKeys.columns.avgDay")}
                    isActive={sort.key === "avgDayRequests"}
                    direction={sort.direction}
                    onClick={() => toggleSort("avgDayRequests")}
                  />
                  <SortableHeader
                    label={t("reports.apiKeys.columns.peakDay")}
                    isActive={sort.key === "peakDayRequests"}
                    direction={sort.direction}
                    onClick={() => toggleSort("peakDayRequests")}
                  />
                  <SortableHeader
                    label={t("reports.apiKeys.columns.burst")}
                    isActive={sort.key === "burstRatio"}
                    direction={sort.direction}
                    onClick={() => toggleSort("burstRatio")}
                  />
                </tr>
              </thead>
              <tbody>
                {rows.map((entry) => {
                  const pattern = burstPattern(entry.burstRatio);
                  const requestShare = totalRequests > 0 ? (entry.requests / totalRequests) * 100 : 0;
                  const rowId = apiKeySeriesId(entry.apiKeyId);
                  return (
                    <tr key={rowId} className="border-b border-border/60" data-testid={`api-key-row-${rowId}`}>
                      <td className="py-2 pr-4">
                        <div className="font-medium text-foreground">{formatApiKeyLabel(entry, t)}</div>
                      </td>
                      <td className="py-2 pr-4 text-right tabular-nums">
                        <div>{formatCompact(entry.requests)}</div>
                        <div className="text-[10px] text-muted-foreground">{requestShare.toFixed(1)}%</div>
                        <div className="mt-1 h-1 rounded-full bg-muted">
                          <div
                            className="h-1 rounded-full bg-foreground/70"
                            style={{ width: `${Math.min(requestShare, 100)}%` }}
                          />
                        </div>
                      </td>
                      <td className="py-2 pr-4 text-right tabular-nums">
                        <div>{formatCurrency(entry.costUsd)}</div>
                        <div className="text-[10px] text-muted-foreground">{entry.percentage.toFixed(1)}%</div>
                      </td>
                      <td className="py-2 pr-4 text-right tabular-nums">{formatCompact(entry.tokens)}</td>
                      <td className="py-2 pr-4 text-right tabular-nums">{entry.avgDayRequests.toFixed(1)}</td>
                      <td className="py-2 pr-4 text-right tabular-nums">
                        {entry.peakDayDate
                          ? t("reports.apiKeys.peakValue", {
                              date: formatReportBucketDate(entry.peakDayDate, dateDisplayFormat),
                              count: formatCompact(entry.peakDayRequests),
                            })
                          : "—"}
                      </td>
                      <td className="py-2 text-right">
                        <span
                          className={cn(
                            "inline-flex items-center rounded-md px-1.5 py-0.5 text-[11px] font-medium",
                            BURST_STYLES[pattern],
                          )}
                          data-testid={`api-key-pattern-${rowId}`}
                        >
                          {t("reports.apiKeys.ratio", { ratio: entry.burstRatio.toFixed(1) })}{" "}
                          {t(`reports.apiKeys.pattern.${pattern}`)}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function formatApiKeyLabel(entry: ApiKeyCostEntry, t: TFunction): string {
  if (entry.apiKeyId === null) {
    return t("reports.apiKeys.noKey");
  }
  if (!entry.name) {
    return t("reports.apiKeys.deleted");
  }
  return entry.keyPrefix ? `${entry.name} · ${entry.keyPrefix}` : entry.name;
}

function formatCompact(value: number): string {
  if (value >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(1)}B`;
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(0)}K`;
  if (Number.isInteger(value)) return String(value);
  return value.toFixed(2);
}

function sortApiKeyRows(
  rows: ApiKeyCostEntry[],
  sort: { key: SortKey; direction: SortDirection },
): ApiKeyCostEntry[] {
  const sorted = [...rows].sort((left, right) => {
    const leftValue = sort.key === "name" ? left.name ?? left.apiKeyId ?? "" : left[sort.key];
    const rightValue = sort.key === "name" ? right.name ?? right.apiKeyId ?? "" : right[sort.key];
    if (leftValue == null && rightValue == null) {
      return 0;
    }
    if (leftValue == null) {
      return 1;
    }
    if (rightValue == null) {
      return -1;
    }
    if (leftValue < rightValue) {
      return sort.direction === "asc" ? -1 : 1;
    }
    if (leftValue > rightValue) {
      return sort.direction === "asc" ? 1 : -1;
    }
    return 0;
  });
  return sorted;
}

function SortableHeader({
  label,
  isActive,
  direction,
  onClick,
  align = "right",
}: {
  label: string;
  isActive: boolean;
  direction: SortDirection;
  onClick: () => void;
  align?: "left" | "right";
}) {
  const Icon = !isActive ? ArrowUpDown : direction === "asc" ? ArrowUp : ArrowDown;
  return (
    <th className={`pb-2 font-medium ${align === "left" ? "pr-4 text-left" : "pr-4 text-right"}`}>
      <button
        type="button"
        className={`flex w-full items-center gap-1 font-medium text-inherit ${
          align === "left" ? "justify-start text-left" : "justify-end text-right"
        }`}
        onClick={onClick}
      >
        <span>{label}</span>
        <Icon aria-hidden="true" className={`h-3 w-3 shrink-0 ${isActive ? "text-foreground" : "text-muted-foreground/60"}`} />
      </button>
    </th>
  );
}

function exportApiKeyCsv(rows: ApiKeyCostEntry[], t: TFunction) {
  const headers = [
    t("reports.apiKeys.columns.key"),
    t("reports.apiKeys.columns.requests"),
    t("reports.apiKeys.columns.cost"),
    t("reports.apiKeys.columns.tokens"),
    t("reports.apiKeys.columns.avgDay"),
    t("reports.apiKeys.columns.peakDay"),
    t("reports.apiKeys.columns.burst"),
  ];
  const lines = rows.map((entry) =>
    [
      csvCell(formatApiKeyLabel(entry, t)),
      entry.requests,
      entry.costUsd.toFixed(4),
      entry.tokens,
      entry.avgDayRequests.toFixed(2),
      entry.peakDayDate ? `${entry.peakDayDate} ${entry.peakDayRequests}` : "",
      entry.burstRatio.toFixed(2),
    ].join(","),
  );
  const csv = [headers.join(","), ...lines].join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "reports-api-keys.csv";
  link.click();
  URL.revokeObjectURL(url);
}

function csvCell(value: string): string {
  if (/[",\n]/.test(value)) {
    return `"${value.replaceAll('"', '""')}"`;
  }
  return value;
}
