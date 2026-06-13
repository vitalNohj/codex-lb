import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { ClaudeSidecarSettings } from "@/features/settings/components/claude-sidecar-settings";
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
  claudeSidecarBaseUrl: "http://127.0.0.1:8317",
  claudeSidecarApiKeyConfigured: true,
  claudeSidecarModelPrefixes: ["claude"],
  claudeSidecarConnectTimeoutSeconds: 8,
  claudeSidecarRequestTimeoutSeconds: 600,
  claudeSidecarModelsCacheTtlSeconds: 60,
  claudeSidecarLastHealthStatus: "healthy",
  claudeSidecarLastHealthMessage: "Claude sidecar reachable",
  claudeSidecarLastCheckedAt: "2026-01-01T00:00:00Z",
  claudeSidecarLastModelCount: 1,
  claudeSidecarManagementKeyConfigured: false,
  claudeSidecarQuotaPollIntervalSeconds: 60,
  claudeSidecarAuthPlans: [],
  claudeSidecarUsagePollIntervalSeconds: 15,
  claudeSidecarUsageQueueBatchSize: 100,
  claudeSidecarUsageCollectionEnabled: true,
};

function renderWithQueryClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe("ClaudeSidecarSettings", () => {
  it("labels the section as the CLIProxyAPI integration", () => {
    renderWithQueryClient(<ClaudeSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={vi.fn()} />);

    expect(screen.getByRole("heading", { name: "CLIProxyAPI Integration" })).toBeInTheDocument();
  });

  it("saves sidecar config and can clear a configured key", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderWithQueryClient(<ClaudeSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={onSave} />);

    await user.click(screen.getByRole("switch", { name: "Enable CLI Proxy integration" }));
    expect(onSave).toHaveBeenLastCalledWith(expect.objectContaining({ claudeSidecarEnabled: true }));

    await user.clear(screen.getByLabelText(/Base URL/));
    await user.type(screen.getByLabelText(/Base URL/), "http://127.0.0.1:9000");
    await user.clear(screen.getByLabelText(/API key/));
    await user.type(screen.getByLabelText(/API key/), "new-key");
    await user.clear(screen.getByLabelText(/Model prefixes/));
    await user.type(screen.getByLabelText(/Model prefixes/), "claude, anthropic");
    await user.click(screen.getByRole("button", { name: /^Save$/ }));

    expect(onSave).toHaveBeenLastCalledWith(
      expect.objectContaining({
        claudeSidecarBaseUrl: "http://127.0.0.1:9000",
        claudeSidecarApiKey: "new-key",
        claudeSidecarModelPrefixes: ["claude", "anthropic"],
      }),
    );

    await user.click(screen.getByRole("button", { name: "Clear API key" }));
    expect(onSave).toHaveBeenLastCalledWith(expect.objectContaining({ claudeSidecarClearApiKey: true }));
  });

  it("disables save for invalid timeout", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<ClaudeSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={vi.fn()} />);

    await user.clear(screen.getByLabelText(/Connect timeout/));
    await user.type(screen.getByLabelText(/Connect timeout/), "0");
    expect(screen.getByRole("button", { name: /^Save$/ })).toBeDisabled();
  });

  it("does not render a manual Test connection button", () => {
    renderWithQueryClient(<ClaudeSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={vi.fn()} />);

    expect(screen.queryByRole("button", { name: "Test connection" })).not.toBeInTheDocument();
  });

  it("runs the connection test after a successful save", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    const testSpy = vi.fn();
    server.use(
      http.post("*/api/claude-sidecar/test", () => {
        testSpy();
        return HttpResponse.json({
          enabled: true,
          configured: true,
          status: "healthy",
          message: "Claude sidecar reachable",
          baseUrl: "http://127.0.0.1:8317",
          modelCount: 1,
          lastCheckedAt: "2026-01-01T00:00:00Z",
          models: [],
        });
      }),
    );
    renderWithQueryClient(<ClaudeSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={onSave} />);

    await user.click(screen.getByRole("button", { name: /^Save$/ }));

    await waitFor(() => expect(testSpy).toHaveBeenCalledTimes(1));
  });

  it("does not render quota estimation controls", () => {
    renderWithQueryClient(<ClaudeSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={vi.fn()} />);

    expect(screen.queryByText("Quota estimation")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save quota estimates" })).not.toBeInTheDocument();
  });

  it("saves the management key when provided", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderWithQueryClient(<ClaudeSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={onSave} />);

    await user.type(screen.getByLabelText(/Management key/), "mgmt-secret");
    await user.click(screen.getByRole("button", { name: /^Save$/ }));

    expect(onSave).toHaveBeenLastCalledWith(
      expect.objectContaining({ claudeSidecarManagementKey: "mgmt-secret" }),
    );
  });

  it("clears the management key when configured", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderWithQueryClient(
      <ClaudeSidecarSettings
        settings={{ ...BASE_SETTINGS, claudeSidecarManagementKeyConfigured: true }}
        busy={false}
        onSave={onSave}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Clear management key" }));
    expect(onSave).toHaveBeenLastCalledWith(
      expect.objectContaining({ claudeSidecarClearManagementKey: true }),
    );
  });

  it("shows placeholder when management key is configured", () => {
    renderWithQueryClient(
      <ClaudeSidecarSettings
        settings={{ ...BASE_SETTINGS, claudeSidecarManagementKeyConfigured: true }}
        busy={false}
        onSave={vi.fn()}
      />,
    );
    expect(screen.getByLabelText(/Management key/)).toHaveAttribute("placeholder", "Configured");
  });

});
