/**
 * Cached discovered models must stop being selectable once the integration is
 * disabled or its key is cleared.
 *
 * The defect, confirmed in `opencode-go-models-browser.tsx` at checkpoint
 * `315b3616`: `enabled` and `configured` are consulted only to choose the text
 * of the **empty** branch (`models.length === 0`). When a previous successful
 * discovery has left rows cached, that branch is skipped entirely, so the list
 * renders and each row's Add button is gated solely on
 * `disabled={isSelected || !model.supported}` - which never looks at `enabled`
 * or `configured`.
 *
 * The user-visible consequence is a success -> disable (or clear key) sequence:
 * the operator turns the integration off, the catalogue stays on screen, and
 * models remain addable even though nothing can route them. That is the
 * "configured-disabled" state being presented as usable.
 *
 * These tests assert the accepted behavior directly and are expected to fail
 * until the owner's fix lands - no defect-passing characterization, per MAIN's
 * rule that a final suite must never be green because a bug exists. The marker
 * is `xfail`-equivalent via `it.fails`, so the moment the fix lands these turn
 * into hard failures and must be converted to plain `it(...)` deliberately.
 *
 * Owner: codexlb-opencode-go-settings-r1. This file is evidence, not a fix.
 */

import { act, render, screen } from "@testing-library/react";
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

function renderBrowser(overrides: Partial<Parameters<typeof OpenCodeGoModelsBrowser>[0]> = {}) {
  const onAddModel = vi.fn();
  render(
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
  return { onAddModel };
}

function openThePanel() {
  // The panel is collapsed by default; its rows only mount once expanded.
  // Wrapped in act(...) so the state update flushes before the queries below.
  const toggle = screen.getByRole("button", { name: /Discovered models/i });
  act(() => {
    toggle.click();
  });
}

describe("OpenCode Go discovered models, after a successful discovery", () => {
  it("offers supported models while enabled and configured", () => {
    // Control. If this ever fails the rest prove nothing.
    renderBrowser();
    openThePanel();

    const add = screen.getByRole("button", { name: "Add full model glm-5.3" });
    expect(add).toBeEnabled();
    // An unsupported protocol is listed but never offered - already correct.
    expect(screen.getByRole("button", { name: "Unavailable grok-4.6" })).toBeDisabled();
  });

  it.fails("stops offering cached models once the integration is disabled", () => {
    renderBrowser({ enabled: false });
    openThePanel();

    // The rows are still rendered from cache, which is reasonable - the
    // operator may want to see what was discovered. What must not happen is
    // offering to add one, because nothing can route it while disabled.
    expect(screen.getByRole("button", { name: "Add full model glm-5.3" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Add full model kimi-k3" })).toBeDisabled();
  });

  it.fails("stops offering cached models once the API key is cleared", () => {
    renderBrowser({ configured: false });
    openThePanel();

    expect(screen.getByRole("button", { name: "Add full model glm-5.3" })).toBeDisabled();
  });

  it.fails("does not add a model when disabled, even if the control is activated", () => {
    // The stronger form: whatever the control looks like, the handler must not
    // fire. A purely visual fix that left onAddModel reachable would pass a
    // disabled-attribute check but still corrupt the configuration.
    const { onAddModel } = renderBrowser({ enabled: false });
    openThePanel();

    act(() => {
      screen.getByRole("button", { name: "Add full model glm-5.3" }).click();
    });

    expect(onAddModel).not.toHaveBeenCalled();
  });

  it.fails("explains why the catalogue is inert rather than looking operable", () => {
    // The empty-state copy already distinguishes disabled from unconfigured.
    // The populated state should be equally honest instead of silently
    // presenting a stale, unusable catalogue.
    renderBrowser({ enabled: false });
    openThePanel();

    expect(screen.getByText(/disabled|not discovered|enable it/i)).toBeInTheDocument();
  });
});
