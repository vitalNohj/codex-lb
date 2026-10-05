import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";

import { AliasSettings } from "@/features/settings/components/alias-settings";
import { ALIAS_POOLS_HEALTH_POLL_MS } from "@/features/settings/hooks/use-alias-pools-health";
import type { DashboardSettings, SettingsUpdateRequest } from "@/features/settings/schemas";
import { ApiError } from "@/lib/api-client";
import { createDashboardSettings } from "@/test/mocks/factories";
import { server } from "@/test/mocks/server";
import { renderWithProviders } from "@/test/utils";

const ALIAS = "pooled/glm-5.3";
const ORCA = "orcarouter/z-ai/glm-5.3";
const OPENROUTER = "or/z-ai/glm-5.3";

function settingsWithPool(targets: string[]): DashboardSettings {
  return createDashboardSettings({
    modelAliases: { [ALIAS]: { targets } },
    customAliasCatalog: {},
  });
}

function row() {
  return within(screen.getByTestId(`alias-row-${ALIAS}`));
}

/**
 * Renders the editor with an `onSave` that behaves like the real settings
 * mutation: the saved settings are visible through props before the promise
 * resolves, because the mutation awaits the settings refetch first.
 */
function renderEditor(initial: DashboardSettings) {
  let current = initial;
  const onSave = vi.fn(async (patch: Partial<SettingsUpdateRequest>) => {
    const fields: Partial<SettingsUpdateRequest> = { ...patch };
    delete fields.expectedVersion;
    current = { ...current, ...(fields as Partial<DashboardSettings>) };
    view.rerender(<AliasSettings settings={current} busy={false} onSave={onSave} />);
    return current;
  });
  const view = renderWithProviders(<AliasSettings settings={current} busy={false} onSave={onSave} />);
  return { onSave, view };
}

function poolInvalidError(message: string, target: string | null) {
  return new ApiError({
    message,
    status: 400,
    code: "model_alias_pool_invalid",
    details: {
      code: "model_alias_pool_invalid",
      message,
      details: { code: "model_alias_pool_invalid", alias: ALIAS, target },
    },
  });
}

