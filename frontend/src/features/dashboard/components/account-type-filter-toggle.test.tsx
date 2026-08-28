import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AccountTypeFilterToggle } from "./account-type-filter-toggle";

describe("AccountTypeFilterToggle", () => {
  it("reflects enabled state via aria-pressed", () => {
    render(
      <AccountTypeFilterToggle
        value={{ codex: true, cliproxy: false, openrouter: true, omniroute: false, orcarouter: true }}
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
    expect(screen.getByRole("button", { name: "Hide OrcaRouter accounts" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("orders the filter buttons to match the sidecar provider order", () => {
    render(
      <AccountTypeFilterToggle
        value={{ codex: true, cliproxy: true, openrouter: true, orcarouter: true, omniroute: true }}
        onToggle={vi.fn()}
      />,
    );

    expect(screen.getAllByRole("button").map((button) => button.textContent?.trim())).toEqual([
      "Codex",
      "CLIProxy",
      "OpenRouter",
      "OrcaRouter",
      "Omniroute",
    ]);
  });

  it("calls onToggle with the account type key when clicked", async () => {
    const user = userEvent.setup();
    const onToggle = vi.fn();
    render(
      <AccountTypeFilterToggle
        value={{ codex: true, cliproxy: true, openrouter: true, omniroute: true, orcarouter: true }}
        onToggle={onToggle}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Hide OpenRouter accounts" }));

    expect(onToggle).toHaveBeenCalledWith("openrouter");

    await user.click(screen.getByRole("button", { name: "Hide OrcaRouter accounts" }));

    expect(onToggle).toHaveBeenCalledWith("orcarouter");
  });
});
