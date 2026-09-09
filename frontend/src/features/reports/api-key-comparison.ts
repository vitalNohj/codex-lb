import type { ApiKeyCostEntry, ApiKeyDailyRow } from "./schemas";

export const API_KEY_NONE_SERIES_ID = "__none__";
export const API_KEY_OTHER_SERIES_ID = "__other__";
export const API_KEY_CHART_TOP_N = 8;

export const API_KEY_SERIES_COLORS = [
  "#3b82f6",
  "#10b981",
  "#f59e0b",
  "#ec4899",
  "#8b5cf6",
  "#06b6d4",
  "#f97316",
  "#14b8a6",
] as const;

export const API_KEY_NONE_COLOR = "#9ca3af";
export const API_KEY_OTHER_COLOR = "#64748b";

export type BurstPattern = "steady" | "uneven" | "burst";

export function burstPattern(ratio: number): BurstPattern {
  if (ratio >= 3) {
    return "burst";
  }
  if (ratio >= 1.5) {
    return "uneven";
  }
  return "steady";
}

export function apiKeySeriesId(apiKeyId: string | null): string {
  return apiKeyId ?? API_KEY_NONE_SERIES_ID;
}

export function rankApiKeyChartEntries(
  byApiKey: ApiKeyCostEntry[],
  metric: "cost" | "req",
): { top: ApiKeyCostEntry[]; hasOther: boolean } {
  const ranked = [...byApiKey].sort((left, right) => metricValue(right, metric) - metricValue(left, metric));
  return {
    top: ranked.slice(0, API_KEY_CHART_TOP_N),
    hasOther: ranked.length > API_KEY_CHART_TOP_N,
  };
}

export type ApiKeyChartSeries = {
  id: string;
  color: string;
  apiKeyId: string | null;
  isOther: boolean;
};

export type ApiKeyChartPoint = {
  date: string;
  displayDate: string;
} & Record<string, number | string>;

export function buildApiKeyChartModel(
  startDate: string,
  endDate: string,
  byApiKey: ApiKeyCostEntry[],
  dailyByApiKey: ApiKeyDailyRow[],
  metric: "cost" | "req",
): { series: ApiKeyChartSeries[]; points: ApiKeyChartPoint[] } {
  const { top, hasOther } = rankApiKeyChartEntries(byApiKey, metric);
  const topIds = new Set(top.map((entry) => apiKeySeriesId(entry.apiKeyId)));
  const series: ApiKeyChartSeries[] = top.map((entry, index) => {
    const id = apiKeySeriesId(entry.apiKeyId);
    return {
      id,
      apiKeyId: entry.apiKeyId,
      isOther: false,
      color: entry.apiKeyId === null ? API_KEY_NONE_COLOR : API_KEY_SERIES_COLORS[index % API_KEY_SERIES_COLORS.length],
    };
  });
  if (hasOther) {
    series.push({
      id: API_KEY_OTHER_SERIES_ID,
      apiKeyId: null,
      isOther: true,
      color: API_KEY_OTHER_COLOR,
    });
  }

  const dates = eachIsoDate(startDate, endDate);
  const valuesByDate = new Map<string, Record<string, number>>();
  for (const date of dates) {
    const zeros: Record<string, number> = {};
    for (const item of series) {
      zeros[item.id] = 0;
    }
    valuesByDate.set(date, zeros);
  }

  for (const row of dailyByApiKey) {
    const dayValues = valuesByDate.get(row.date);
    if (!dayValues) {
      continue;
    }
    const seriesId = apiKeySeriesId(row.apiKeyId);
    const bucketId = topIds.has(seriesId) ? seriesId : hasOther ? API_KEY_OTHER_SERIES_ID : seriesId;
    if (!(bucketId in dayValues)) {
      continue;
    }
    dayValues[bucketId] = (dayValues[bucketId] ?? 0) + (metric === "cost" ? row.costUsd : row.requests);
  }

  const points: ApiKeyChartPoint[] = dates.map((date) => ({
    date,
    displayDate: date.slice(5),
    ...valuesByDate.get(date),
  }));

  return { series, points };
}

function metricValue(entry: ApiKeyCostEntry, metric: "cost" | "req"): number {
  return metric === "cost" ? entry.costUsd : entry.requests;
}

function eachIsoDate(startDate: string, endDate: string): string[] {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(startDate) || !/^\d{4}-\d{2}-\d{2}$/.test(endDate) || startDate > endDate) {
    return [];
  }

  const dates: string[] = [];
  for (let current = startDate; current <= endDate; ) {
    dates.push(current);
    const nextDate = new Date(`${current}T00:00:00Z`);
    nextDate.setUTCDate(nextDate.getUTCDate() + 1);
    current = nextDate.toISOString().slice(0, 10);
  }
  return dates;
}
