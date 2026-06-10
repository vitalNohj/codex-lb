import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ClaudeSidecarSettings } from "@/features/settings/components/claude-sidecar-settings";
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
};

function renderWithQueryClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe("ClaudeSidecarSettings", () => {
  it("saves sidecar config and can clear a configured key", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderWithQueryClient(<ClaudeSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={onSave} />);

    await user.click(screen.getByRole("switch", { name: "Enable Claude sidecar" }));
    expect(onSave).toHaveBeenLastCalledWith(expect.objectContaining({ claudeSidecarEnabled: true }));

    await user.clear(screen.getByLabelText(/Base URL/));
    await user.type(screen.getByLabelText(/Base URL/), "http://127.0.0.1:9000");
    await user.clear(screen.getByLabelText(/API key/));
    await user.type(screen.getByLabelText(/API key/), "new-key");
    await user.clear(screen.getByLabelText(/Model prefixes/));
    await user.type(screen.getByLabelText(/Model prefixes/), "claude, anthropic");
    await user.click(screen.getByRole("button", { name: "Save sidecar" }));

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

  it("disables save for invalid timeout and triggers test mutation", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<ClaudeSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={vi.fn()} />);

    await user.clear(screen.getByLabelText(/Connect timeout/));
    await user.type(screen.getByLabelText(/Connect timeout/), "0");
    expect(screen.getByRole("button", { name: "Save sidecar" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Test connection" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Test connection" })).toBeInTheDocument());
  });

  it("saves the management key when provided", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderWithQueryClient(<ClaudeSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={onSave} />);

    await user.type(screen.getByLabelText(/Management key/), "mgmt-secret");
    await user.click(screen.getByRole("button", { name: "Save sidecar" }));

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
