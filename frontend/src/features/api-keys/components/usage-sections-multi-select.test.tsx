import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/utils";

import { UsageSectionsMultiSelect } from "./usage-sections-multi-select";

describe("UsageSectionsMultiSelect", () => {
  it("renders an explicitly empty selection with no checked sections", async () => {
    const user = userEvent.setup();

    renderWithProviders(<UsageSectionsMultiSelect value="" onChange={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: /None/i }));

    expect(screen.getByRole("menuitemcheckbox", { name: "Upstream limits" })).not.toBeChecked();
    expect(screen.getByRole("menuitemcheckbox", { name: "Account pool usage" })).not.toBeChecked();
    expect(screen.getByRole("menuitemcheckbox", { name: "Reset credits" })).not.toBeChecked();
  });

  it("lists reset credits unchecked for the default sections", async () => {
    const user = userEvent.setup();

    renderWithProviders(
      <UsageSectionsMultiSelect value="upstream_limits,account_pool_usage" onChange={vi.fn()} />,
    );

    await user.click(screen.getByRole("button", { name: "Upstream limits, Account pool usage" }));

    expect(screen.getByRole("menuitemcheckbox", { name: "Upstream limits" })).toBeChecked();
    expect(screen.getByRole("menuitemcheckbox", { name: "Account pool usage" })).toBeChecked();
    expect(screen.getByRole("menuitemcheckbox", { name: "Reset credits" })).not.toBeChecked();
  });

  it("adds reset credits to the selected sections", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();

    renderWithProviders(
      <UsageSectionsMultiSelect value="upstream_limits,account_pool_usage" onChange={onChange} />,
    );

    await user.click(screen.getByRole("button", { name: "Upstream limits, Account pool usage" }));
    await user.click(screen.getByRole("menuitemcheckbox", { name: "Reset credits" }));

    expect(onChange).toHaveBeenCalledWith("upstream_limits,account_pool_usage,reset_credits");
  });

  it("labels every section selected as all sections", () => {
    renderWithProviders(
      <UsageSectionsMultiSelect value="upstream_limits,account_pool_usage,reset_credits" onChange={vi.fn()} />,
    );

    expect(screen.getByRole("button", { name: "All sections" })).toBeInTheDocument();
  });
});
