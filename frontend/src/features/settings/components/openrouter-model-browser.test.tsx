import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { OpenRouterModelBrowser } from "@/features/settings/components/openrouter-model-browser";
import type { OpenRouterSidecarModelSummary } from "@/features/settings/schemas";

const MODELS: OpenRouterSidecarModelSummary[] = [
  { id: "deepseek/deepseek-chat", created: 1, ownedBy: "deepseek" },
  { id: "google/gemini-2.5-pro-preview", created: 2, ownedBy: "google" },
  { id: "meta-llama/llama-3.3-70b-instruct", created: 3, ownedBy: "meta-llama" },
];

describe("OpenRouterModelBrowser", () => {
  it("renders the model count in the header", () => {
    render(<OpenRouterModelBrowser models={MODELS} isLoading={false} onAddPrefix={() => {}} />);
    expect(screen.getByText("Discovered models (3)")).toBeInTheDocument();
  });

  it("filters the list when typing in search", async () => {
    const user = userEvent.setup();
    render(<OpenRouterModelBrowser models={MODELS} isLoading={false} onAddPrefix={() => {}} />);

    await user.type(screen.getByPlaceholderText("Search models..."), "deepseek");

    expect(screen.getByText("deepseek/deepseek-chat")).toBeInTheDocument();
    expect(screen.queryByText("google/gemini-2.5-pro-preview")).not.toBeInTheDocument();
  });

  it("shows an empty state when nothing matches", async () => {
    const user = userEvent.setup();
    render(<OpenRouterModelBrowser models={MODELS} isLoading={false} onAddPrefix={() => {}} />);

    await user.type(screen.getByPlaceholderText("Search models..."), "does-not-exist");

    expect(screen.getByText("No models match your search")).toBeInTheDocument();
  });

  it("calls onAddPrefix with the provider prefix", async () => {
    const user = userEvent.setup();
    const onAddPrefix = vi.fn();
    render(<OpenRouterModelBrowser models={MODELS} isLoading={false} onAddPrefix={onAddPrefix} />);

    await user.click(screen.getAllByRole("button", { name: /Add prefix/ })[0]);

    expect(onAddPrefix).toHaveBeenCalledWith("deepseek/");
  });

  it("shows guidance when no models are loaded", () => {
    render(<OpenRouterModelBrowser models={[]} isLoading={false} onAddPrefix={() => {}} />);
    expect(screen.getByText("No models loaded — save API key and test connection")).toBeInTheDocument();
  });
});
