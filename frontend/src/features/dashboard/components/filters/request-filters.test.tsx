import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { RequestFilters } from "./request-filters";

const BASE_PROPS = {
  filters: {
    search: "",
    timeframe: "all" as const,
    accountIds: [],
    apiKeyIds: [],
    modelOptions: [],
    statuses: [],
    limit: 25,
    offset: 0,
  },
  accountOptions: [],
  apiKeyOptions: [],
  modelOptions: [],
  statusOptions: [],
  onSearchChange: vi.fn(),
  onTimeframeChange: vi.fn(),
  onAccountChange: vi.fn(),
  onApiKeyChange: vi.fn(),
  onModelChange: vi.fn(),
  onStatusChange: vi.fn(),
  onReset: vi.fn(),
};

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
