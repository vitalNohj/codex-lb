// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { Activity, AlertTriangle, Coins, DollarSign, Flame } from "lucide-react";
import { describe, expect, it } from "vitest";

import { StatsGrid } from "@/features/dashboard/components/stats-grid";
import { DEFAULT_DASHBOARD_LAYOUT } from "@/features/dashboard/layout";
import { buildDashboardView } from "@/features/dashboard/utils";
import { createDashboardOverview, createDefaultRequestLogs } from "@/test/mocks/factories";

const EMPTY_TREND: { value: number }[] = [];
const SAMPLE_TREND = [{ value: 1 }, { value: 2 }, { value: 3 }];

describe("StatsGrid", () => {
  it("renders metric cards with values", () => {
    render(
      <StatsGrid
        stats={[
          { label: "Requests (30d)", value: "228", comparison: { text: "▲ 50%", tone: "positive" }, icon: Activity, trend: SAMPLE_TREND, trendColor: "#3b82f6" },
          { label: "Tokens (30d)", value: "45K", comparison: { text: "▼ 50%", tone: "negative" }, icon: Coins, trend: SAMPLE_TREND, trendColor: "#8b5cf6" },
          { label: "Cost (30d)", value: "$1.82", meta: "Avg/day $0.06", icon: DollarSign, trend: SAMPLE_TREND, trendColor: "#10b981" },
          { label: "Account burn projection (5h/7d)", value: "0.7 / 0.8", meta: "Projected account-equivalents: 0.7/5h · 0.8/7d", icon: Flame, trend: SAMPLE_TREND, trendColor: "#ef4444" },
          { label: "Error rate (30d)", value: "2.8%", meta: "Top: rate_limit_exceeded", icon: AlertTriangle, trend: SAMPLE_TREND, trendColor: "#f59e0b" },
        ]}
      />,
    );

    expect(screen.getByText("Requests (30d)")).toBeInTheDocument();
    expect(screen.getByText("228")).toBeInTheDocument();
    expect(screen.getByText("▲ 50%")).toBeInTheDocument();
    expect(screen.getByText("Tokens (30d)")).toBeInTheDocument();
    expect(screen.getByText("45K")).toBeInTheDocument();
    expect(screen.getByText("▼ 50%")).toBeInTheDocument();
    expect(screen.getByText("Cost (30d)")).toBeInTheDocument();
    expect(screen.getByText("Avg/day $0.06")).toBeInTheDocument();
    expect(screen.getByText("Account burn projection (5h/7d)")).toBeInTheDocument();
    expect(screen.getByText("Projected account-equivalents: 0.7/5h · 0.8/7d")).toBeInTheDocument();
    expect(screen.getByText("Error rate (30d)")).toBeInTheDocument();
    expect(screen.getByText("Top: rate_limit_exceeded")).toBeInTheDocument();
  });

  it("renders the comparison indicator inline with the metric value", () => {
    render(
      <StatsGrid
        stats={[
          { label: "Requests (30d)", value: "228", comparison: { text: "▲ 50%", tone: "positive" }, icon: Activity, trend: SAMPLE_TREND, trendColor: "#3b82f6" },
        ]}
      />,
    );

    const valueRow = screen.getByTestId("stat-value-row");
    expect(valueRow).toContainElement(screen.getByText("228"));
    expect(valueRow).toContainElement(screen.getByText("▲ 50%"));
  });

  it("does not render a comparison line when a stat has no comparison", () => {
    render(
      <StatsGrid
        stats={[
          { label: "Requests (30d)", value: "228", icon: Activity, trend: SAMPLE_TREND, trendColor: "#3b82f6" },
        ]}
      />,
    );

    expect(screen.queryByText("▲ 50%")).not.toBeInTheDocument();
  });

  it("renders without sparklines when trend is empty", () => {
    render(
      <StatsGrid
        stats={[
          { label: "Empty", value: "0", icon: Activity, trend: EMPTY_TREND, trendColor: "#3b82f6" },
        ]}
      />,
    );

    expect(screen.getByText("Empty")).toBeInTheDocument();
  });

  it("renders nothing when every card is hidden", () => {
    const { container } = render(<StatsGrid stats={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders the active conversations card only when the layout includes it", () => {
    const overview = createDashboardOverview({
      summary: {
        primaryWindow: {
          remainingPercent: 80,
          capacityCredits: 100,
          remainingCredits: 80,
          resetAt: null,
          windowMinutes: 300,
        },
        secondaryWindow: null,
        cost: { currency: "USD", totalUsd: 12.5 },
        metrics: {
          requests: 500,
          tokens: 2000,
          cachedInputTokens: 300,
          errorRate: 0.02,
          errorCount: 10,
          topError: null,
          conversations: 4,
          conversationRequests: 10,
        },
      },
    });

    const hidden = buildDashboardView(overview, createDefaultRequestLogs(), {
      dashboardLayout: DEFAULT_DASHBOARD_LAYOUT,
    });
    const { unmount } = render(<StatsGrid stats={hidden.stats} />);
    expect(screen.queryByTestId("dashboard-stat-conversations")).not.toBeInTheDocument();
    expect(screen.getByTestId("dashboard-stat-requests")).toBeInTheDocument();
    expect(screen.getByTestId("stats-grid").childElementCount).toBe(hidden.stats.length);
    unmount();

    const shown = buildDashboardView(overview, createDefaultRequestLogs(), {
      dashboardLayout: { ...DEFAULT_DASHBOARD_LAYOUT, conversations: true },
    });
    render(<StatsGrid stats={shown.stats} />);
    expect(screen.getByTestId("dashboard-stat-conversations")).toHaveTextContent("4");
    expect(screen.getByTestId("stats-grid").childElementCount).toBe(shown.stats.length);
  });
});
