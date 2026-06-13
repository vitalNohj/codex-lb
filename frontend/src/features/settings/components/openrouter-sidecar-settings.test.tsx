import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { OpenRouterSidecarSettings } from "@/features/settings/components/openrouter-sidecar-settings";
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
  openrouterSidecarEnabled: false,
  openrouterSidecarBaseUrl: "https://openrouter.ai/api/v1",
  openrouterSidecarApiKeyConfigured: true,
  openrouterSidecarModelPrefixes: ["deepseek/"],
  openrouterSidecarConnectTimeoutSeconds: 8,
  openrouterSidecarRequestTimeoutSeconds: 600,
  openrouterSidecarModelsCacheTtlSeconds: 60,
  openrouterSidecarLastHealthStatus: "healthy",
  openrouterSidecarLastHealthMessage: "OpenRouter sidecar reachable",
  openrouterSidecarLastCheckedAt: "2026-01-01T00:00:00Z",
  openrouterSidecarLastModelCount: 1,
};

function renderWithQueryClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe("OpenRouterSidecarSettings", () => {
  it("labels the section as the OpenRouter integration", () => {
    renderWithQueryClient(<OpenRouterSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={vi.fn()} />);

    expect(screen.getByRole("heading", { name: "OpenRouter Integration" })).toBeInTheDocument();
  });

  it("saves integration config and can clear a configured key", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderWithQueryClient(<OpenRouterSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={onSave} />);

    await user.click(screen.getByRole("switch", { name: "Enable OpenRouter Integration" }));
    expect(onSave).toHaveBeenLastCalledWith(expect.objectContaining({ openrouterSidecarEnabled: true }));

    await user.type(screen.getByLabelText(/API key/), "new-key");
    await user.click(screen.getByRole("button", { name: /^Save$/ }));

    expect(onSave).toHaveBeenLastCalledWith(
      expect.objectContaining({
        openrouterSidecarApiKey: "new-key",
        openrouterSidecarModelPrefixes: ["deepseek/"],
        openrouterSidecarBaseUrl: "https://openrouter.ai/api/v1",
      }),
    );

    await user.click(screen.getByRole("button", { name: "Clear API key" }));
    expect(onSave).toHaveBeenLastCalledWith(expect.objectContaining({ openrouterSidecarClearApiKey: true }));
  });

  it("saves edited model prefixes", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderWithQueryClient(<OpenRouterSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={onSave} />);

    const prefixInput = screen.getByLabelText(/Model prefixes/);
    await user.clear(prefixInput);
    await user.type(prefixInput, "google/, meta-llama/");
    await user.click(screen.getByRole("button", { name: /^Save$/ }));

    expect(onSave).toHaveBeenLastCalledWith(
      expect.objectContaining({ openrouterSidecarModelPrefixes: ["google/", "meta-llama/"] }),
    );
  });

  it("does not render a manual Test connection button", () => {
    renderWithQueryClient(<OpenRouterSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={vi.fn()} />);

    expect(screen.queryByRole("button", { name: "Test connection" })).not.toBeInTheDocument();
  });

  it("runs the connection test after a successful save", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    const testSpy = vi.fn();
    server.use(
      http.post("*/api/openrouter-sidecar/test", () => {
        testSpy();
        return HttpResponse.json({
          enabled: true,
          configured: true,
          status: "healthy",
          message: "OpenRouter sidecar reachable",
          baseUrl: "https://openrouter.ai/api/v1",
          modelCount: 0,
          lastCheckedAt: "2026-01-01T00:00:00Z",
          models: [],
        });
      }),
    );
    renderWithQueryClient(<OpenRouterSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={onSave} />);

    await user.click(screen.getByRole("button", { name: /^Save$/ }));

    await waitFor(() => expect(testSpy).toHaveBeenCalledTimes(1));
  });

  it("adds a provider prefix from popular models", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderWithQueryClient(<OpenRouterSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={onSave} />);

    await user.click(screen.getByRole("button", { name: "Add prefix google/" }));

    expect(screen.getByLabelText(/Model prefixes/)).toHaveValue("deepseek/, google/");
  });
});
