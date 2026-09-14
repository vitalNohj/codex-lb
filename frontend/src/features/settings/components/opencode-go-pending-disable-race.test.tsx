/**
 * The pending-disable window, driven through the real settings component.
 *
 * `opencode-go-disable-clears-selectability.test.tsx` covers the *post-refresh*
 * state: the guard once `enabled={false}` has already reached the models
 * browser. This file covers the window *before* that - between the operator
 * moving the switch and the save round-tripping - which is a different failure
 * and needs a different setup.
 *
 * ## Why this file was rewritten
 *
 * An earlier version of this test built a `PendingDisableHarness` that
 * hardcoded `enabled={serverEnabled}` and a home-made toggle button. That was
 * unsound as a regression test, and Firstmate was right to call it out: the
 * harness reproduced the *defect* in the test file itself, so composing the
 * owner's fix could never change its result, and "fixing" it would have meant
 * editing my stand-in rather than the product. A test that can only be
 * satisfied by editing itself proves nothing.
 *
 * Everything below therefore renders the real `OpenCodeGoSidecarSettings`,
 * moves the real enable switch, and lets the real `SidecarIntegrationCard`
 * provider wire `models.render`. The save is deferred so the pending window is
 * held open deliberately. A mutation that reverts the production seam
 * (`enabled={enabled && sidecarEnabled}` back to `enabled={sidecarEnabled}`)
 * must fail these; that is the check the old harness could not offer.
 *
 * The historical simulation is retained only in
 * `data/codexlb-opencode-go-e2e-r1/finding-settings-pending-disable-race.md`
 * as diagnosis of how the race was found - not as regression evidence.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { OpenCodeGoSidecarSettings } from "@/features/settings/components/opencode-go-sidecar-settings";
import type { DashboardSettings } from "@/features/settings/schemas";
import { createDashboardSettings } from "@/test/mocks/factories";
import { server } from "@/test/mocks/server";

const ENABLED_SETTINGS = createDashboardSettings({
  opencodeGoSidecarEnabled: true,
  opencodeGoSidecarApiKeyConfigured: true,
});

/** A discovered catalogue, as a successful models fetch would have left it. */
function serveModels() {
  server.use(
    http.get("*/api/opencode-go-sidecar/models", () =>
      HttpResponse.json({
        models: [
          { id: "glm-5.3", protocol: "chat_completions", supported: true, ownedBy: "opencode" },
          { id: "kimi-k3", protocol: "chat_completions", supported: true, ownedBy: "opencode" },
        ],
      }),
    ),
  );
}

function renderSettings(onSave: (patch: unknown) => Promise<unknown>) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const saveSpy = vi.fn(onSave);
  render(
    <QueryClientProvider client={queryClient}>
      {/* Settings stay enabled: the component is told the server still says
          "on", which is exactly the state during a pending disable. */}
      <OpenCodeGoSidecarSettings
        settings={ENABLED_SETTINGS as DashboardSettings}
        busy={false}
        onSave={saveSpy as never}
      />
    </QueryClientProvider>,
  );
  return { saveSpy };
}

async function openDiscoveredModels(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: /Discovered models/i }));
}

async function rowFor(modelId: string): Promise<HTMLElement> {
  // The id can appear both in the discovered list and in the selected
  // full-models list, so scope to list rows and take the discovered one.
  // ``findAllByText`` rather than ``findByText``: a bare match throws
  // "found multiple elements" the moment a model is also selected elsewhere,
  // which is a test-selector failure masquerading as a product failure.
  const labels = await screen.findAllByText(modelId);
  const rows = labels
    .map((label) => label.closest("li"))
    .filter((row): row is HTMLElement => row !== null && within(row).queryAllByRole("button").length > 0);
  expect(rows.length, `no model row rendered for ${modelId}`).toBeGreaterThan(0);
  return rows[0];
}

