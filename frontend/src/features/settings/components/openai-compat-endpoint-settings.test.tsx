import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { OpenAICompatEndpointSettings } from "@/features/settings/components/openai-compat-endpoint-settings";
import type { DashboardSettings, OpenAICompatEndpoint } from "@/features/settings/schemas";

const ENDPOINT_ID = "2c9b8f3a-1e4d-4b7a-9c11-7a0e4d2b1c0a";

const VAST_ENDPOINT: OpenAICompatEndpoint = {
  id: ENDPOINT_ID,
  name: "Vast",
  enabled: false,
  baseUrl: "https://openai.vast.ai/demo/v1",
  apiKeyConfigured: false,
  modelPrefixes: [{ prefix: "vast/", strip: true }],
  fullModels: [],
  connectTimeoutSeconds: 8,
  requestTimeoutSeconds: 600,
  modelsCacheTtlSeconds: 60,
  defaultReasoningEffort: null,
  lastHealthStatus: "healthy",
  lastHealthMessage: "Vast reachable",
  lastCheckedAt: "2026-01-01T00:00:00Z",
  lastModelCount: 1,
};

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
  customAliasCatalog: {},
  limitWarmupEnabled: false,
  limitWarmupWindows: "both",
  limitWarmupModel: "auto",
  limitWarmupPrompt: "Say OK.",
  limitWarmupCooldownSeconds: 3600,
  limitWarmupMinAvailablePercent: 100,
  claudeSidecarEnabled: false,
  nvidiaSidecarEnabled: false,
  nvidiaSidecarBaseUrl: "https://integrate.api.nvidia.com/v1",
  nvidiaSidecarApiKeyConfigured: true,
  nvidiaSidecarModelPrefixes: [{ prefix: "nvidia/", strip: true }],
  nvidiaSidecarFullModels: [],
  nvidiaSidecarConnectTimeoutSeconds: 8,
  nvidiaSidecarRequestTimeoutSeconds: 600,
  nvidiaSidecarModelsCacheTtlSeconds: 60,
  orcarouterSidecarEnabled: false,
  orcarouterSidecarBaseUrl: "https://api.orcarouter.ai/v1",
  orcarouterSidecarApiKeyConfigured: false,
  orcarouterSidecarModelPrefixes: [{ prefix: "orcarouter/", strip: false }],
  orcarouterSidecarFullModels: [],
  orcarouterSidecarConnectTimeoutSeconds: 8,
  orcarouterSidecarRequestTimeoutSeconds: 600,
  orcarouterSidecarModelsCacheTtlSeconds: 60,
  nvidiaSidecarLastHealthStatus: "healthy",
  nvidiaSidecarLastHealthMessage: "NVIDIA reachable",
  nvidiaSidecarLastCheckedAt: "2026-01-01T00:00:00Z",
  nvidiaSidecarLastModelCount: 1,
  openaiCompatEndpoints: [VAST_ENDPOINT],
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
  openaiCompatEndpoints: [{ ...VAST_ENDPOINT, enabled: true }],
};

function renderWithQueryClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe("OpenAICompatEndpointSettings", () => {
  it("labels the section with the operator name", () => {
    renderWithQueryClient(
      <OpenAICompatEndpointSettings endpoint={VAST_ENDPOINT} settings={BASE_SETTINGS} busy={false} onSave={vi.fn()} />,
    );

    expect(screen.getByRole("heading", { name: "Vast" })).toBeInTheDocument();
  });

  it("places the enable toggle above the setup callout and prefills the Vast base URL", () => {
    renderWithQueryClient(
      <OpenAICompatEndpointSettings endpoint={VAST_ENDPOINT} settings={BASE_SETTINGS} busy={false} onSave={vi.fn()} />,
    );

    const enable = screen.getByRole("switch", { name: "Enable Vast" });
    const callout = screen.getByText(/https:\/\/openai\.vast\.ai\/<ENDPOINT_NAME>\/v1/);
    expect(enable).not.toBeChecked();
    expect(enable.compareDocumentPosition(callout) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByLabelText(/Base URL/i)).toHaveValue("https://openai.vast.ai/demo/v1");
    expect(screen.getByPlaceholderText("Optional API key")).toBeInTheDocument();
  });

  it("does not render Save or Clear buttons", () => {
    renderWithQueryClient(
      <OpenAICompatEndpointSettings endpoint={VAST_ENDPOINT} settings={BASE_SETTINGS} busy={false} onSave={vi.fn()} />,
    );

    expect(screen.queryByRole("button", { name: /^Save$/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Clear API key" })).not.toBeInTheDocument();
  });

  it("does not render a manual Test connection button", () => {
    renderWithQueryClient(
      <OpenAICompatEndpointSettings endpoint={VAST_ENDPOINT} settings={BASE_SETTINGS} busy={false} onSave={vi.fn()} />,
    );

    expect(screen.queryByRole("button", { name: "Test connection" })).not.toBeInTheDocument();
  });

  it("persists edited model prefixes immediately", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderWithQueryClient(
      <OpenAICompatEndpointSettings endpoint={VAST_ENDPOINT} settings={BASE_SETTINGS} busy={false} onSave={onSave} />,
    );

    await user.click(screen.getByRole("button", { name: "Remove vast/" }));
    await user.type(screen.getByLabelText("New prefix for Vast"), "google/");
    await user.click(screen.getByRole("button", { name: "Add prefix" }));
    await user.type(screen.getByLabelText("New prefix for Vast"), "meta-llama/");
    await user.click(screen.getByRole("button", { name: "Add prefix" }));

    await waitFor(() =>
      expect(onSave).toHaveBeenLastCalledWith(
        expect.objectContaining({
          openaiCompatEndpoints: [
            expect.objectContaining({
              id: ENDPOINT_ID,
              modelPrefixes: [
                { prefix: "google/", strip: false },
                { prefix: "meta-llama/", strip: false },
              ],
            }),
          ],
        }),
      ),
    );
  });

  it("adds a discovered model as a full model", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderWithQueryClient(
      <OpenAICompatEndpointSettings
        endpoint={{ ...VAST_ENDPOINT, enabled: true }}
        settings={ENABLED_SETTINGS}
        busy={false}
        onSave={onSave}
      />,
    );

    await user.click(screen.getByRole("button", { name: /Discovered models/i }));
    await screen.findAllByText("vast-llama");
    await user.click(await screen.findByRole("button", { name: /Add full model vast-llama/ }));

    expect(within(screen.getByLabelText("Configured full models for Vast")).getByText("vast-llama")).toBeInTheDocument();
  });

  it("keeps discovered models collapsed inside the model routing panel", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderWithQueryClient(
      <OpenAICompatEndpointSettings
        endpoint={{ ...VAST_ENDPOINT, enabled: true }}
        settings={ENABLED_SETTINGS}
        busy={false}
        onSave={onSave}
      />,
    );

    const disclosure = await screen.findByRole("button", { name: /Discovered models/i });
    expect(screen.getByRole("region", { name: "Model routing" })).toContainElement(disclosure);
    expect(disclosure).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByLabelText("Search models")).not.toBeInTheDocument();

    await user.click(disclosure);

    expect(disclosure).toHaveAttribute("aria-expanded", "true");
    expect(await screen.findByLabelText("Search models")).toBeInTheDocument();
    await screen.findAllByText("vast-llama");
    await user.click(await screen.findByRole("button", { name: /Add full model vast-llama/ }));
    expect(within(screen.getByLabelText("Configured full models for Vast")).getByText("vast-llama")).toBeInTheDocument();
  });

  it("removes the stored endpoint", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    const onRemoved = vi.fn();
    renderWithQueryClient(
      <OpenAICompatEndpointSettings
        endpoint={VAST_ENDPOINT}
        settings={BASE_SETTINGS}
        busy={false}
        onSave={onSave}
        onRemoved={onRemoved}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Remove" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledWith({ openaiCompatEndpoints: [] }));
    expect(onRemoved).toHaveBeenCalledTimes(1);
  });
});
