import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import * as SidecarIntegrationCard from "@/features/settings/components/sidecar-integration-card";
import type { ClaudeSidecarRoutingAccount } from "@/features/settings/schemas";

function account(priority: number): ClaudeSidecarRoutingAccount {
  return {
    name: "claude-a@example.com.json",
    email: "a@example.com",
    priority,
    paused: false,
    excludedModels: [],
    excludedModelsState: "available",
  };
}

function routing(priority: number, onPriorityChange: (name: string, priority: number) => void) {
  return (
    <SidecarIntegrationCard.Routing
      strategy="fill_first"
      accounts={[account(priority)]}
      busy={false}
      onStrategyChange={vi.fn()}
      onPriorityChange={onPriorityChange}
      onPausedChange={vi.fn()}
      onExcludedModelsChange={vi.fn()}
    />
  );
}

describe("SidecarIntegrationCard.Routing priority input", () => {
  it("commits an edited priority once and does not re-send an unchanged blur", async () => {
    const user = userEvent.setup();
    const onPriorityChange = vi.fn();
    render(routing(5, onPriorityChange));

    const input = screen.getByLabelText("Priority for a@example.com");
    await user.clear(input);
    await user.type(input, "7");
    await user.tab();
    expect(onPriorityChange).toHaveBeenCalledTimes(1);
    expect(onPriorityChange).toHaveBeenLastCalledWith("claude-a@example.com.json", 7);

    await user.click(input);
    await user.tab();
    expect(onPriorityChange).toHaveBeenCalledTimes(1);
  });

  it("restores the last committed value when the draft is not a valid priority", async () => {
    const user = userEvent.setup();
    const onPriorityChange = vi.fn();
    render(routing(5, onPriorityChange));

    const input = screen.getByLabelText("Priority for a@example.com");
    await user.clear(input);
    await user.tab();

    expect(input).toHaveValue(5);
    expect(onPriorityChange).not.toHaveBeenCalled();
  });

  it("replaces the draft when the server priority changes and treats it as committed", async () => {
    const user = userEvent.setup();
    const onPriorityChange = vi.fn();
    const { rerender } = render(routing(5, onPriorityChange));

    const input = screen.getByLabelText("Priority for a@example.com");
    await user.clear(input);
    await user.type(input, "42");

    rerender(routing(9, onPriorityChange));
    expect(input).toHaveValue(9);

    // The server value is now the committed one, so blurring it is a no-op.
    await user.click(input);
    await user.tab();
    expect(onPriorityChange).not.toHaveBeenCalled();
  });
});
