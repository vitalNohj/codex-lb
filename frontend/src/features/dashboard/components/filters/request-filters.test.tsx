import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { RequestFilters, type RequestFiltersProps } from "@/features/dashboard/components/filters/request-filters";
import type { FilterState } from "@/features/dashboard/schemas";

const EMPTY_OPTIONS: RequestFiltersProps["accountOptions"] = [];
const BASE_FILTERS: FilterState = {
  search: "",
  timeframe: "all",
  accountIds: [],
  apiKeyIds: [],
  modelOptions: [],
  statuses: [],
  conversationId: null,
  limit: 25,
  offset: 0,
};

const BASE_PROPS: RequestFiltersProps = {
  filters: BASE_FILTERS,
  accountOptions: EMPTY_OPTIONS,
  apiKeyOptions: EMPTY_OPTIONS,
  modelOptions: EMPTY_OPTIONS,
  statusOptions: EMPTY_OPTIONS,
  onSearchChange: vi.fn(),
  onTimeframeChange: vi.fn(),
  onAccountChange: vi.fn(),
  onApiKeyChange: vi.fn(),
  onModelChange: vi.fn(),
  onStatusChange: vi.fn(),
  onConversationDismiss: vi.fn(),
  onReset: vi.fn(),
};

function renderFilters(overrides: Partial<FilterState> = {}) {
  const filters = { ...BASE_FILTERS, ...overrides };
  const props: RequestFiltersProps = {
    ...BASE_PROPS,
    filters,
    onSearchChange: vi.fn(),
    onTimeframeChange: vi.fn(),
    onAccountChange: vi.fn(),
    onApiKeyChange: vi.fn(),
    onModelChange: vi.fn(),
    onStatusChange: vi.fn(),
    onConversationDismiss: vi.fn(),
    onReset: vi.fn(),
  };
  render(<RequestFilters {...props} />);
  return props;
}

describe("RequestFilters", () => {
  it("shows simplified as the selected request-log view mode", () => {
    render(
      <RequestFilters
        {...BASE_PROPS}
        viewMode="simplified"
        onViewModeChange={vi.fn()}
      />,
    );

    expect(screen.getByRole("radiogroup", { name: "Request log view mode" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Simplified" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.getByRole("radio", { name: "Expanded" })).toHaveAttribute(
      "aria-checked",
      "false",
    );
  });

  it("reports expanded mode selection", async () => {
    const user = userEvent.setup();
    const onViewModeChange = vi.fn();
    render(
      <RequestFilters
        {...BASE_PROPS}
        viewMode="simplified"
        onViewModeChange={onViewModeChange}
      />,
    );

    await user.click(screen.getByRole("radio", { name: "Expanded" }));

    expect(onViewModeChange).toHaveBeenCalledWith("expanded");
  });
});

describe("RequestFilters conversation badge", () => {
  it("renders no badge when conversationId is null", () => {
    renderFilters();
    expect(screen.queryByText(/conv/i)).not.toBeInTheDocument();
  });

  it("renders badge when conversationId is set", () => {
    renderFilters({ conversationId: "conv_badge_test" });
    expect(screen.getByText(/conv_badge_test/)).toBeInTheDocument();
  });

  it("places badge immediately after Statuses and before Reset button", () => {
    renderFilters({
      conversationId: "conv_ordering",
      statuses: ["ok"],
    });

    const badgeText = screen.getByText(/conv_ordering/);
    const badgeEl = badgeText.closest('[data-slot="badge"]');
    expect(badgeEl).not.toBeNull();

    const resetButton = screen.getByRole("button", { name: /reset/i });
    const filterRow = resetButton.closest(".flex.flex-wrap");
    expect(filterRow).not.toBeNull();

    const children = Array.from(filterRow?.children ?? []);
    const badgeIdx = children.findIndex((c) => c === badgeEl);
    const resetIdx = children.findIndex((c) => c === resetButton);

    expect(badgeIdx).not.toBe(-1);
    expect(badgeIdx).toBeLessThan(resetIdx);
    expect(badgeIdx).toBeGreaterThan(0);

    const filterTriggers = filterRow?.querySelectorAll("button[aria-haspopup=\"menu\"]");
    const lastTrigger = filterTriggers?.[filterTriggers.length - 1];
    expect(lastTrigger).toBeDefined();

    const statusIdx = children.findIndex((c) => c === lastTrigger);
    expect(statusIdx).toBeGreaterThan(-1);
    expect(statusIdx + 1).toBe(badgeIdx);
    expect(badgeIdx + 1).toBe(resetIdx);
  });

  it("dismiss button fires onConversationDismiss", () => {
    const props = renderFilters({ conversationId: "conv_dismiss_me" });

    const dismissButton = screen.getByRole("button", { name: /remove conversation/i });
    fireEvent.click(dismissButton);

    expect(props.onConversationDismiss).toHaveBeenCalled();
  });

  it("dismiss button does not fire onReset", () => {
    const props = renderFilters({ conversationId: "conv_dismiss_only" });

    const dismissButton = screen.getByRole("button", { name: /remove conversation/i });
    fireEvent.click(dismissButton);

    expect(props.onReset).not.toHaveBeenCalled();
  });

  it("Reset button fires onReset and includes conversation clearing", () => {
    const props = renderFilters({ conversationId: "conv_reset_me" });

    const resetButton = screen.getByRole("button", { name: /reset/i });
    fireEvent.click(resetButton);

    expect(props.onReset).toHaveBeenCalled();
  });

  it("shows full conversation ID as title for accessibility when visually truncated", () => {
    const longId = "conv_this_is_a_very_long_id_that_exceeds_display_width";
    renderFilters({ conversationId: longId });

    const badge = screen.getByText(/conv_this/);
    const span = badge.closest("span");
    expect(span).toHaveAttribute("title", longId);
    expect(span).toHaveClass("truncate");
  });
});
