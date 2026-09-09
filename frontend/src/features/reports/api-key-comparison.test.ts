import { describe, expect, it } from "vitest";

import {
  API_KEY_CHART_TOP_N,
  API_KEY_NONE_SERIES_ID,
  API_KEY_OTHER_SERIES_ID,
  apiKeySeriesId,
  buildApiKeyChartModel,
  burstPattern,
  rankApiKeyChartEntries,
} from "./api-key-comparison";
import type { ApiKeyCostEntry, ApiKeyDailyRow } from "./schemas";

function keyEntry(overrides: Partial<ApiKeyCostEntry> & Pick<ApiKeyCostEntry, "apiKeyId">): ApiKeyCostEntry {
  return {
    name: "Key",
    keyPrefix: "sk-x",
    costUsd: 1,
    requests: 10,
    tokens: 100,
    percentage: 10,
    avgDayRequests: 10,
    peakDayDate: "2026-06-01",
    peakDayRequests: 10,
    peakDayCostUsd: 1,
    burstRatio: 1,
    ...overrides,
  };
}

describe("burstPattern", () => {
  it("maps the fixed burst thresholds", () => {
    expect(burstPattern(1)).toBe("steady");
    expect(burstPattern(1.49)).toBe("steady");
    expect(burstPattern(1.5)).toBe("uneven");
    expect(burstPattern(2.99)).toBe("uneven");
    expect(burstPattern(3)).toBe("burst");
    expect(burstPattern(4)).toBe("burst");
  });
});

describe("rankApiKeyChartEntries", () => {
  it("keeps the top eight keys and flags Other for the remainder", () => {
    const byApiKey = Array.from({ length: 9 }, (_, index) =>
      keyEntry({
        apiKeyId: `key-${index}`,
        name: `Key ${index}`,
        requests: 9 - index,
        costUsd: index,
      }),
    );

    const ranked = rankApiKeyChartEntries(byApiKey, "req");

    expect(API_KEY_CHART_TOP_N).toBe(8);
    expect(ranked.top.map((entry) => entry.apiKeyId)).toEqual([
      "key-0",
      "key-1",
      "key-2",
      "key-3",
      "key-4",
      "key-5",
      "key-6",
      "key-7",
    ]);
    expect(ranked.hasOther).toBe(true);
  });
});

describe("buildApiKeyChartModel", () => {
  it("zero-fills the selected days and folds overflow keys into Other", () => {
    const byApiKey = [
      ...Array.from({ length: 8 }, (_, index) =>
        keyEntry({
          apiKeyId: `key-${index}`,
          name: `Key ${index}`,
          requests: 20,
        }),
      ),
      keyEntry({ apiKeyId: "overflow", name: "Overflow", requests: 5 }),
      keyEntry({ apiKeyId: null, name: null, keyPrefix: null, requests: 3 }),
    ];
    const dailyByApiKey: ApiKeyDailyRow[] = [
      { date: "2026-06-01", apiKeyId: "key-0", requests: 4, costUsd: 0.4 },
      { date: "2026-06-02", apiKeyId: "overflow", requests: 5, costUsd: 0.5 },
      { date: "2026-06-02", apiKeyId: null, requests: 3, costUsd: 0.1 },
    ];

    const model = buildApiKeyChartModel(
      "2026-06-01",
      "2026-06-02",
      byApiKey,
      dailyByApiKey,
      "req",
    );

    expect(model.series.map((item) => item.id)).toEqual([
      "key-0",
      "key-1",
      "key-2",
      "key-3",
      "key-4",
      "key-5",
      "key-6",
      "key-7",
      API_KEY_OTHER_SERIES_ID,
    ]);
    expect(model.points).toHaveLength(2);
    expect(model.points[0]?.["key-0"]).toBe(4);
    expect(model.points[0]?.[API_KEY_OTHER_SERIES_ID]).toBe(0);
    expect(model.points[1]?.[API_KEY_OTHER_SERIES_ID]).toBe(8);
    expect(apiKeySeriesId(null)).toBe(API_KEY_NONE_SERIES_ID);
  });
});