function enabledControlsIn(row: HTMLElement): HTMLElement[] {
  return within(row)
    .queryAllByRole("button")
    .filter((control) => !control.hasAttribute("disabled"));
}

/** The card's enable switch, by role rather than by a label this test owns. */
async function enableSwitch(): Promise<HTMLElement> {
  const switches = await screen.findAllByRole("switch");
  expect(switches.length, "no enable switch rendered").toBeGreaterThan(0);
  return switches[0];
}

describe("OpenCode Go models during a pending disable", () => {
  it("offers a supported model while enabled and saved", async () => {
    // Control. Without an offerable control in the healthy state the rest of
    // this file proves nothing.
    const user = userEvent.setup();
    serveModels();
    renderSettings(async () => undefined);
    await openDiscoveredModels(user);

    await waitFor(async () => {
      expect(enabledControlsIn(await rowFor("glm-5.3"))).toHaveLength(1);
    });
  });

  it("stops offering models the instant the switch is turned off", async () => {
    const user = userEvent.setup();
    serveModels();
    // A save that never resolves: the pending window, held open.
    renderSettings(() => new Promise(() => {}));
    await openDiscoveredModels(user);
    await waitFor(async () => {
      expect(enabledControlsIn(await rowFor("glm-5.3"))).toHaveLength(1);
    });

    await user.click(await enableSwitch());

    // The operator has switched it off. Nothing may still be addable, even
    // though the server has not acknowledged and the settings prop still says
    // enabled.
    await waitFor(async () => {
      expect(enabledControlsIn(await rowFor("glm-5.3"))).toHaveLength(0);
    });
    expect(enabledControlsIn(await rowFor("kimi-k3"))).toHaveLength(0);
  });

  it("invokes no save patch from a model row during the pending window", async () => {
    const user = userEvent.setup();
    serveModels();
    const { saveSpy } = renderSettings(() => new Promise(() => {}));
    await openDiscoveredModels(user);
    await waitFor(async () => {
      expect(enabledControlsIn(await rowFor("glm-5.3"))).toHaveLength(1);
    });

    await user.click(await enableSwitch());
    const enablePatches = saveSpy.mock.calls.length;

    // Click every control in the row, whatever it is now called. A purely
    // visual fix would satisfy a disabled-attribute check but still let a
    // full-model patch through here.
    const row = await rowFor("glm-5.3");
    for (const control of within(row).queryAllByRole("button")) {
      await user.click(control).catch(() => undefined);
    }

    expect(saveSpy.mock.calls.length).toBe(enablePatches);
  });

  it("keeps models unusable when the disable save fails", async () => {
    const user = userEvent.setup();
    serveModels();
    // The save rejects, so the server value never advances. This window never
    // closes on its own, which is why it matters more than a slow save.
    renderSettings(async () => {
      throw new Error("save failed");
    });
    await openDiscoveredModels(user);
    await waitFor(async () => {
      expect(enabledControlsIn(await rowFor("glm-5.3"))).toHaveLength(1);
    });

    await user.click(await enableSwitch());

    await waitFor(async () => {
      expect(enabledControlsIn(await rowFor("glm-5.3"))).toHaveLength(0);
    });
  });

  it("restores usability when the switch is turned back on", async () => {
    // The other direction must keep working, or a fix that simply pinned the
    // catalogue to "off" would look correct above.
    const user = userEvent.setup();
    serveModels();
    renderSettings(async () => undefined);
    await openDiscoveredModels(user);
    await waitFor(async () => {
      expect(enabledControlsIn(await rowFor("glm-5.3"))).toHaveLength(1);
    });

    await user.click(await enableSwitch());
    await waitFor(async () => {
      expect(enabledControlsIn(await rowFor("glm-5.3"))).toHaveLength(0);
    });

    await user.click(await enableSwitch());
    await waitFor(async () => {
      expect(enabledControlsIn(await rowFor("glm-5.3"))).toHaveLength(1);
    });
  });
});
