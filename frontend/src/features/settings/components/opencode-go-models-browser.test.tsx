import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { OpenCodeGoModelsBrowser } from "@/features/settings/components/opencode-go-models-browser";
import {
  OpenCodeGoSidecarModelSummarySchema,
  type OpenCodeGoSidecarModelSummary,
} from "@/features/settings/schemas";

/**
 * Local typed fixture. Parsing through the schema keeps this honest: if the
 * published backend contract changes shape, this fixture fails to build rather
 * than quietly testing a shape the server never sends.
 */
function model(overrides: Partial<OpenCodeGoSidecarModelSummary> & { id: string }) {
  return OpenCodeGoSidecarModelSummarySchema.parse(overrides);
}

const MODELS = [
  model({ id: "kimi-k3", protocol: "chat_completions", routable: true, ownedBy: "moonshotai" }),
  model({
    id: "qwen3.8-max",
    protocol: "messages",
    routable: false,
    unavailableReason: "Messages protocol not implemented",
  }),
  model({ id: "hy4-preview", routable: false, unavailableReason: "Protocol unknown" }),
  model({
    id: "muse-spark-1.3-contributor",
    protocol: "responses",
    routable: true,
    privacySensitive: true,
    privacyNote: "Trains on prompts, not ZDR",
  }),
];

function renderBrowser(props: Partial<React.ComponentProps<typeof OpenCodeGoModelsBrowser>> = {}) {
  const onAddModel = vi.fn();
  const utils = render(
    <OpenCodeGoModelsBrowser
      models={MODELS}
      selectedModels={[]}
      isLoading={false}
      configured
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

  it("summarises how many discovered models are actually routable", () => {
    renderBrowser();

    expect(
      screen.getByRole("button", { name: /Discovered models \(4\).*2 routable/ }),
    ).toBeInTheDocument();
  });

  it("does not claim an unknown protocol is a working default", async () => {
    const user = userEvent.setup();
    const { onAddModel } = renderBrowser();

    await expand(user);
    const row = screen.getByText("hy4-preview").closest("li") as HTMLElement;

    expect(within(row).getByText("Protocol unknown")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Unavailable hy4-preview" })).toBeDisabled();
    expect(onAddModel).not.toHaveBeenCalled();
  });

  it("marks a known-but-unrouted protocol unavailable with its reason", async () => {
    const user = userEvent.setup();
    renderBrowser();

    await expand(user);
    const row = screen.getByText("qwen3.8-max").closest("li") as HTMLElement;

    expect(within(row).getByText("Messages")).toBeInTheDocument();
    expect(within(row).getByText(/Messages protocol not implemented/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Unavailable qwen3.8-max" })).toBeDisabled();
  });

  it("adds a routable model on request", async () => {
    const user = userEvent.setup();
    const { onAddModel } = renderBrowser();

    await expand(user);
    await user.click(screen.getByRole("button", { name: "Add full model kimi-k3" }));

    expect(onAddModel).toHaveBeenCalledWith("kimi-k3");
  });

  it("labels a privacy-sensitive model but keeps it selectable", async () => {
    const user = userEvent.setup();
    renderBrowser();

    await expand(user);
    const row = screen.getByText("muse-spark-1.3-contributor").closest("li") as HTMLElement;

    expect(within(row).getByText("Trains on prompts, not ZDR")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Add full model muse-spark-1.3-contributor" }),
    ).toBeEnabled();
  });

  it("shows an already-selected model as added rather than addable", async () => {
    const user = userEvent.setup();
    renderBrowser({ selectedModels: ["KIMI-K3"] });

    await expand(user);

    expect(screen.getByRole("button", { name: "Added kimi-k3" })).toBeDisabled();
  });

  it("filters by search and reports an empty result honestly", async () => {
    const user = userEvent.setup();
    renderBrowser();

    await expand(user);
    await user.type(screen.getByLabelText("Search OpenCode Go models"), "nothing-matches");

    expect(screen.getByText("No models match your search")).toBeInTheDocument();
  });

  it("distinguishes loading, unconfigured, and empty catalogs", async () => {
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
        onAddModel={vi.fn()}
      />,
    );
    expect(screen.getByText(/add an API key to discover models/i)).toBeInTheDocument();

    rerender(
      <OpenCodeGoModelsBrowser
        models={[]}
        selectedModels={[]}
        isLoading={false}
        configured
        onAddModel={vi.fn()}
      />,
    );
    expect(screen.getByText("No models returned by OpenCode Go.")).toBeInTheDocument();
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
    expect(screen.getByRole("button", { name: "Add full model kimi-k3" })).toHaveFocus();
    await user.keyboard("{Enter}");

    expect(onAddModel).toHaveBeenCalledWith("kimi-k3");
  });
});