describe("model alias pools", () => {
  it("reorders targets and saves the whole map in pool shape", async () => {
    const user = userEvent.setup();
    const { onSave } = renderEditor(settingsWithPool([ORCA, OPENROUTER]));

    await user.click(row().getByRole("button", { name: `Move ${OPENROUTER} up` }));

    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        modelAliases: { [ALIAS]: { targets: [OPENROUTER, ORCA] } },
      }),
    );
    const items = row().getAllByRole("listitem");
    expect(items[0]).toHaveTextContent(OPENROUTER);
    expect(items[1]).toHaveTextContent(ORCA);
    expect(row().getByRole("button", { name: `Move ${OPENROUTER} up` })).toBeDisabled();
    expect(row().getByRole("button", { name: `Move ${ORCA} down` })).toBeDisabled();
  });

  it("adds a target from the input and clears it", async () => {
    const user = userEvent.setup();
    const { onSave } = renderEditor(settingsWithPool([ORCA]));

    const input = row().getByRole("combobox", { name: `Add target to ${ALIAS}` });
    await user.type(input, `  ${OPENROUTER}  `);
    await user.click(row().getByRole("button", { name: "Add target" }));

    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        modelAliases: { [ALIAS]: { targets: [ORCA, OPENROUTER] } },
      }),
    );
    expect(input).toHaveValue("");
    expect(row().getAllByRole("listitem")).toHaveLength(2);
    expect(row().getByRole("button", { name: `Move ${OPENROUTER} up` })).toBeEnabled();
  });

  it("offers known model ids as completions for a new target", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <AliasSettings settings={settingsWithPool([ORCA])} busy={false} onSave={vi.fn().mockResolvedValue(undefined)} />,
    );

    const input = row().getByRole("combobox", { name: `Add target to ${ALIAS}` });
    await user.click(input);
    const listbox = await waitFor(() => {
      const id = input.getAttribute("aria-controls") ?? "";
      const list = document.getElementById(id);
      expect(list).not.toBeNull();
      return list as HTMLElement;
    });
    expect(listbox.querySelectorAll("[role='option']").length).toBeGreaterThan(0);
  });

  it("rejects a duplicate target before saving", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderWithProviders(<AliasSettings settings={settingsWithPool([ORCA])} busy={false} onSave={onSave} />);

    await user.type(row().getByRole("combobox", { name: `Add target to ${ALIAS}` }), ORCA.toUpperCase());

    expect(row().getByText("This target is already in the pool.")).toBeInTheDocument();
    expect(row().getByRole("button", { name: "Add target" })).toBeDisabled();
    await user.keyboard("{Enter}");
    expect(onSave).not.toHaveBeenCalled();
  });

  it("cannot remove the last target but can remove the alias", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderWithProviders(<AliasSettings settings={settingsWithPool([ORCA])} busy={false} onSave={onSave} />);

    expect(row().getByRole("button", { name: `Remove target ${ORCA}` })).toBeDisabled();
    expect(row().queryByRole("button", { name: `Move ${ORCA} up` })).not.toBeInTheDocument();
    expect(row().getByRole("button", { name: "Remove" })).toBeEnabled();

    await user.click(row().getByRole("button", { name: "Remove" }));

    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ modelAliases: {}, customAliasCatalog: {} }),
    );
  });

  it("removes one target from a pool", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderWithProviders(
      <AliasSettings settings={settingsWithPool([ORCA, OPENROUTER])} busy={false} onSave={onSave} />,
    );

    await user.click(row().getByRole("button", { name: `Remove target ${ORCA}` }));

    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ modelAliases: { [ALIAS]: { targets: [OPENROUTER] } } }),
    );
  });

  it("creates a one-target pool from the add-alias form", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderWithProviders(
      <AliasSettings settings={createDashboardSettings({ modelAliases: {} })} busy={false} onSave={onSave} />,
    );

    await user.type(screen.getByRole("textbox", { name: "Real model" }), ORCA);
    await user.type(screen.getByRole("textbox", { name: "Alias name" }), ALIAS);
    await user.click(screen.getByRole("button", { name: "Add alias" }));

    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ modelAliases: { [ALIAS]: { targets: [ORCA] } } }),
    );
  });

  it("shows a server pool rejection on the row and keeps the unsaved list", async () => {
    const user = userEvent.setup();
    const message = `Alias '${ALIAS}' target 'cc/glm-5.3' routes to Claude, which does not support pooling yet`;
    const onSave = vi.fn().mockRejectedValue(poolInvalidError(message, "cc/glm-5.3"));
    renderWithProviders(<AliasSettings settings={settingsWithPool([ORCA])} busy={false} onSave={onSave} />);

    await user.type(row().getByRole("combobox", { name: `Add target to ${ALIAS}` }), "cc/glm-5.3{Enter}");

    expect(await row().findByRole("alert")).toHaveTextContent(message);
    const items = row().getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[1]).toHaveTextContent("cc/glm-5.3");

    // Fixing the list clears the error once the next save succeeds.
    onSave.mockResolvedValue(undefined);
    await user.click(row().getByRole("button", { name: "Remove target cc/glm-5.3" }));
    await waitFor(() => expect(row().queryByRole("alert")).not.toBeInTheDocument());
    expect(onSave).toHaveBeenLastCalledWith(
      expect.objectContaining({ modelAliases: { [ALIAS]: { targets: [ORCA] } } }),
    );
  });

  it("renders healthy and cooling chip states from the health endpoint", async () => {
    server.use(
      http.get("*/api/settings/alias-pools/health", () =>
        HttpResponse.json({
          aliases: {
            [ALIAS]: {
              [ORCA]: {
                state: "cooling",
                until: "2026-09-23T12:34:00Z",
                lastStatus: 402,
                lastError: "Insufficient credits",
              },
              [OPENROUTER]: { state: "healthy", until: null, lastStatus: null, lastError: null },
            },
          },
        }),
      ),
    );
    renderWithProviders(
      <AliasSettings
        settings={settingsWithPool([ORCA, OPENROUTER])}
        busy={false}
        onSave={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    const cooling = await row().findByText(/cooling until .* \(last: 402\)/);
    expect(cooling).toHaveAttribute("data-state", "cooling");
    expect(cooling).toHaveAttribute("title", "402 Insufficient credits");
    const badges = row().getAllByTestId("alias-target-health");
    expect(badges.map((badge) => badge.getAttribute("data-state"))).toEqual(["cooling", "healthy"]);
  });

  it("polls health while mounted and stops after unmount", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      let requests = 0;
      server.use(
        http.get("*/api/settings/alias-pools/health", () => {
          requests += 1;
          return HttpResponse.json({ aliases: {} });
        }),
      );
      const view = renderWithProviders(
        <AliasSettings
          settings={settingsWithPool([ORCA, OPENROUTER])}
          busy={false}
          onSave={vi.fn().mockResolvedValue(undefined)}
        />,
      );

      await waitFor(() => expect(requests).toBe(1));
      await vi.advanceTimersByTimeAsync(ALIAS_POOLS_HEALTH_POLL_MS + 50);
      await waitFor(() => expect(requests).toBe(2));

      view.unmount();
      await vi.advanceTimersByTimeAsync(ALIAS_POOLS_HEALTH_POLL_MS * 2);
      expect(requests).toBe(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not poll health when no alias is configured", async () => {
    let requests = 0;
    server.use(
      http.get("*/api/settings/alias-pools/health", () => {
        requests += 1;
        return HttpResponse.json({ aliases: {} });
      }),
    );
    renderWithProviders(
      <AliasSettings
        settings={createDashboardSettings({ modelAliases: {} })}
        busy={false}
        onSave={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    await screen.findByRole("button", { name: "Add alias" });
    expect(requests).toBe(0);
  });
});

describe("per-integration alias pool targets", () => {
  const SHARED = "z-ai/glm-5.3";

  function settingsWithSharedModel(): DashboardSettings {
    return createDashboardSettings({
      modelAliases: { [ALIAS]: { targets: [ORCA] } },
      customAliasCatalog: {},
      openrouterSidecarFullModels: [SHARED],
      orcarouterSidecarFullModels: [SHARED],
    });
  }

  async function openPicker() {
    const input = row().getByRole("combobox", { name: `Add target to ${ALIAS}` });
    await userEvent.setup().click(input);
    await waitFor(() => {
      expect(input).toHaveAttribute("aria-expanded", "true");
    });
    const listId = input.getAttribute("aria-controls") ?? "";
    return {
      input,
      listbox: document.getElementById(listId) as HTMLElement,
    };
  }

  it("offers the same model once per integration and picks the named card", async () => {
    const user = userEvent.setup();
    const { onSave } = renderEditor(settingsWithSharedModel());

    const { input, listbox } = await openPicker();
    const options = within(listbox).getAllByRole("option");
    const labels = options.map((option) => option.textContent);
    // Both cards carrying glm-5.3 are offered, each labeled with its integration.
    expect(labels).toContain(`${SHARED}OpenRouter`);
    expect(labels).toContain(`${SHARED}OrcaRouter`);

    await user.click(within(listbox).getByRole("option", { name: `${SHARED}OpenRouter` }));

    expect(input).toHaveValue(`openrouter::${SHARED}`);
    await user.click(row().getByRole("button", { name: "Add target" }));
    expect(onSave).toHaveBeenLastCalledWith(
      expect.objectContaining({
        modelAliases: { [ALIAS]: { targets: [ORCA, `openrouter::${SHARED}`] } },
      }),
    );
  });

  it("filters options by integration name and model text", async () => {
    const user = userEvent.setup();
    renderEditor(settingsWithSharedModel());

    const { input } = await openPicker();
    await user.type(input, "orca");

    // Re-query: the picker re-renders the list while typing.
    const listbox = document.getElementById(input.getAttribute("aria-controls") ?? "") as HTMLElement;
    const options = within(listbox).getAllByRole("option");
    // The OpenRouter-labeled card is filtered out; OrcaRouter's route survives.
    expect(options.some((option) => option.textContent?.includes("OpenRouter"))).toBe(false);
    expect(options.some((option) => option.textContent?.includes("OrcaRouter"))).toBe(true);
  });

  it("keeps free-text commit working when the typed value matches no option", async () => {
    const user = userEvent.setup();
    const { onSave } = renderEditor(settingsWithPool([ORCA]));

    const input = row().getByRole("combobox", { name: `Add target to ${ALIAS}` });
    await user.type(input, "some/custom-target{Enter}");

    expect(onSave).toHaveBeenLastCalledWith(
      expect.objectContaining({
        modelAliases: { [ALIAS]: { targets: [ORCA, "some/custom-target"] } },
      }),
    );
  });
});
