import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
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
  customAliasCatalog: {},
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
  nvidiaSidecarEnabled: false,
  nvidiaSidecarBaseUrl: "https://integrate.api.nvidia.com/v1",
  nvidiaSidecarApiKeyConfigured: false,
  nvidiaSidecarModelPrefixes: [],
  nvidiaSidecarFullModels: [],
  nvidiaSidecarConnectTimeoutSeconds: 8,
  nvidiaSidecarRequestTimeoutSeconds: 600,
  nvidiaSidecarModelsCacheTtlSeconds: 60,
  omnirouteSidecarEnabled: false,
  omnirouteSidecarBaseUrl: "http://127.0.0.1:20128/v1",
  omnirouteSidecarApiKeyConfigured: true,
  omnirouteSidecarModelPrefixes: [],
  omnirouteSidecarFullModels: ["omniroute/test-chat"],
  omnirouteSidecarSelectedModels: ["omniroute/test-chat"],
  omnirouteSidecarConnectTimeoutSeconds: 8,
  omnirouteSidecarRequestTimeoutSeconds: 600,
  omnirouteSidecarModelsCacheTtlSeconds: 60,
  ollamaSidecarEnabled: false,
  ollamaSidecarBaseUrl: "https://ollama.com",
  ollamaSidecarApiKeyConfigured: true,
  ollamaSidecarModelPrefixes: [],
  ollamaSidecarFullModels: ["gpt-oss:120b-cloud"],
  ollamaSidecarConnectTimeoutSeconds: 8,
  ollamaSidecarRequestTimeoutSeconds: 600,
  ollamaSidecarModelsCacheTtlSeconds: 60,
  orcarouterSidecarEnabled: false,
  orcarouterSidecarBaseUrl: "https://api.orcarouter.ai/v1",
  orcarouterSidecarApiKeyConfigured: false,
  orcarouterSidecarModelPrefixes: [{ prefix: "orcarouter/", strip: false }],
  orcarouterSidecarFullModels: [],
  orcarouterSidecarConnectTimeoutSeconds: 8,
  orcarouterSidecarRequestTimeoutSeconds: 600,
  orcarouterSidecarModelsCacheTtlSeconds: 60,
  opencodeGoSidecarEnabled: false,
  opencodeGoSidecarBaseUrl: "https://opencode.ai/zen/go/v1",
  opencodeGoSidecarApiKeyConfigured: false,
  opencodeGoSidecarModelPrefixes: [{ prefix: "opencode-go/", strip: true }],
  opencodeGoSidecarFullModels: [],
  opencodeGoSidecarConnectTimeoutSeconds: 8,
  opencodeGoSidecarRequestTimeoutSeconds: 600,
  opencodeGoSidecarModelsCacheTtlSeconds: 60,
  openaiCompatEndpoints: [],
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
} as DashboardSettings;

function renderCard(settings: DashboardSettings, locationHash?: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <SidecarIntegrationsCard
        settings={settings}
        busy={false}
        onSave={vi.fn()}
        locationHash={locationHash}
      />
    </QueryClientProvider>,
  );
}

