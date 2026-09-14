import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { OpenCodeGoModelsBrowser } from "@/features/settings/components/opencode-go-models-browser";
import {
  OpenCodeGoSidecarModelSummarySchema,
  type OpenCodeGoSidecarModelSummary,
} from "@/features/settings/schemas";

/**
 * Local typed fixture parsed through the schema, so a drift between the
 * published backend contract and this file fails here rather than in the UI.
 */
function model(overrides: Partial<OpenCodeGoSidecarModelSummary> & { id: string }) {
  return OpenCodeGoSidecarModelSummarySchema.parse(overrides);
}

const MODELS = [
  model({ id: "glm-5.3", protocol: "chat_completions", supported: true, ownedBy: "opencode" }),
  model({ id: "qwen3.8-max", protocol: "messages", supported: false }),
  model({ id: "muse-spark-1.3-contributor", protocol: "responses", supported: false }),
  model({ id: "some-unlisted-preview", protocol: "unknown", supported: false }),
];

function renderBrowser(props: Partial<React.ComponentProps<typeof OpenCodeGoModelsBrowser>> = {}) {
  const onAddModel = vi.fn();
  const utils = render(
    <OpenCodeGoModelsBrowser
      models={MODELS}
      selectedModels={[]}
      isLoading={false}
      configured
      enabled
      onAddModel={onAddModel}
      {...props}
    />,
  );
  return { ...utils, onAddModel };
}

async function expand(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: /Discovered models/i }));
}

