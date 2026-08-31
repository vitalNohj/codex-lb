import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { AppHeader } from "@/components/layout/app-header";
import { AccountTypeFilterToggle } from "@/features/dashboard/components/account-type-filter-toggle";
import { SidecarIntegrationsCard } from "@/features/settings/components/sidecar-integrations";
import { buildSettingsUpdateRequest } from "@/features/settings/payload";
import type { DashboardSettings } from "@/features/settings/schemas";
import {
  OMNIROUTE_ENABLED,
  isDisabledCapabilityAccount,
  isDisabledCapabilityRequestSource,
} from "@/lib/product-capabilities";

const BASE_SETTINGS: DashboardSettings = {
  stickyThreadsEnabled: true,
  upstreamStreamTransport: "default",
  upstreamProxyRoutingEnabled: false,
  upstreamProxyDefaultPoolId: null,
  preferEarlierResetAccounts: true,
  preferEarlierResetWindow: "secondary",
  routingStrategy: "capacity_weighted",
  relativeAvailabilityPower: 2,
  relativeAvailabilityTopK: 5,
  singleAccountId: null,
  openaiCacheAffinityMaxAgeSeconds: 300,
  dashboardSessionTtlSeconds: 43200,
  stickyReallocationBudgetThresholdPct: 95,
  stickyReallocationPrimaryBudgetThresholdPct: 95,
  stickyReallocationSecondaryBudgetThresholdPct: 100,
  additionalQuotaRoutingPolicies: {},
  additionalQuotaPolicies: [],
  customAliasCatalog: {},
  warmupModel: "gpt-5.4-mini",
  importWithoutOverwrite: true,
  totpRequiredOnLogin: false,
  totpConfigured: false,
  apiKeyAuthEnabled: true,
  limitWarmupEnabled: false,
  limitWarmupWindows: "both",
  limitWarmupModel: "auto",
  limitWarmupPrompt: "Say OK.",
  limitWarmupCooldownSeconds: 3600,
  limitWarmupMinAvailablePercent: 100,
  weeklyPaceWorkingDays: "0,1,2,3,4,5,6",
  omnirouteSidecarEnabled: false,
  omnirouteSidecarBaseUrl: "http://127.0.0.1:20128/v1",
  omnirouteSidecarApiKeyConfigured: true,
  omnirouteSidecarModelPrefixes: [],
  omnirouteSidecarFullModels: ["omniroute/test-chat"],
  omnirouteSidecarSelectedModels: ["omniroute/test-chat"],
  omnirouteSidecarConnectTimeoutSeconds: 8,
  omnirouteSidecarRequestTimeoutSeconds: 600,
  omnirouteSidecarModelsCacheTtlSeconds: 60,
  orcarouterSidecarEnabled: false,
  orcarouterSidecarBaseUrl: "https://api.orcarouter.ai/v1",
  orcarouterSidecarApiKeyConfigured: false,
  orcarouterSidecarModelPrefixes: [{ prefix: "orcarouter/", strip: false }],
  orcarouterSidecarFullModels: [],
  orcarouterSidecarConnectTimeoutSeconds: 8,
  orcarouterSidecarRequestTimeoutSeconds: 600,
  orcarouterSidecarModelsCacheTtlSeconds: 60,
  omnirouteSidecarLastHealthStatus: "healthy",
  omnirouteSidecarLastHealthMessage: "OmniRoute sidecar reachable",
  omnirouteSidecarLastCheckedAt: "2026-01-01T00:00:00Z",
  omnirouteSidecarLastModelCount: 1,
  guestAccessEnabled: false,
  prohibitFastMode: false,
  httpDownstreamTransportPolicy: "smart",
  proxyAccountResponseCreateLimit: 4,
  proxyAccountStreamLimit: 8,
  proxyAccountStreamRecoveryReserve: 1,
  hideUpstreamQuotaFromApiKeys: false,
  limitWarmupExhaustedThresholdPercent: 99,
  limitWarmupIdleThresholdPercent: 1,
  weeklyPaceSmoothingMinutes: 30,
  limitWarmupStaggeredIdleEnabled: false,
  showResetCreditBadges: true,
  autoRedeemResetCreditsBeforeExpiry: false,
  showResetCreditExpiryBadge: true,
  requestLogRetentionDays: 0,
  usageHistoryRetentionDays: 0,
  requestLogRetentionOverrideDays: null,
  usageHistoryRetentionOverrideDays: null,
  guestPasswordConfigured: false,
};

const ENABLED_SETTINGS: DashboardSettings = {
  ...BASE_SETTINGS,
  omnirouteSidecarEnabled: true,
};

function renderWithQueryClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

/**
 * OmniRoute is disabled as a product integration. The implementation module is
 * retained dormant for a future re-enable, so these tests assert the *product*
 * behaviour: no user-reachable surface exposes OmniRoute, and no OmniRoute
 * field is ever written, even when stored settings still enable it.
 */
describe("OmniRoute disabled as a product integration", () => {
  it("declares the capability disabled", () => {
    expect(OMNIROUTE_ENABLED).toBe(false);
  });

  it("renders no OmniRoute tab in External Integrations, even when stored settings enable it", () => {
    renderWithQueryClient(
      <SidecarIntegrationsCard settings={ENABLED_SETTINGS} busy={false} onSave={vi.fn()} />,
    );

    expect(screen.queryByRole("tab", { name: /omniroute/i })).toBeNull();
    expect(screen.queryByText(/omniroute/i)).toBeNull();
  });

  it("renders no OmniRoute navigation entry", () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/dashboard"]}>
          <AppHeader onLogout={vi.fn()} />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(screen.queryAllByRole("link", { name: /omniroute/i })).toHaveLength(0);
  });

  it("strips every OmniRoute field from a settings update, including explicit patches", () => {
    const payload = buildSettingsUpdateRequest(ENABLED_SETTINGS, {
      omnirouteSidecarEnabled: true,
      omnirouteSidecarApiKey: "should-never-be-sent",
      omnirouteSidecarFullModels: ["omniroute/test-chat"],
      ollamaSidecarEnabled: true,
    });

    for (const key of Object.keys(payload)) {
      expect(key.startsWith("omniroute")).toBe(false);
    }
    // A neighbouring integration in the same patch is still written.
    expect(payload.ollamaSidecarEnabled).toBe(true);
  });

  it("hides OmniRoute accounts from the account-type filter", () => {
    render(
      <AccountTypeFilterToggle
        value={{ codex: true, cliproxy: true, openrouter: true, orcarouter: true, omniroute: true }}
        onToggle={vi.fn()}
      />,
    );

    expect(screen.queryByRole("button", { name: /omniroute/i })).toBeNull();
  });

  it("classifies an OmniRoute account as a disabled capability", () => {
    expect(isDisabledCapabilityAccount({ provider: "omniroute" })).toBe(true);
    // Neighbouring providers stay enabled.
    for (const provider of ["openrouter", "orcarouter", "claude", "ollama"]) {
      expect(isDisabledCapabilityAccount({ provider })).toBe(false);
    }
  });

  it("classifies an OmniRoute request-log source as a disabled capability", () => {
    expect(isDisabledCapabilityRequestSource("omniroute_sidecar")).toBe(true);
    for (const source of ["openrouter_sidecar", "orcarouter_sidecar", "claude_sidecar", "ollama_sidecar"]) {
      expect(isDisabledCapabilityRequestSource(source)).toBe(false);
    }
  });
});
