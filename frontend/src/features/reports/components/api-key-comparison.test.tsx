import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ApiKeyCostEntry } from "../schemas";
import { ApiKeyComparison } from "./api-key-comparison";

vi.mock("@/components/lazy-recharts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/components/lazy-recharts")>();
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: ReactNode }) => (
      <div data-testid="api-key-chart-container">{children}</div>
    ),
    AreaChart: ({ children }: { children: ReactNode }) => <div>{children}</div>,
    Area: ({ name }: { name?: string }) => <div data-testid={`api-key-area-${String(name)}`} />,
    CartesianGrid: () => null,
    XAxis: () => null,
    YAxis: () => null,
    Tooltip: () => null,
  };
});

function keyEntry(overrides: Partial<ApiKeyCostEntry> & Pick<ApiKeyCostEntry, "apiKeyId">): ApiKeyCostEntry {
  return {
    name: "Key",
    keyPrefix: "sk-x",
    costUsd: 1,
    requests: 10,
    tokens: 100,
    percentage: 50,
    avgDayRequests: 10,
    peakDayDate: "2026-06-01",
    peakDayRequests: 10,
    peakDayCostUsd: 1,
    burstRatio: 1,
    ...overrides,
  };
}

describe("ApiKeyComparison", () => {
  it("labels bursty, uneven, steady, missing, and deleted keys", async () => {
    render(
      <ApiKeyComparison
        startDate="2026-06-01"
        endDate="2026-06-07"
        byApiKey={[
          keyEntry({
            apiKeyId: "batch",
            name: "Batch job",
            keyPrefix: "sk-batch",
            burstRatio: 4,
            requests: 70,
            avgDayRequests: 10,
            peakDayRequests: 70,
          }),
          keyEntry({
            apiKeyId: "mixed",
            name: "Mixed",
            keyPrefix: "sk-mix",
            burstRatio: 2,
            requests: 20,
          }),
          keyEntry({
            apiKeyId: "agent",
            name: "Agent",
            keyPrefix: "sk-agent",
            burstRatio: 1,
            requests: 70,
          }),
          keyEntry({ apiKeyId: null, name: null, keyPrefix: null, burstRatio: 1, requests: 3 }),
          keyEntry({ apiKeyId: "gone", name: null, keyPrefix: null, burstRatio: 1, requests: 2 }),
        ]}
        dailyByApiKey={[]}
      />,
    );

    expect(await screen.findByText("API keys")).toBeInTheDocument();
    expect(screen.getByTestId("api-key-pattern-batch")).toHaveTextContent("Burst");
    expect(screen.getByTestId("api-key-pattern-mixed")).toHaveTextContent("Uneven");
    expect(screen.getByTestId("api-key-pattern-agent")).toHaveTextContent("Steady");
    expect(screen.getByTestId("api-key-row-__none__")).toHaveTextContent("No API key");
    expect(screen.getByTestId("api-key-row-gone")).toHaveTextContent("Deleted key");
  });
});
