/**
 * The pending-disable window: between flipping the switch and the save landing.
 *
 * `opencode-go-disable-clears-selectability.test.tsx` proves the guard works
 * once `enabled={false}` reaches the browser. That is the *post-refresh* state,
 * and it is not the whole story - which is why this file exists separately
 * rather than as more cases in that one.
 *
 * The gap, confirmed in the composed source at Settings `2ae060e3`:
 *
 *   `sidecar-integration-card.tsx`
 *     const setEnabled = (nextEnabled) => {
 *       setEnabledState(nextEnabled);          // local state, immediate
 *       void onSave(buildEnablePatch(nextEnabled));   // async, not awaited
 *     };
 *
 *   `opencode-go-sidecar-settings.tsx`
 *     const sidecarEnabled = settings.opencodeGoSidecarEnabled ?? false;
 *     render: (...) => <OpenCodeGoModelsBrowser enabled={sidecarEnabled} ... />
 *
 * The card's own switch state updates synchronously, but the models browser is
 * handed `sidecarEnabled`, which is server-backed and only changes after the
 * save round-trips and the settings query refetches. In between - a real window
 * on a slow or failing request - the switch reads "off" while the catalogue
 * still offers models to add.
 *
 * These tests drive the **actual switch** and a **deferred** save, rather than
 * re-rendering with `enabled={false}`, because re-rendering with the final props
 * is precisely the case that already passes and would hide this.
 *
 * Owner: codexlb-opencode-go-settings-r1, actively correcting. `2ae060e3` is a
 * checkpoint. The `it.fails` markers are investigative evidence against this one
 * open race and must become plain assertions on the corrected head.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import * as React from "react";
import { BrowserRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { OpenCodeGoModelsBrowser } from "@/features/settings/components/opencode-go-models-browser";

type Model = {
  id: string;
  protocol: "chat_completions" | "messages" | "responses" | "unknown";
  supported: boolean;
};

const CACHED_MODELS: Model[] = [
  { id: "glm-5.3", protocol: "chat_completions", supported: true },
  { id: "kimi-k3", protocol: "chat_completions", supported: true },
];

/**
 * A minimal stand-in for the settings card's enable control, reproducing the
 * composed wiring exactly: local switch state is immediate, the save is async
 * and not awaited, and the browser is fed the *server-backed* value.
 *
 * Built here rather than mounting the whole settings page so the race is
 * isolated and the test cannot pass for an unrelated reason.
 */
function PendingDisableHarness({
  onSave,
  onAddModel,
}: {
  onSave: (enabled: boolean) => Promise<void>;
  onAddModel: (id: string) => void;
}) {
  const [switchOn, setSwitchOn] = React.useState(true);
  // Server-backed: only advances when the save resolves, mirroring the refetch.
  const [serverEnabled, setServerEnabled] = React.useState(true);

  const setEnabled = (next: boolean) => {
    setSwitchOn(next);
    // Mirrors the composed `setEnabled`: fire-and-forget, server value advances
    // only on success. The `.catch` is the card's own error handling, not a
    // test convenience - a rejected save must leave the server value behind.
    void onSave(next)
      .then(() => setServerEnabled(next))
      .catch(() => {});
  };

  return (
    <div>
      <button type="button" aria-label="Toggle integration" onClick={() => setEnabled(!switchOn)}>
        {switchOn ? "Enabled" : "Disabled"}
      </button>
      <OpenCodeGoModelsBrowser
        models={CACHED_MODELS}
        selectedModels={[]}
        isLoading={false}
        configured={true}
        enabled={serverEnabled}
        onAddModel={onAddModel}
      />
    </div>
  );
}

function renderHarness(save: (enabled: boolean) => Promise<void>) {
  const onAddModel = vi.fn();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <PendingDisableHarness onSave={save} onAddModel={onAddModel} />
      </BrowserRouter>
    </QueryClientProvider>,
  );
  return { onAddModel };
}

function openThePanel() {
  act(() => {
    screen.getByRole("button", { name: /Discovered models/i }).click();
  });
}

function rowFor(modelId: string): HTMLElement {
  const row = screen.getByText(modelId).closest("li");
  expect(row, `no row rendered for ${modelId}`).not.toBeNull();
  return row as HTMLElement;
}

function enabledControlsIn(row: HTMLElement): HTMLElement[] {
  return within(row)
    .queryAllByRole("button")
    .filter((control) => !control.hasAttribute("disabled"));
}

describe("OpenCode Go models during a pending disable", () => {
  it("offers models while the integration is enabled and saved", async () => {
    // Control: without this the rest prove nothing.
    renderHarness(async () => {});
    openThePanel();
    expect(enabledControlsIn(rowFor("glm-5.3"))).toHaveLength(1);
  });

  it.fails("stops offering models as soon as the switch is turned off", async () => {
    const user = userEvent.setup();
    // A save that never resolves: the whole pending window, held open.
    renderHarness(() => new Promise<void>(() => {}));
    openThePanel();
    expect(enabledControlsIn(rowFor("glm-5.3"))).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: "Toggle integration" }));

    // The operator has switched it off. Nothing should still be addable, even
    // though the server has not acknowledged yet.
    expect(enabledControlsIn(rowFor("glm-5.3"))).toHaveLength(0);
  });

  it.fails("invokes no add callback during the pending window", async () => {
    const user = userEvent.setup();
    const { onAddModel } = renderHarness(() => new Promise<void>(() => {}));
    openThePanel();

    await user.click(screen.getByRole("button", { name: "Toggle integration" }));

    const row = rowFor("glm-5.3");
    const controls = within(row).queryAllByRole("button");
    expect(controls.length, "the row rendered no controls").toBeGreaterThan(0);
    await act(async () => {
      for (const control of controls) {
        control.click();
      }
    });

    expect(onAddModel).not.toHaveBeenCalled();
  });

  it.fails("keeps models unusable when the disable save fails", async () => {
    const user = userEvent.setup();
    // The save rejects, so the server value never advances. The switch shows
    // "Disabled"; the catalogue must not contradict it.
    renderHarness(async () => {
      throw new Error("save failed");
    });
    openThePanel();

    await user.click(screen.getByRole("button", { name: "Toggle integration" }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Toggle integration" })).toHaveTextContent("Disabled");
    });
    expect(enabledControlsIn(rowFor("glm-5.3"))).toHaveLength(0);
  });

  it("restores usability once a re-enable save completes", async () => {
    // The other direction must keep working, or a fix that simply pinned the
    // browser to "off" would look correct here.
    const user = userEvent.setup();
    renderHarness(async () => {});
    openThePanel();

    await user.click(screen.getByRole("button", { name: "Toggle integration" }));
    await waitFor(() => {
      expect(enabledControlsIn(rowFor("glm-5.3"))).toHaveLength(0);
    });

    await user.click(screen.getByRole("button", { name: "Toggle integration" }));
    await waitFor(() => {
      expect(enabledControlsIn(rowFor("glm-5.3"))).toHaveLength(1);
    });
  });
});
