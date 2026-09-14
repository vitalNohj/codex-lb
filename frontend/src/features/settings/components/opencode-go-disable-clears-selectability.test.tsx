/**
 * Cached discovered models must stop being usable once the integration is
 * disabled or its key is cleared.
 *
 * The defect, confirmed in `opencode-go-models-browser.tsx` at checkpoint
 * `315b3616`: `enabled` and `configured` are consulted only to pick the wording
 * of the **empty** branch (`models.length === 0`). When a previous successful
 * discovery has left rows cached that branch is skipped, and each row's control
 * is gated solely on `disabled={isSelected || !model.supported}`, which never
 * looks at `enabled` or `configured`.
 *
 * User-visible sequence: configure a key and load the catalogue, then disable
 * the integration or clear the key. The catalogue stays on screen and models
 * remain addable even though nothing can route them.
 *
 * ## Discrimination hazard these tests are written to avoid
 *
 * An earlier version of this file queried `getByRole("button", { name: "Add
 * full model glm-5.3" })` under `it.fails`. That is unsound: the owner's actual
 * fix **renames** an inert row's control to `"Unavailable ..."`, so the query
 * would throw "element not found", `it.fails` would absorb that as the expected
 * failure, and the suite would keep reporting "4 expected fail" forever - never
 * signalling that the defect was fixed. Verified by simulating the owner-style
 * fix: all four still reported as expected failures.
 *
 * So nothing here keys on the button's accessible name, or on any label that
 * the fix is free to change. Each test locates the row by its model id and then
 * asserts a property that must hold *however* the row is labelled:
 *
 *   - no enabled control inside the row,
 *   - clicking every control in the row invokes no callback,
 *   - the panel carries an explanation of why it is inert,
 *   - and a real success -> disable transition, not just a static prop.
 *
 * A "query not found" is never accepted as evidence of the product behavior:
 * the row must exist for the assertion to mean anything, so its presence is
 * asserted first.
 *
 * Owner: codexlb-opencode-go-settings-r1. This file is evidence, not a fix.
 *
 * All five `it.fails` markers are investigative evidence against one open
 * defect. Every one of them must be converted to a plain `it(...)` once the
 * owner's corrected head is composed, before any readiness claim. They must not
 * survive into the final delivered suite.
 */

import { act, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { OpenCodeGoModelsBrowser } from "@/features/settings/components/opencode-go-models-browser";

type Model = {
  id: string;
  protocol: "chat_completions" | "messages" | "responses" | "unknown";
  supported: boolean;
};

/** A catalogue a previous successful discovery would have left cached. */
const CACHED_MODELS: Model[] = [
  { id: "glm-5.3", protocol: "chat_completions", supported: true },
  { id: "kimi-k3", protocol: "chat_completions", supported: true },
  { id: "grok-4.6", protocol: "responses", supported: false },
];

type BrowserProps = Parameters<typeof OpenCodeGoModelsBrowser>[0];

function renderBrowser(overrides: Partial<BrowserProps> = {}) {
  const onAddModel = vi.fn();
  const view = render(
    <OpenCodeGoModelsBrowser
      models={CACHED_MODELS}
      selectedModels={[]}
      enabled={true}
      configured={true}
      isLoading={false}
      onAddModel={onAddModel}
      {...overrides}
    />,
  );
  return { onAddModel, view };
}

function openThePanel() {
  // Rows only mount once the panel is expanded.
  const toggle = screen.getByRole("button", { name: /Discovered models/i });
  act(() => {
    toggle.click();
  });
}

/**
 * The row for `modelId`, located by its id text rather than by any control
 * label, so a rename cannot turn a real regression into a silent miss.
 */
function rowFor(modelId: string): HTMLElement {
  const label = screen.getByText(modelId);
  const row = label.closest("li");
  expect(row, `no cached row rendered for ${modelId}`).not.toBeNull();
  return row as HTMLElement;
}

/** Every control in the row that a user could actually activate. */
function enabledControlsIn(row: HTMLElement): HTMLElement[] {
  return within(row)
    .queryAllByRole("button")
    .filter((control) => !control.hasAttribute("disabled"));
}

describe("OpenCode Go discovered models, after a successful discovery", () => {
  it("offers supported models while enabled and configured", () => {
    // Control. Without this the rest prove nothing: it establishes that the row
    // renders AND that an offerable control exists in the healthy state.
    renderBrowser();
    openThePanel();

    expect(enabledControlsIn(rowFor("glm-5.3"))).toHaveLength(1);
    // An unsupported protocol is listed but never offered - already correct.
    expect(enabledControlsIn(rowFor("grok-4.6"))).toHaveLength(0);
  });

  it.fails("offers no usable control for a cached model once disabled", () => {
    renderBrowser({ enabled: false });
    openThePanel();

    // The row must still be rendered - seeing what was discovered is fine.
    // What must not exist is any control the user can still activate.
    expect(enabledControlsIn(rowFor("glm-5.3"))).toHaveLength(0);
    expect(enabledControlsIn(rowFor("kimi-k3"))).toHaveLength(0);
  });

  it.fails("offers no usable control once the API key is cleared", () => {
    renderBrowser({ configured: false });
    openThePanel();

    expect(enabledControlsIn(rowFor("glm-5.3"))).toHaveLength(0);
  });

  it.fails("invokes no callback when a disabled row's controls are activated", () => {
    // The stronger form, and the one a purely visual fix would not satisfy:
    // click every control in the row, whatever it is now called, and require
    // that nothing reaches the handler.
    const { onAddModel } = renderBrowser({ enabled: false });
    openThePanel();

    const row = rowFor("glm-5.3");
    const controls = within(row).queryAllByRole("button");
    expect(controls.length, "the row rendered no controls at all").toBeGreaterThan(0);
    act(() => {
      for (const control of controls) {
        control.click();
      }
    });

    expect(onAddModel).not.toHaveBeenCalled();
  });

  it.fails("explains why a populated catalogue is inert rather than looking operable", () => {
    // The empty-state copy already distinguishes disabled from unconfigured;
    // the populated state should be equally honest instead of silently
    // presenting a stale, unusable catalogue.
    //
    // Scope note. This case is part of the SAME open defect as the four above,
    // not a separate finding. An earlier note of mine called it a "second gap"
    // because it did not flip when I simulated a partial fix (rename + gate
    // only). That simulation was my own construction, not the owner's revision,
    // so its silence says nothing about the real fix - which is finalizing
    // availability gating AND explanatory copy together. Retracted accordingly.
    renderBrowser({ enabled: false });
    openThePanel();

    expect(screen.getByText(/disabled|not discovered|enable it/i)).toBeInTheDocument();
  });

  it.fails("drops usability across an actual success -> disable transition", () => {
    // Props alone could be satisfied by a component that never re-evaluates.
    // This performs the real transition: discover successfully, then disable,
    // and require the previously-offered control to become unusable.
    const { onAddModel, view } = renderBrowser();
    openThePanel();
    expect(enabledControlsIn(rowFor("glm-5.3"))).toHaveLength(1);

    view.rerender(
      <OpenCodeGoModelsBrowser
        models={CACHED_MODELS}
        selectedModels={[]}
        enabled={false}
        configured={true}
        isLoading={false}
        onAddModel={onAddModel}
      />,
    );

    expect(enabledControlsIn(rowFor("glm-5.3"))).toHaveLength(0);
  });
});
