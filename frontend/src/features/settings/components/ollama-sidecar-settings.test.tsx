import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { OllamaSidecarSettings } from "@/features/settings/components/ollama-sidecar-settings";
import type { DashboardSettings } from "@/features/settings/schemas";
import { server } from "@/test/mocks/server";

const BASE_SETTINGS: DashboardSettings = {
  stickyThreadsEnabled: false,
  upstreamStreamTransport: "default",
  upstreamProxyRoutingEnabled: false,
  upstreamProxyDefaultPoolId: null,
  preferEarlierResetAccounts: true,
  preferEarlierResetWindow: "secondary",
  routingStrategy: "usage_weighted",
  relativeAvailabilityPower: 2,
  relativeAvailabilityTopK: 5,
  singleAccountId: null,
  weeklyPaceWorkingDays: "0,1,2,3,4,5,6",
  openaiCacheAffinityMaxAgeSeconds: 300,
  dashboardSessionTtlSeconds: 43200,
  warmupModel: "gpt-5.4-mini",
  importWithoutOverwrite: false,
  totpRequiredOnLogin: false,
  totpConfigured: false,
  apiKeyAuthEnabled: true,
  additionalQuotaRoutingPolicies: {},
  additionalQuotaPolicies: [],
  limitWarmupEnabled: false,
  limitWarmupWindows: "both",
  limitWarmupModel: "auto",
  limitWarmupPrompt: "Say OK.",
  limitWarmupCooldownSeconds: 3600,
  limitWarmupMinAvailablePercent: 100,
  claudeSidecarEnabled: false,
  claudeSidecarModelPrefixes: [{ prefix: "claude", strip: false }],
  claudeSidecarFullModels: [],
  openrouterSidecarEnabled: true,
  openrouterSidecarBaseUrl: "https://openrouter.ai/api/v1",
  openrouterSidecarApiKeyConfigured: true,
  openrouterSidecarModelPrefixes: [{ prefix: "deepseek/", strip: false }],
  openrouterSidecarFullModels: ["deepseek/deepseek-chat"],
  openrouterSidecarConnectTimeoutSeconds: 8,
  openrouterSidecarRequestTimeoutSeconds: 600,
  openrouterSidecarModelsCacheTtlSeconds: 60,
  omnirouteSidecarEnabled: true,
  omnirouteSidecarBaseUrl: "http://127.0.0.1:20128/v1",
  omnirouteSidecarApiKeyConfigured: true,
  omnirouteSidecarModelPrefixes: [{ prefix: "omni/", strip: true }],
  omnirouteSidecarFullModels: ["omniroute/test-chat"],
  omnirouteSidecarSelectedModels: ["omniroute/test-chat"],
  omnirouteSidecarConnectTimeoutSeconds: 8,
  omnirouteSidecarRequestTimeoutSeconds: 600,
  omnirouteSidecarModelsCacheTtlSeconds: 60,
  ollamaSidecarEnabled: false,
  ollamaSidecarBaseUrl: "https://ollama.com",
  ollamaSidecarApiKeyConfigured: true,
  ollamaSidecarModelPrefixes: [],
  ollamaSidecarFullModels: [],
  ollamaSidecarConnectTimeoutSeconds: 8,
  ollamaSidecarRequestTimeoutSeconds: 600,
  ollamaSidecarModelsCacheTtlSeconds: 60,
};

const ENABLED_SETTINGS: DashboardSettings = {
  ...BASE_SETTINGS,
  ollamaSidecarEnabled: true,
};

function renderWithQueryClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe("OllamaSidecarSettings", () => {
  it("labels the section as the Ollama integration", () => {
    renderWithQueryClient(<OllamaSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={vi.fn()} />);

    expect(screen.getByRole("heading", { name: "Ollama Integration" })).toBeInTheDocument();
  });

  it("links to the Ollama API key page in a new tab", () => {
    renderWithQueryClient(<OllamaSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={vi.fn()} />);

    const link = screen.getByRole("link", { name: "https://ollama.com/settings/keys" });
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("adds an API key and runs the connection test after the save", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    const testSpy = vi.fn();
    server.use(
      http.post("*/api/ollama-sidecar/test", () => {
        testSpy();
        return HttpResponse.json({
          enabled: true,
          configured: true,
          status: "healthy",
          message: "Ollama reachable",
          baseUrl: "https://ollama.com",
          modelCount: 0,
          lastCheckedAt: "2026-01-01T00:00:00Z",
          models: [],
        });
      }),
    );
    renderWithQueryClient(<OllamaSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={onSave} />);

    await user.type(screen.getByLabelText(/API key/), "new-key");
    await user.click(screen.getByRole("button", { name: "Add API key" }));

    await waitFor(() =>
      expect(onSave).toHaveBeenLastCalledWith(expect.objectContaining({ ollamaSidecarApiKey: "new-key" })),
    );
    expect(screen.getByLabelText(/API key/)).toHaveValue("");
    await waitFor(() => expect(testSpy).toHaveBeenCalledTimes(1));
  });

  it("persists edited model prefixes immediately", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderWithQueryClient(<OllamaSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={onSave} />);

    await user.type(screen.getByLabelText("New prefix for Ollama Integration"), "ollama-");
    await user.click(screen.getByRole("button", { name: "Add prefix" }));

    await waitFor(() =>
      expect(onSave).toHaveBeenLastCalledWith(
        expect.objectContaining({
          ollamaSidecarModelPrefixes: [{ prefix: "ollama-", strip: false }],
        }),
      ),
    );
  });

  it("adds a discovered cloud model as a full model and persists immediately", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderWithQueryClient(<OllamaSidecarSettings settings={ENABLED_SETTINGS} busy={false} onSave={onSave} />);

    await user.click(await screen.findByRole("button", { name: /Discovered models/i }));
    await screen.findAllByText("gpt-oss:120b-cloud");
    await user.click(await screen.findByRole("button", { name: /Add full model gpt-oss:120b-cloud/ }));

    expect(
      within(screen.getByLabelText("Configured full models for Ollama Integration")).getByText(
        "gpt-oss:120b-cloud",
      ),
    ).toBeInTheDocument();

    await waitFor(() =>
      expect(onSave).toHaveBeenLastCalledWith(
        expect.objectContaining({
          ollamaSidecarFullModels: ["gpt-oss:120b-cloud"],
        }),
      ),
    );
  });

  it("rejects duplicate prefixes owned by another integration", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<OllamaSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={vi.fn()} />);

    await user.type(screen.getByLabelText("New prefix for Ollama Integration"), "deepseek/");
    await user.click(screen.getByRole("button", { name: "Add prefix" }));

    expect(screen.getByText("Prefix deepseek/ is already used by OpenRouter.")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "Remove prefix deepseek/ before forwarding" })).not.toBeInTheDocument();
  });

  it("rejects duplicate full models owned by another integration", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<OllamaSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={vi.fn()} />);

    await user.type(screen.getByLabelText("New full model for Ollama Integration"), "omniroute/test-chat");
    await user.click(screen.getByRole("button", { name: "Add full model" }));

    expect(screen.getByText("Full model omniroute/test-chat is already used by OmniRoute.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove omniroute/test-chat" })).not.toBeInTheDocument();
  });
});
