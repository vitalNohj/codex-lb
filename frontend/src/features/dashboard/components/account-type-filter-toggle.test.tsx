import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AccountTypeFilterToggle } from "./account-type-filter-toggle";

describe("AccountTypeFilterToggle", () => {
  it("reflects enabled state via aria-pressed", () => {
    render(
      <AccountTypeFilterToggle
        value={{ codex: true, cliproxy: false, openrouter: true, omniroute: false }}
        onToggle={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Hide Codex accounts" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "Show CLIProxy accounts" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(screen.getByRole("button", { name: "Hide OpenRouter accounts" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "Show Omniroute accounts" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("calls onToggle with the account type key when clicked", async () => {
    const user = userEvent.setup();
    const onToggle = vi.fn();
    render(
      <AccountTypeFilterToggle
        value={{ codex: true, cliproxy: true, openrouter: true, omniroute: true }}
        onToggle={onToggle}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Hide OpenRouter accounts" }));

    expect(onToggle).toHaveBeenCalledWith("openrouter");
  });
});
