import { cloneElement, type ReactElement, type ReactNode } from "react";
import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MonthlyUsageChart } from "./monthly-usage-chart";
import type { MonthlyUsageEntry } from "../schemas";

type ChartProps = { children: ReactNode; margin?: unknown; data?: unknown };

let capturedProps: ChartProps | null = null;
let capturedBars: Array<{ dataKey?: string; fill?: string; radius?: unknown }> = [];

function findTooltipContent(node: ReactNode): ReactElement | null {
  if (!node || typeof node !== "object") return null;
  if (Array.isArray(node)) {
    for (const child of node) {
      const found = findTooltipContent(child);
      if (found) return found;
    }
    return null;
  }

  const element = node as ReactElement<{ content?: ReactElement; children?: ReactNode }>;
  if (element.props.content) return element.props.content;
  return findTooltipContent(element.props.children);
}

vi.mock("@/components/lazy-recharts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/components/lazy-recharts")>();

  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: ReactNode }) => <div>{children}</div>,
    BarChart: (props: { children: ReactNode; margin?: unknown; data?: unknown }) => {
      capturedProps = props;
      return <div data-testid="monthly-bar-chart">{props.children}</div>;
    },
    Bar: (props: { dataKey?: string; fill?: string; radius?: unknown }) => {
      capturedBars.push(props);
      return null;
    },
    XAxis: () => null,
    YAxis: () => null,
    CartesianGrid: () => null,
    Tooltip: () => null,
  };
});

const DATA: MonthlyUsageEntry[] = [
  {
    month: "2026-06",
    requests: 12,
    inputTokens: 100,
    outputTokens: 40,
    cachedInputTokens: 10,
    costUsd: 1.5,
    models: [
      { model: "gpt-5.1", costUsd: 1.0, requests: 8, percentage: 66.7 },
      { model: "gpt-5.2", costUsd: 0.5, requests: 4, percentage: 33.3 },
    ],
  },
  {
    month: "2026-07",
    requests: 7,
    inputTokens: 60,
    outputTokens: 20,
    cachedInputTokens: 5,
    costUsd: 0.9,
    models: [{ model: "gpt-5.1", costUsd: 0.9, requests: 7, percentage: 100 }],
  },
];

describe("MonthlyUsageChart", () => {
  beforeEach(() => {
    capturedProps = null;
    capturedBars = [];
  });

  it("stacks one bar per model, ordered by lifetime model cost", () => {
    render(<MonthlyUsageChart data={DATA} />);

    expect(capturedBars.map((bar) => bar.dataKey)).toEqual(["gpt-5.1", "gpt-5.2"]);
    expect(capturedBars.map((bar) => bar.fill)).toEqual(["#3b82f6", "#10b981"]);
    expect((capturedProps?.data as Array<{ month: string }>).map((row) => row.month)).toEqual([
      "2026-06",
      "2026-07",
    ]);
  });

  it("reuses one bar for a model that spans several months", () => {
    render(<MonthlyUsageChart data={DATA} />);

    expect(capturedBars).toHaveLength(2);
  });

  it("shows the month totals and the per-model cost split in the tooltip", () => {
    render(<MonthlyUsageChart data={DATA} />);

    const tooltip = findTooltipContent(capturedProps?.children);
    expect(tooltip).not.toBeNull();
    const { container: tooltipContainer } = render(
      cloneElement(tooltip!, {
        active: true,
        label: "2026-06",
        payload: [
          { dataKey: "gpt-5.1", value: 1.0, color: "#3b82f6" },
          { dataKey: "gpt-5.2", value: 0.5, color: "#10b981" },
        ],
      }),
    );

    expect(screen.getByText("June 2026")).toBeInTheDocument();
    expect(screen.getByText("Requests")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("Input tokens")).toBeInTheDocument();
    expect(screen.getByText("100")).toBeInTheDocument();
    expect(screen.getByText("Cached input tokens")).toBeInTheDocument();
    expect(screen.getByText("10")).toBeInTheDocument();
    expect(screen.getByText("Output tokens")).toBeInTheDocument();
    expect(screen.getByText("40")).toBeInTheDocument();
    expect(screen.getAllByText("Cost").length).toBeGreaterThan(0);
    expect(screen.getByText("$1.50")).toBeInTheDocument();
    expect(within(tooltipContainer).getByText("gpt-5.1")).toBeInTheDocument();
    expect(screen.getByText("$1.00")).toBeInTheDocument();
    expect(within(tooltipContainer).getByText("gpt-5.2")).toBeInTheDocument();
    expect(screen.getByText("$0.50")).toBeInTheDocument();
  });

  it("shows no-data instead of a chart when monthly entries are absent", () => {
    render(<MonthlyUsageChart data={[]} />);

    expect(screen.getByText("No data")).toBeInTheDocument();
    expect(screen.getByText("No usage recorded for the selected range.")).toBeInTheDocument();
    expect(capturedProps).toBeNull();
    expect(screen.queryByTestId("monthly-bar-chart")).not.toBeInTheDocument();
  });

  it("lists every model in a legend, in lifetime-cost order", () => {
    render(<MonthlyUsageChart data={DATA} />);

    const legend = screen.getByRole("list");
    expect(legend.textContent).toBe("gpt-5.1gpt-5.2");
  });

  it("rounds only the top segment of each stacked bar", () => {
    render(<MonthlyUsageChart data={DATA} />);

    expect(capturedBars.map((bar) => bar.radius)).toEqual([undefined, [4, 4, 0, 0]]);
  });

  it("orders tooltip models by that month's cost and hides models with no cost", () => {
    render(<MonthlyUsageChart data={DATA} />);

    const tooltip = findTooltipContent(capturedProps?.children);
    const { container } = render(
      cloneElement(tooltip!, {
        active: true,
        label: "2026-07",
        payload: [
          { dataKey: "gpt-5.2", value: 0, color: "#10b981" },
          { dataKey: "gpt-5.1", value: 0.9, color: "#3b82f6" },
        ],
      }),
    );

    expect(screen.getByText("July 2026")).toBeInTheDocument();
    expect(container.textContent).not.toContain("gpt-5.2");
    expect(container.textContent).toContain("gpt-5.1");
  });

  it("renders a single month as one stacked bar", () => {
    render(<MonthlyUsageChart data={[DATA[0]]} />);

    expect((capturedProps?.data as unknown[]).length).toBe(1);
    expect(capturedBars).toHaveLength(2);
  });
});
