import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiKeyTable } from "@/features/api-keys/components/api-key-table";
import { createApiKey, createDefaultApiKeys } from "@/test/mocks/factories";
import { renderWithProviders } from "@/test/utils";

describe("ApiKeyTable", () => {
  it("renders the empty state when no keys are provided", () => {
    renderWithProviders(
      <ApiKeyTable
        keys={[]}
        busy={false}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
        onRegenerate={vi.fn()}
      />,
    );

    expect(screen.getByText("No API keys created yet")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("renders one row per key with prefix, status, and limit/usage summaries", () => {
    const keys = createDefaultApiKeys();
    renderWithProviders(
      <ApiKeyTable
        keys={keys}
        busy={false}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
        onRegenerate={vi.fn()}
      />,
    );

    const rows = screen.getAllByRole("row");
    expect(rows).toHaveLength(keys.length + 1);

    const firstRow = rows[1];
    expect(within(firstRow).getByText(keys[0].name)).toBeInTheDocument();
    expect(within(firstRow).getByText(keys[0].keyPrefix)).toBeInTheDocument();
    expect(within(firstRow).getByText("Active")).toBeInTheDocument();

    const secondRow = rows[2];
    expect(within(secondRow).getByText("Disabled")).toBeInTheDocument();
    expect(within(secondRow).getByText("No Limit")).toBeInTheDocument();
  });

  it("marks a one-time budget in the limit summary so it does not read as periodic", () => {
    const keys = [
      createApiKey({
        id: "budget-key",
        name: "Budget key",
        limits: [
          {
            id: 7,
            limitType: "cost_usd",
            limitWindow: "lifetime",
            maxValue: 5_000_000,
            currentValue: 1_250_000,
            modelFilter: null,
            resetAt: null,
          },
        ],
      }),
    ];
    renderWithProviders(
      <ApiKeyTable
        keys={keys}
        busy={false}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
        onRegenerate={vi.fn()}
      />,
    );

    const row = screen.getAllByRole("row")[1];
    expect(within(row).getByText("Cost: $1.25/$5.00 one-time")).toBeInTheDocument();
  });

  it("names every model that shares a limit in the summary", () => {
    const keys = [
      createApiKey({
        id: "shared-models",
        name: "Shared models",
        limits: [
          {
            id: 8,
            limitType: "cost_usd",
            limitWindow: "weekly",
            maxValue: 500_000_000,
            currentValue: 0,
            modelFilter: null,
            modelFilters: ["gpt-5.1", "gpt-5.4"],
            resetAt: "2026-01-08T00:00:00Z",
          },
        ],
      }),
    ];
    renderWithProviders(
      <ApiKeyTable
        keys={keys}
        busy={false}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
        onRegenerate={vi.fn()}
      />,
    );

    const row = screen.getAllByRole("row")[1];
    expect(within(row).getByText("Cost: $0.00/$500.00 weekly gpt-5.1, gpt-5.4")).toBeInTheDocument();
  });

  it("badges shared keys only", () => {
    const keys = [
      createApiKey({ id: "shared-key", name: "Friend key", isShared: true }),
      createApiKey({ id: "own-key", name: "Own key", isShared: false }),
    ];
    renderWithProviders(
      <ApiKeyTable
        keys={keys}
        busy={false}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
        onRegenerate={vi.fn()}
      />,
    );

    const rows = screen.getAllByRole("row");
    expect(within(rows[1]).getByText("Shared")).toBeInTheDocument();
    expect(within(rows[2]).queryByText("Shared")).not.toBeInTheDocument();
  });

  it("renders traffic class labels in the traffic column", () => {
    const keys = [
      createApiKey({ id: "foreground-key", trafficClass: "foreground" }),
      createApiKey({
        id: "opportunistic-key",
        name: "Opportunistic key",
        trafficClass: "opportunistic",
      }),
    ];
    renderWithProviders(
      <ApiKeyTable
        keys={keys}
        busy={false}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
        onRegenerate={vi.fn()}
      />,
    );

    expect(screen.getByText("Foreground")).toBeInTheDocument();
    expect(screen.getByText("Opportunistic")).toBeInTheDocument();
  });

  it("renders 'All' when allowedModels is missing and the configured list otherwise", () => {
    const restricted = createApiKey({
      id: "key_restricted",
      allowedModels: ["gpt-5.1", "gpt-4o-mini"],
    });
    const unrestricted = createApiKey({
      id: "key_unrestricted",
      name: "Unrestricted key",
      keyPrefix: "sk-open",
      allowedModels: null,
    });

    renderWithProviders(
      <ApiKeyTable
        keys={[restricted, unrestricted]}
        busy={false}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
        onRegenerate={vi.fn()}
      />,
    );

    expect(screen.getByText("gpt-5.1, gpt-4o-mini")).toBeInTheDocument();
    expect(screen.getByText("All")).toBeInTheDocument();
  });

  it("invokes onEdit / onRegenerate / onDelete with the selected key from the row menu", async () => {
    const user = userEvent.setup();
    const onEdit = vi.fn();
    const onRegenerate = vi.fn();
    const onDelete = vi.fn();
    const target = createApiKey({ id: "key_target", name: "Target key" });

    renderWithProviders(
      <ApiKeyTable
        keys={[target]}
        busy={false}
        onEdit={onEdit}
        onDelete={onDelete}
        onRegenerate={onRegenerate}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Actions" }));
    await user.click(screen.getByRole("menuitem", { name: /edit/i }));
    expect(onEdit).toHaveBeenCalledWith(target);

    await user.click(screen.getByRole("button", { name: "Actions" }));
    await user.click(screen.getByRole("menuitem", { name: /regenerate/i }));
    expect(onRegenerate).toHaveBeenCalledWith(target);

    await user.click(screen.getByRole("button", { name: "Actions" }));
    await user.click(screen.getByRole("menuitem", { name: /delete/i }));
    expect(onDelete).toHaveBeenCalledWith(target);
  });

  it("disables the row action trigger when busy is true", () => {
    renderWithProviders(
      <ApiKeyTable
        keys={[createApiKey()]}
        busy={true}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
        onRegenerate={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Actions" })).toBeDisabled();
  });
});
