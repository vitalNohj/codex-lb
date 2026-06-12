import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { OpenRouterSidecarSettings } from "@/features/settings/components/openrouter-sidecar-settings";
import type { DashboardSettings } from "@/features/settings/schemas";

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
  it("saves sidecar config and can clear a configured key", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderWithQueryClient(<OpenRouterSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={onSave} />);

    await user.click(screen.getByRole("switch"));
    expect(onSave).toHaveBeenLastCalledWith(expect.objectContaining({ openrouterSidecarEnabled: true }));

    await user.type(screen.getByPlaceholderText(/Configured — enter to replace/), "new-key");
    await user.click(screen.getByRole("button", { name: "Save OpenRouter settings" }));

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
});