describe("SidecarIntegrationsCard", () => {
  it("renders one unified card with a tab per integration", () => {
    renderCard(BASE_SETTINGS);

    expect(screen.getByRole("heading", { name: "External Integrations" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /CLIProxyAPI/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /OpenRouter/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /NVIDIA/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /OrcaRouter/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Ollama/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /OpenCode Go/ })).toBeInTheDocument();
  });

  // Tab order is the locked surface contract, matching SIDECAR_PROVIDER_ORDER
  // on the backend minus capabilities disabled at the product level.
  it("orders the integration tabs to match the sidecar provider order", () => {
    renderCard(BASE_SETTINGS);

    expect(screen.getAllByRole("tab").map((tab) => tab.textContent?.trim())).toEqual([
      "CLIProxyAPI",
      "OpenRouter",
      "NVIDIA",
      "OrcaRouter",
      "Ollama",
      "OpenCode Go",
    ]);
  });

  it("offers no OmniRoute tab or settings even when stored settings enable it", () => {
    renderCard({
      ...BASE_SETTINGS,
      omnirouteSidecarEnabled: true,
      omnirouteSidecarApiKeyConfigured: true,
    });

    expect(screen.queryByRole("tab", { name: /omniroute/i })).toBeNull();
    expect(screen.queryByText(/omniroute/i)).toBeNull();
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

  it("defaults to the Ollama tab when only Ollama is enabled", () => {
    renderCard({
      ...BASE_SETTINGS,
      openrouterSidecarEnabled: false,
      ollamaSidecarEnabled: true,
    });

    expect(screen.getByRole("tab", { name: "Ollama (enabled)" })).toHaveAttribute(
      "data-state",
      "active",
    );
    expect(screen.getByRole("switch", { name: "Enable Ollama Integration" })).toBeInTheDocument();
  });

  it("switches the visible integration when another tab is selected", async () => {
    const user = userEvent.setup();
    renderCard(BASE_SETTINGS);

    // OpenRouter active by default -> its enable toggle is visible.
    expect(screen.getByRole("switch", { name: "Enable OpenRouter Integration" })).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "CLIProxyAPI" }));

    expect(screen.getByRole("switch", { name: "Enable CLI Proxy integration" })).toBeInTheDocument();
  });

  it("shows the Ollama integration when the Ollama tab is selected", async () => {
    const user = userEvent.setup();
    renderCard(BASE_SETTINGS);

    await user.click(screen.getByRole("tab", { name: "Ollama" }));

    expect(screen.getByRole("switch", { name: "Enable Ollama Integration" })).toBeInTheDocument();
  });

  it("shows the OrcaRouter integration when the OrcaRouter tab is selected", async () => {
    const user = userEvent.setup();
    renderCard(BASE_SETTINGS);

    await user.click(screen.getByRole("tab", { name: "OrcaRouter" }));

    expect(screen.getByRole("switch", { name: "Enable OrcaRouter Integration" })).toBeInTheDocument();
  });

  it("shows the OpenCode Go integration when its tab is selected", async () => {
    const user = userEvent.setup();
    renderCard(BASE_SETTINGS);

    await user.click(screen.getByRole("tab", { name: "OpenCode Go" }));

    expect(
      screen.getByRole("switch", { name: "Enable OpenCode Go Integration" }),
    ).toBeInTheDocument();
  });

  // The Accounts page links to /settings#<section-id>. Inactive tab panels are
  // unmounted, so the hash must select the owning tab or the link lands on a
  // page with nothing revealed.
  describe("deep links from the Accounts page", () => {
    it.each([
      ["#opencode-go-sidecar", "OpenCode Go", "Enable OpenCode Go Integration"],
      ["#nvidia-sidecar", "NVIDIA", "Enable NVIDIA Integration"],
      ["#orcarouter-sidecar", "OrcaRouter", "Enable OrcaRouter Integration"],
      ["#ollama-sidecar", "Ollama", "Enable Ollama Integration"],
      ["#claude-sidecar", "CLIProxyAPI", "Enable CLI Proxy integration"],
    ])("%s selects the %s tab over the first-enabled default", (hash, tabLabel, switchName) => {
      // OpenRouter is the enabled integration, so the default would win here.
      renderCard(BASE_SETTINGS, hash);

      expect(screen.getByRole("tab", { name: new RegExp(tabLabel) })).toHaveAttribute(
        "data-state",
        "active",
      );
      expect(screen.getByRole("switch", { name: switchName })).toBeInTheDocument();
    });

    it("ignores a hash that matches no integration", () => {
      renderCard(BASE_SETTINGS, "#firewall");

      expect(screen.getByRole("tab", { name: "OpenRouter (enabled)" })).toHaveAttribute(
        "data-state",
        "active",
      );
    });

    it("keeps the first-enabled default when there is no hash", () => {
      renderCard(BASE_SETTINGS);

      expect(screen.getByRole("tab", { name: "OpenRouter (enabled)" })).toHaveAttribute(
        "data-state",
        "active",
      );
    });
  });

  it("defaults to the OpenCode Go tab when only OpenCode Go is enabled", () => {
    renderCard({
      ...BASE_SETTINGS,
      openrouterSidecarEnabled: false,
      opencodeGoSidecarEnabled: true,
    });

    expect(screen.getByRole("tab", { name: "OpenCode Go (enabled)" })).toHaveAttribute(
      "data-state",
      "active",
    );
  });

  it("offers a + control that is not itself a tab", () => {
    renderCard(BASE_SETTINGS);

    expect(screen.getByRole("button", { name: "Add OpenAI-compatible endpoint" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /Add OpenAI/ })).toBeNull();
  });

  it("creates a named OpenAI-compat tab from the add dialog", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    vi.spyOn(crypto, "randomUUID").mockReturnValue("2c9b8f3a-1e4d-4b7a-9c11-7a0e4d2b1c0a");
    render(
      <QueryClientProvider client={queryClient}>
        <SidecarIntegrationsCard settings={BASE_SETTINGS} busy={false} onSave={onSave} />
      </QueryClientProvider>,
    );

    await user.click(screen.getByRole("button", { name: "Add OpenAI-compatible endpoint" }));
    await user.type(screen.getByLabelText("Name"), "Vast");
    await user.type(screen.getByLabelText("Base URL"), "https://openai.vast.ai/demo/v1");
    await user.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith(
        expect.objectContaining({
          openaiCompatEndpoints: [
            expect.objectContaining({
              id: "2c9b8f3a-1e4d-4b7a-9c11-7a0e4d2b1c0a",
              name: "Vast",
              enabled: false,
              baseUrl: "https://openai.vast.ai/demo/v1",
            }),
          ],
        }),
      ),
    );
  });

  it("renders a stored OpenAI-compat endpoint as a tab after first-class integrations", () => {
    renderCard({
      ...BASE_SETTINGS,
      openaiCompatEndpoints: [
        {
          id: "2c9b8f3a-1e4d-4b7a-9c11-7a0e4d2b1c0a",
          name: "Vast",
          enabled: true,
          baseUrl: "https://openai.vast.ai/demo/v1",
          apiKeyConfigured: false,
          modelPrefixes: [],
          fullModels: ["vast-llama"],
          connectTimeoutSeconds: 8,
          requestTimeoutSeconds: 600,
          modelsCacheTtlSeconds: 60,
          defaultReasoningEffort: null,
          lastHealthStatus: null,
          lastHealthMessage: null,
          lastCheckedAt: null,
          lastModelCount: null,
        },
      ],
    } as DashboardSettings);

    expect(screen.getAllByRole("tab").map((tab) => tab.textContent?.trim())).toEqual([
      "CLIProxyAPI",
      "OpenRouter",
      "NVIDIA",
      "OrcaRouter",
      "Ollama",
      "OpenCode Go",
      "Vast",
    ]);
  });

  it("deep-links an OpenAI-compat endpoint hash to that tab", () => {
    renderCard(
      {
        ...BASE_SETTINGS,
        openaiCompatEndpoints: [
          {
            id: "2c9b8f3a-1e4d-4b7a-9c11-7a0e4d2b1c0a",
            name: "Vast",
            enabled: false,
            baseUrl: "https://openai.vast.ai/demo/v1",
            apiKeyConfigured: false,
            modelPrefixes: [],
            fullModels: [],
            connectTimeoutSeconds: 8,
            requestTimeoutSeconds: 600,
            modelsCacheTtlSeconds: 60,
            defaultReasoningEffort: null,
            lastHealthStatus: null,
            lastHealthMessage: null,
            lastCheckedAt: null,
            lastModelCount: null,
          },
        ],
      } as DashboardSettings,
      "#openai-compat-2c9b8f3a-1e4d-4b7a-9c11-7a0e4d2b1c0a",
    );

    expect(screen.getByRole("tab", { name: "Vast" })).toHaveAttribute("data-state", "active");
    expect(screen.getByRole("switch", { name: "Enable Vast" })).toBeInTheDocument();
  });

  it("disables the + control at 32 endpoints", () => {
    const endpoints = Array.from({ length: 32 }, (_, index) => ({
      id: `00000000-0000-4000-8000-${String(index).padStart(12, "0")}`,
      name: `EP${index}`,
      enabled: false,
      baseUrl: "http://127.0.0.1:8000/v1",
      apiKeyConfigured: false,
      modelPrefixes: [],
      fullModels: [],
      connectTimeoutSeconds: 8,
      requestTimeoutSeconds: 600,
      modelsCacheTtlSeconds: 60,
      defaultReasoningEffort: null,
      lastHealthStatus: null,
      lastHealthMessage: null,
      lastCheckedAt: null,
      lastModelCount: null,
    }));
    renderCard({ ...BASE_SETTINGS, openaiCompatEndpoints: endpoints } as DashboardSettings);

    expect(screen.getByRole("button", { name: "Add OpenAI-compatible endpoint" })).toBeDisabled();
  });
});
