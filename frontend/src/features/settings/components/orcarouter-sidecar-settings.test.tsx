import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { OrcaRouterSidecarSettings } from "@/features/settings/components/orcarouter-sidecar-settings";
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
  orcarouterSidecarEnabled: false,
  orcarouterSidecarBaseUrl: "https://api.orcarouter.ai/v1",
  orcarouterSidecarApiKeyConfigured: true,
  orcarouterSidecarModelPrefixes: [{ prefix: "orcarouter/", strip: false }],
  orcarouterSidecarFullModels: [],
  orcarouterSidecarConnectTimeoutSeconds: 8,
  orcarouterSidecarRequestTimeoutSeconds: 600,
  orcarouterSidecarModelsCacheTtlSeconds: 60,
  orcarouterSidecarLastHealthStatus: "healthy",
  orcarouterSidecarLastHealthMessage: "OrcaRouter sidecar reachable",
  orcarouterSidecarLastCheckedAt: "2026-01-01T00:00:00Z",
  orcarouterSidecarLastModelCount: 1,
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
  orcarouterSidecarEnabled: true,
};

function renderWithQueryClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe("OrcaRouterSidecarSettings", () => {
  it("labels the section as the OrcaRouter integration", () => {
    renderWithQueryClient(<OrcaRouterSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={vi.fn()} />);

    expect(screen.getByRole("heading", { name: "OrcaRouter Integration" })).toBeInTheDocument();
  });

  it("renders the enable toggle above the OmniRoute prefix callout", () => {
    renderWithQueryClient(<OrcaRouterSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={vi.fn()} />);

    const enable = screen.getByRole("switch", { name: "Enable OrcaRouter Integration" });
    const callout = screen.getByText(/remove that OmniRoute prefix/i);
    expect(enable.compareDocumentPosition(callout) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("does not render Save or Clear buttons", () => {
    renderWithQueryClient(<OrcaRouterSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={vi.fn()} />);

    expect(screen.queryByRole("button", { name: /^Save$/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Clear API key" })).not.toBeInTheDocument();
  });

  it("adds an API key and runs the connection test after the save", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    const testSpy = vi.fn();
    server.use(
      http.post("*/api/orcarouter-sidecar/test", () => {
        testSpy();
        return HttpResponse.json({
          enabled: true,
          configured: true,
          status: "healthy",
          message: "OrcaRouter sidecar reachable",
          baseUrl: "https://api.orcarouter.ai/v1",
          modelCount: 0,
          lastCheckedAt: "2026-01-01T00:00:00Z",
          models: [],
        });
      }),
    );
    renderWithQueryClient(<OrcaRouterSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={onSave} />);

    await user.type(screen.getByLabelText(/API key/), "new-key");
    await user.click(screen.getByRole("button", { name: "Add API key" }));

    await waitFor(() =>
      expect(onSave).toHaveBeenLastCalledWith(expect.objectContaining({ orcarouterSidecarApiKey: "new-key" })),
    );
    expect(screen.getByLabelText(/API key/)).toHaveValue("");
    await waitFor(() => expect(testSpy).toHaveBeenCalledTimes(1));
  });

  it("persists edited model prefixes immediately", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderWithQueryClient(<OrcaRouterSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={onSave} />);

    await user.click(screen.getByRole("button", { name: "Remove orcarouter/" }));
    await user.type(screen.getByLabelText("New prefix for OrcaRouter Integration"), "google/");
    await user.click(screen.getByRole("button", { name: "Add prefix" }));
    await user.type(screen.getByLabelText("New prefix for OrcaRouter Integration"), "meta-llama/");
    await user.click(screen.getByRole("button", { name: "Add prefix" }));

    await waitFor(() =>
      expect(onSave).toHaveBeenLastCalledWith(
        expect.objectContaining({
          orcarouterSidecarModelPrefixes: [
            { prefix: "google/", strip: false },
            { prefix: "meta-llama/", strip: false },
          ],
        }),
      ),
    );
  });

  it("does not render a manual Test connection button", () => {
    renderWithQueryClient(<OrcaRouterSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={vi.fn()} />);

    expect(screen.queryByRole("button", { name: "Test connection" })).not.toBeInTheDocument();
  });

  it("adds a discovered model as a full model", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderWithQueryClient(<OrcaRouterSidecarSettings settings={ENABLED_SETTINGS} busy={false} onSave={onSave} />);

    await user.click(screen.getByRole("button", { name: /Discovered models/i }));
    await screen.findAllByText("google/gemini-2.5-pro-preview");
    await user.click(await screen.findByRole("button", { name: /Add full model google\/gemini-2.5-pro-preview/ }));

    expect(
      within(screen.getByLabelText("Configured full models for OrcaRouter Integration")).getByText(
        "google/gemini-2.5-pro-preview",
      ),
    ).toBeInTheDocument();
  });

  it("keeps discovered models collapsed inside the configuration card above the timeout fields", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderWithQueryClient(<OrcaRouterSidecarSettings settings={ENABLED_SETTINGS} busy={false} onSave={onSave} />);

    const disclosure = await screen.findByRole("button", { name: /Discovered models/i });
    const cacheTtlField = screen.getByLabelText(/Model cache TTL/);

    expect(disclosure.compareDocumentPosition(cacheTtlField) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(disclosure).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByLabelText("Search models")).not.toBeInTheDocument();

    await user.click(disclosure);

    expect(disclosure).toHaveAttribute("aria-expanded", "true");
    expect(await screen.findByLabelText("Search models")).toBeInTheDocument();
    await screen.findAllByText("google/gemini-2.5-pro-preview");
    await user.click(await screen.findByRole("button", { name: /Add full model google\/gemini-2.5-pro-preview/ }));
    expect(
      within(screen.getByLabelText("Configured full models for OrcaRouter Integration")).getByText(
        "google/gemini-2.5-pro-preview",
      ),
    ).toBeInTheDocument();
  });
});
