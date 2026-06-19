import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SidecarIntegrationsCard } from "@/features/settings/components/sidecar-integrations";
import type { DashboardSettings } from "@/features/settings/schemas";

const BASE_SETTINGS = {
  stickyThreadsEnabled: true,
  upstreamStreamTransport: "default",
  upstreamProxyRoutingEnabled: false,
  upstreamProxyDefaultPoolId: null,
  preferEarlierResetAccounts: false,
  preferEarlierResetWindow: "secondary",
  routingStrategy: "usage_weighted",
  relativeAvailabilityPower: 2,
  relativeAvailabilityTopK: 5,
  singleAccountId: null,
  weeklyPaceWorkingDays: "0,1,2,3,4,5,6",
  openaiCacheAffinityMaxAgeSeconds: 300,
  dashboardSessionTtlSeconds: 43200,
  stickyReallocationBudgetThresholdPct: 95,
  stickyReallocationPrimaryBudgetThresholdPct: 95,
  stickyReallocationSecondaryBudgetThresholdPct: 100,
  warmupModel: "gpt-5.4-mini",
  importWithoutOverwrite: false,
  totpRequiredOnLogin: false,
  totpConfigured: true,
  apiKeyAuthEnabled: true,
  limitWarmupEnabled: false,
  limitWarmupWindows: "both",
  limitWarmupModel: "auto",
  limitWarmupPrompt: "Say OK.",
  limitWarmupCooldownSeconds: 3600,
  limitWarmupMinAvailablePercent: 100,
  additionalQuotaRoutingPolicies: {},
  additionalQuotaPolicies: [],
  claudeSidecarEnabled: false,
  claudeSidecarBaseUrl: "http://127.0.0.1:8317",
  claudeSidecarApiKeyConfigured: true,
  claudeSidecarModelPrefixes: [{ prefix: "claude", strip: false }],
  claudeSidecarFullModels: [],
  claudeSidecarConnectTimeoutSeconds: 8,
  claudeSidecarRequestTimeoutSeconds: 600,
  claudeSidecarModelsCacheTtlSeconds: 60,
  claudeSidecarManagementKeyConfigured: false,
  claudeSidecarQuotaPollIntervalSeconds: 60,
  claudeSidecarAuthPlans: [],
  claudeSidecarUsagePollIntervalSeconds: 15,
  claudeSidecarUsageQueueBatchSize: 100,
  claudeSidecarUsageCollectionEnabled: true,
  openrouterSidecarEnabled: true,
  openrouterSidecarBaseUrl: "https://openrouter.ai/api/v1",
  openrouterSidecarApiKeyConfigured: true,
  openrouterSidecarModelPrefixes: [{ prefix: "deepseek/", strip: false }],
  openrouterSidecarFullModels: [],
  openrouterSidecarConnectTimeoutSeconds: 8,
  openrouterSidecarRequestTimeoutSeconds: 600,
  openrouterSidecarModelsCacheTtlSeconds: 60,
  omnirouteSidecarEnabled: false,
  omnirouteSidecarBaseUrl: "http://127.0.0.1:20128/v1",
  omnirouteSidecarApiKeyConfigured: true,
  omnirouteSidecarModelPrefixes: [],
  omnirouteSidecarFullModels: ["omniroute/test-chat"],
  omnirouteSidecarSelectedModels: ["omniroute/test-chat"],
  omnirouteSidecarConnectTimeoutSeconds: 8,
  omnirouteSidecarRequestTimeoutSeconds: 600,
  omnirouteSidecarModelsCacheTtlSeconds: 60,
} as DashboardSettings;

function renderCard(settings: DashboardSettings) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <SidecarIntegrationsCard settings={settings} busy={false} onSave={vi.fn()} />
    </QueryClientProvider>,
  );
}

describe("SidecarIntegrationsCard", () => {
  it("renders one unified card with a tab per integration", () => {
    renderCard(BASE_SETTINGS);

    expect(screen.getByRole("heading", { name: "External Integrations" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /CLIProxyAPI/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /OpenRouter/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /OmniRoute/ })).toBeInTheDocument();
  });

  it("defaults to the first enabled integration's tab", () => {
    renderCard(BASE_SETTINGS);

    // Only OpenRouter is enabled in BASE_SETTINGS, so its tab is selected.
    expect(screen.getByRole("tab", { name: "OpenRouter (enabled)" })).toHaveAttribute(
      "data-state",
      "active",
    );
    expect(screen.getByRole("tab", { name: "CLIProxyAPI" })).toHaveAttribute("data-state", "inactive");
  });

  it("falls back to the first tab when no integration is enabled", () => {
    renderCard({
      ...BASE_SETTINGS,
      openrouterSidecarEnabled: false,
    });

    expect(screen.getByRole("tab", { name: "CLIProxyAPI" })).toHaveAttribute("data-state", "active");
  });

  it("switches the visible integration when another tab is selected", async () => {
    const user = userEvent.setup();
    renderCard(BASE_SETTINGS);

    // OpenRouter active by default -> its enable toggle is visible.
    expect(screen.getByRole("switch", { name: "Enable OpenRouter Integration" })).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "CLIProxyAPI" }));

    expect(screen.getByRole("switch", { name: "Enable CLI Proxy integration" })).toBeInTheDocument();
  });
});
