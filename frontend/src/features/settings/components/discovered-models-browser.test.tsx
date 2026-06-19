import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DiscoveredModelsBrowser, type DiscoveredModelSummary } from "@/features/settings/components/discovered-models-browser";

const MODELS: DiscoveredModelSummary[] = [
  { id: "deepseek/deepseek-chat", created: 1, ownedBy: "deepseek" },
  { id: "google/gemini-2.5-pro-preview", created: 2, ownedBy: "google" },
  { id: "meta-llama/llama-3.3-70b-instruct", created: 3, ownedBy: "meta-llama" },
];

describe("DiscoveredModelsBrowser", () => {
  it("renders the model count in the header", () => {
    render(<DiscoveredModelsBrowser models={MODELS} selectedModels={[]} isLoading={false} onAddModel={() => {}} />);
    expect(screen.getByText("Discovered models (3)")).toBeInTheDocument();
  });

  it("filters the list when typing in search", async () => {
    const user = userEvent.setup();
    render(<DiscoveredModelsBrowser models={MODELS} selectedModels={[]} isLoading={false} onAddModel={() => {}} />);

    await user.click(screen.getByRole("button", { name: /Discovered models/i }));
    await user.type(screen.getByPlaceholderText("Search models..."), "deepseek");

    expect(screen.getAllByText("deepseek/deepseek-chat")).toHaveLength(2);
    expect(screen.queryByText("google/gemini-2.5-pro-preview")).not.toBeInTheDocument();
  });

  it("shows an empty state when nothing matches", async () => {
    const user = userEvent.setup();
    render(<DiscoveredModelsBrowser models={MODELS} selectedModels={[]} isLoading={false} onAddModel={() => {}} />);

    await user.click(screen.getByRole("button", { name: /Discovered models/i }));
    await user.type(screen.getByPlaceholderText("Search models..."), "does-not-exist");

    expect(screen.getByText("No models match your search")).toBeInTheDocument();
  });

  it("calls onAddModel with the full model ID", async () => {
    const user = userEvent.setup();
    const onAddModel = vi.fn();
    render(<DiscoveredModelsBrowser models={MODELS} selectedModels={[]} isLoading={false} onAddModel={onAddModel} />);

    await user.click(screen.getByRole("button", { name: /Discovered models/i }));
    await user.click(screen.getAllByRole("button", { name: /Add full model/ })[0]);

    expect(onAddModel).toHaveBeenCalledWith("deepseek/deepseek-chat");
  });

  it("shows guidance when no models are loaded", async () => {
    const user = userEvent.setup();
    render(<DiscoveredModelsBrowser models={[]} selectedModels={[]} isLoading={false} onAddModel={() => {}} />);

    await user.click(screen.getByRole("button", { name: /Discovered models/i }));

    expect(screen.getByText("No models loaded - add an API key to discover models")).toBeInTheDocument();
  });
});
