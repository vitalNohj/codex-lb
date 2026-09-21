import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { NvidiaSidecarSettings } from "@/features/settings/components/nvidia-sidecar-settings";
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
};

const ENABLED_SETTINGS: DashboardSettings = {
  ...BASE_SETTINGS,
  nvidiaSidecarEnabled: true,
};

function renderWithQueryClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe("NvidiaSidecarSettings", () => {
  it("labels the section as the NVIDIA integration", () => {
    renderWithQueryClient(<NvidiaSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={vi.fn()} />);

    expect(screen.getByRole("heading", { name: "NVIDIA Integration" })).toBeInTheDocument();
  });

  it("places the enable toggle above the setup callout and prefills the NVIDIA base URL", () => {
    renderWithQueryClient(<NvidiaSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={vi.fn()} />);

    const enable = screen.getByRole("switch", { name: "Enable NVIDIA Integration" });
    const docsLink = screen.getByRole("link", { name: "build.nvidia.com/settings" });
    expect(enable).not.toBeChecked();
    expect(enable.compareDocumentPosition(docsLink) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(docsLink).toHaveAttribute("target", "_blank");
    expect(docsLink).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getByLabelText(/Base URL/i)).toHaveValue("https://integrate.api.nvidia.com/v1");
  });

  it("does not render Save or Clear buttons", () => {
    renderWithQueryClient(<NvidiaSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={vi.fn()} />);

    expect(screen.queryByRole("button", { name: /^Save$/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Clear API key" })).not.toBeInTheDocument();
  });

  it("adds an API key and runs the connection test after the save", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    const testSpy = vi.fn();
    server.use(
      http.post("*/api/nvidia-sidecar/test", () => {
        testSpy();
        return HttpResponse.json({
          enabled: true,
          configured: true,
          status: "healthy",
          message: "NVIDIA reachable",
          baseUrl: "https://integrate.api.nvidia.com/v1",
          modelCount: 0,
          lastCheckedAt: "2026-01-01T00:00:00Z",
          models: [],
        });
      }),
    );
    renderWithQueryClient(<NvidiaSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={onSave} />);

    await user.type(screen.getByLabelText(/API key/), "new-key");
    await user.click(screen.getByRole("button", { name: "Add API key" }));

    await waitFor(() =>
      expect(onSave).toHaveBeenLastCalledWith(expect.objectContaining({ nvidiaSidecarApiKey: "new-key" })),
    );
    expect(screen.getByLabelText(/API key/)).toHaveValue("");
    await waitFor(() => expect(testSpy).toHaveBeenCalledTimes(1));
  });

  it("persists edited model prefixes immediately", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderWithQueryClient(<NvidiaSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={onSave} />);

    await user.click(screen.getByRole("button", { name: "Remove nvidia/" }));
    await user.type(screen.getByLabelText("New prefix for NVIDIA Integration"), "google/");
    await user.click(screen.getByRole("button", { name: "Add prefix" }));
    await user.type(screen.getByLabelText("New prefix for NVIDIA Integration"), "meta-llama/");
    await user.click(screen.getByRole("button", { name: "Add prefix" }));

    await waitFor(() =>
      expect(onSave).toHaveBeenLastCalledWith(
        expect.objectContaining({
          nvidiaSidecarModelPrefixes: [
            { prefix: "google/", strip: false },
            { prefix: "meta-llama/", strip: false },
          ],
        }),
      ),
    );
  });

  it("does not render a manual Test connection button", () => {
    renderWithQueryClient(<NvidiaSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={vi.fn()} />);

    expect(screen.queryByRole("button", { name: "Test connection" })).not.toBeInTheDocument();
  });

  it("adds a discovered model as a full model", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderWithQueryClient(<NvidiaSidecarSettings settings={ENABLED_SETTINGS} busy={false} onSave={onSave} />);

    await user.click(screen.getByRole("button", { name: /Discovered models/i }));
    await screen.findAllByText("z-ai/glm-5.3");
    await user.click(await screen.findByRole("button", { name: /Add full model z-ai\/glm-5.3/ }));

    expect(
      within(screen.getByLabelText("Configured full models for NVIDIA Integration")).getByText(
        "z-ai/glm-5.3",
      ),
    ).toBeInTheDocument();
  });

  it("keeps discovered models collapsed inside the configuration card above the timeout fields", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderWithQueryClient(<NvidiaSidecarSettings settings={ENABLED_SETTINGS} busy={false} onSave={onSave} />);

    const disclosure = await screen.findByRole("button", { name: /Discovered models/i });
    const cacheTtlField = screen.getByLabelText(/Model cache TTL/);

    expect(disclosure.compareDocumentPosition(cacheTtlField) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(disclosure).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByLabelText("Search models")).not.toBeInTheDocument();

    await user.click(disclosure);

    expect(disclosure).toHaveAttribute("aria-expanded", "true");
    expect(await screen.findByLabelText("Search models")).toBeInTheDocument();
    await screen.findAllByText("z-ai/glm-5.3");
    await user.click(await screen.findByRole("button", { name: /Add full model z-ai\/glm-5.3/ }));
    expect(
      within(screen.getByLabelText("Configured full models for NVIDIA Integration")).getByText(
        "z-ai/glm-5.3",
      ),
    ).toBeInTheDocument();
  });
});