describe("OpenCodeGoModelsBrowser", () => {
  it("stays collapsed until opened", () => {
    renderBrowser();

    expect(screen.getByRole("button", { name: /Discovered models/i })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(screen.queryByLabelText("Search OpenCode Go models")).not.toBeInTheDocument();
  });

  it("summarises how many discovered models are actually supported", () => {
    renderBrowser();

    expect(
      screen.getByRole("button", { name: /Discovered models \(4\).*1 supported/ }),
    ).toBeInTheDocument();
  });

  it("does not treat an unknown protocol as a usable default", async () => {
    const user = userEvent.setup();
    const { onAddModel } = renderBrowser();

    await expand(user);
    const row = screen.getByText("some-unlisted-preview").closest("li") as HTMLElement;

    expect(within(row).getByText("Protocol unknown")).toBeInTheDocument();
    expect(within(row).getByText(/Not classified by the pinned model map/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Unavailable some-unlisted-preview" })).toBeDisabled();
    expect(onAddModel).not.toHaveBeenCalled();
  });

  it("keeps a mapped but undispatchable /messages model non-selectable", async () => {
    const user = userEvent.setup();
    renderBrowser();

    await expand(user);
    const row = screen.getByText("qwen3.8-max").closest("li") as HTMLElement;

    expect(within(row).getByText("Messages")).toBeInTheDocument();
    expect(within(row).getByText(/Messages routing not supported yet/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Unavailable qwen3.8-max" })).toBeDisabled();
  });

  it("keeps a /responses model non-selectable", async () => {
    const user = userEvent.setup();
    renderBrowser();

    await expand(user);
    const row = screen.getByText("muse-spark-1.3-contributor").closest("li") as HTMLElement;

    expect(within(row).getByText(/Responses routing not supported yet/)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Unavailable muse-spark-1.3-contributor" }),
    ).toBeDisabled();
  });

  it("lists unsupported models rather than hiding them", async () => {
    const user = userEvent.setup();
    renderBrowser();

    await expand(user);

    for (const id of ["qwen3.8-max", "muse-spark-1.3-contributor", "some-unlisted-preview"]) {
      expect(screen.getByText(id)).toBeInTheDocument();
    }
  });

  it("adds a supported model on request", async () => {
    const user = userEvent.setup();
    const { onAddModel } = renderBrowser();

    await expand(user);
    await user.click(screen.getByRole("button", { name: "Add full model glm-5.3" }));

    expect(onAddModel).toHaveBeenCalledWith("glm-5.3");
  });

  it("shows an already-selected model as added rather than addable", async () => {
    const user = userEvent.setup();
    renderBrowser({ selectedModels: ["GLM-5.3"] });

    await expand(user);

    expect(screen.getByRole("button", { name: "Added glm-5.3" })).toBeDisabled();
  });

  it("filters by search and reports an empty result honestly", async () => {
    const user = userEvent.setup();
    renderBrowser();

    await expand(user);
    await user.type(screen.getByLabelText("Search OpenCode Go models"), "nothing-matches");

    expect(screen.getByText("No models match your search")).toBeInTheDocument();
  });

  it("distinguishes loading, unconfigured, disabled, and genuinely empty catalogs", async () => {
    const user = userEvent.setup();
    const { rerender } = renderBrowser({ models: [], isLoading: true });

    await expand(user);
    expect(screen.getByText("Loading models...")).toBeInTheDocument();

    rerender(
      <OpenCodeGoModelsBrowser
        models={[]}
        selectedModels={[]}
        isLoading={false}
        configured={false}
        enabled={false}
        onAddModel={vi.fn()}
      />,
    );
    expect(screen.getByText(/add an API key to discover models/i)).toBeInTheDocument();

    // Key stored but switched off: the backend returns an empty list without
    // calling upstream, so claiming the provider has no models would be false.
    rerender(
      <OpenCodeGoModelsBrowser
        models={[]}
        selectedModels={[]}
        isLoading={false}
        configured
        enabled={false}
        onAddModel={vi.fn()}
      />,
    );
    expect(screen.getByText(/not discovered while the integration is disabled/i)).toBeInTheDocument();
    expect(screen.queryByText("No models returned by OpenCode Go.")).not.toBeInTheDocument();

    rerender(
      <OpenCodeGoModelsBrowser
        models={[]}
        selectedModels={[]}
        isLoading={false}
        configured
        enabled
        onAddModel={vi.fn()}
      />,
    );
    expect(screen.getByText("No models returned by OpenCode Go.")).toBeInTheDocument();
  });

  // React Query retains the last successful result, so rows stay mounted after
  // the operator disables the integration or clears the key. Those cached rows
  // must stop being selectable: adding one would configure a full model for an
  // integration that cannot route it.
  describe("cached rows after the integration stops being usable", () => {
    it("stops offering retained rows once the integration is disabled", async () => {
      const user = userEvent.setup();
      const { rerender, onAddModel } = renderBrowser();

      await expand(user);
      expect(screen.getByRole("button", { name: "Add full model glm-5.3" })).toBeEnabled();

      rerender(
        <OpenCodeGoModelsBrowser
          models={MODELS}
          selectedModels={[]}
          isLoading={false}
          configured
          enabled={false}
          onAddModel={onAddModel}
        />,
      );

      expect(screen.getByRole("button", { name: "Unavailable glm-5.3" })).toBeDisabled();
      expect(onAddModel).not.toHaveBeenCalled();
    });

    it("stops offering retained rows once the stored key is cleared", async () => {
      const user = userEvent.setup();
      const { rerender, onAddModel } = renderBrowser();

      await expand(user);
      expect(screen.getByRole("button", { name: "Add full model glm-5.3" })).toBeEnabled();

      rerender(
        <OpenCodeGoModelsBrowser
          models={MODELS}
          selectedModels={[]}
          isLoading={false}
          configured={false}
          enabled
          onAddModel={onAddModel}
        />,
      );

      expect(screen.getByRole("button", { name: "Unavailable glm-5.3" })).toBeDisabled();
      expect(onAddModel).not.toHaveBeenCalled();
    });

    it("explains why retained rows are unavailable rather than implying the model changed", async () => {
      const user = userEvent.setup();
      renderBrowser({ enabled: false });

      await expand(user);
      const row = screen.getByText("glm-5.3").closest("li") as HTMLElement;

      // The model itself is still supported; the integration is what is off.
      expect(within(row).getByText("Chat Completions")).toBeInTheDocument();
      expect(within(row).getByText(/Integration disabled/)).toBeInTheDocument();
    });

    it("does not count retained rows as currently supported", () => {
      renderBrowser({ enabled: false });

      // 1 of these models is dispatchable, but none is usable right now, so the
      // header must not advertise a supported count.
      expect(screen.getByRole("button", { name: /Discovered models \(4\)/ })).toBeInTheDocument();
      expect(screen.queryByText(/supported/)).not.toBeInTheDocument();
    });

    it("keeps counting supported rows while the integration is usable", () => {
      renderBrowser();

      expect(
        screen.getByRole("button", { name: /Discovered models \(4\).*1 supported/ }),
      ).toBeInTheDocument();
    });

    it("names the reason in the header so the state is not silent", () => {
      renderBrowser({ enabled: false });

      expect(
        screen.getByRole("button", { name: /Discovered models \(4\).*Integration disabled/ }),
      ).toBeInTheDocument();
    });

    it("reports a cleared key distinctly from a disabled integration", async () => {
      const user = userEvent.setup();
      renderBrowser({ configured: false });

      await expand(user);
      const row = screen.getByText("glm-5.3").closest("li") as HTMLElement;

      expect(within(row).getByText(/No API key stored/)).toBeInTheDocument();
      expect(screen.queryByText(/Integration disabled/)).not.toBeInTheDocument();
    });

    it("shows an already-added model as unavailable rather than removable-looking", async () => {
      const user = userEvent.setup();
      renderBrowser({ enabled: false, selectedModels: ["glm-5.3"] });

      await expand(user);

      // It stays configured in the Full models list above; here it simply
      // cannot be acted on, and "Added" would imply it is live.
      expect(screen.getByRole("button", { name: "Unavailable glm-5.3" })).toBeDisabled();
    });
  });

  it("is operable by keyboard alone", async () => {
    const user = userEvent.setup();
    const { onAddModel } = renderBrowser({ models: [MODELS[0]] });

    await user.tab();
    expect(screen.getByRole("button", { name: /Discovered models/i })).toHaveFocus();
    await user.keyboard("{Enter}");

    await user.tab();
    expect(screen.getByLabelText("Search OpenCode Go models")).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("button", { name: "Add full model glm-5.3" })).toHaveFocus();
    await user.keyboard("{Enter}");

    expect(onAddModel).toHaveBeenCalledWith("glm-5.3");
  });
});
