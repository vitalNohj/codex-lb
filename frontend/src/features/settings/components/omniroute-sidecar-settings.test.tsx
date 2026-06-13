import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { OmniRouteSidecarSettings } from "@/features/settings/components/omniroute-sidecar-settings";
import type { DashboardSettings } from "@/features/settings/schemas";

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
  omnirouteSidecarSelectedModels: ["omniroute/test-chat"],
  omnirouteSidecarConnectTimeoutSeconds: 8,
  omnirouteSidecarRequestTimeoutSeconds: 600,
  omnirouteSidecarModelsCacheTtlSeconds: 60,
  omnirouteSidecarLastHealthStatus: "healthy",
  omnirouteSidecarLastHealthMessage: "OmniRoute sidecar reachable",
  omnirouteSidecarLastCheckedAt: "2026-01-01T00:00:00Z",
  omnirouteSidecarLastModelCount: 1,
};

function renderWithQueryClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe("OmniRouteSidecarSettings", () => {
  it("saves sidecar config and can clear a configured key", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderWithQueryClient(<OmniRouteSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={onSave} />);

    await user.click(screen.getByRole("switch", { name: "Enable OmniRoute sidecar" }));
    expect(onSave).toHaveBeenLastCalledWith(expect.objectContaining({ omnirouteSidecarEnabled: true }));

    await user.type(screen.getByLabelText(/API key/), "new-key");
    await user.click(screen.getByRole("button", { name: "Save OmniRoute settings" }));

    expect(onSave).toHaveBeenLastCalledWith(
      expect.objectContaining({
        omnirouteSidecarApiKey: "new-key",
        omnirouteSidecarSelectedModels: ["omniroute/test-chat"],
      }),
    );

    await user.click(screen.getByRole("button", { name: "Clear API key" }));
    expect(onSave).toHaveBeenLastCalledWith(expect.objectContaining({ omnirouteSidecarClearApiKey: true }));
  });

  it("adds and removes exact model IDs", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderWithQueryClient(<OmniRouteSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={onSave} />);

    await user.type(screen.getByLabelText(/Add model ID manually/), "manual/model");
    await user.click(screen.getByRole("button", { name: "Add" }));
    expect(screen.getByText("manual/model")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Save OmniRoute settings" }));
    expect(onSave).toHaveBeenLastCalledWith(
      expect.objectContaining({
        omnirouteSidecarSelectedModels: ["omniroute/test-chat", "manual/model"],
      }),
    );

    await user.click(screen.getByRole("button", { name: "Remove manual/model" }));
    expect(screen.queryByText("manual/model")).not.toBeInTheDocument();
  });

  it("tests the connection", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderWithQueryClient(<OmniRouteSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={onSave} />);

    await user.click(screen.getByRole("button", { name: "Test connection" }));
    expect(await screen.findByText(/OmniRoute sidecar reachable/)).toBeInTheDocument();
  });

  it("opens the OmniRoute link in a new tab", () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderWithQueryClient(<OmniRouteSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={onSave} />);

    const link = screen.getByRole("link", { name: /open omniroute/i });
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });
});
