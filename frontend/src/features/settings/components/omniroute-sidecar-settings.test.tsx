import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { OmniRouteSidecarSettings } from "@/features/settings/components/omniroute-sidecar-settings";
import type { DashboardSettings } from "@/features/settings/schemas";
import { server } from "@/test/mocks/server";

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
  omnirouteSidecarModelPrefixes: [],
  omnirouteSidecarFullModels: ["omniroute/test-chat"],
  omnirouteSidecarSelectedModels: ["omniroute/test-chat"],
  omnirouteSidecarConnectTimeoutSeconds: 8,
  omnirouteSidecarRequestTimeoutSeconds: 600,
  omnirouteSidecarModelsCacheTtlSeconds: 60,
  omnirouteSidecarLastHealthStatus: "healthy",
  omnirouteSidecarLastHealthMessage: "OmniRoute sidecar reachable",
  omnirouteSidecarLastCheckedAt: "2026-01-01T00:00:00Z",
  omnirouteSidecarLastModelCount: 1,
};

const ENABLED_SETTINGS: DashboardSettings = {
  ...BASE_SETTINGS,
  omnirouteSidecarEnabled: true,
};

function renderWithQueryClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe("OmniRouteSidecarSettings", () => {
  it("labels the section as the OmniRoute integration", () => {
    renderWithQueryClient(<OmniRouteSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={vi.fn()} />);

    expect(screen.getByRole("heading", { name: "OmniRoute Integration" })).toBeInTheDocument();
  });

  it("saves integration config and can clear a configured key", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderWithQueryClient(<OmniRouteSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={onSave} />);

    await user.click(screen.getByRole("switch", { name: "Enable OmniRoute Integration" }));
    expect(onSave).toHaveBeenLastCalledWith(expect.objectContaining({ omnirouteSidecarEnabled: true }));

    await user.type(screen.getByLabelText(/API key/), "new-key");
    await user.click(screen.getByRole("button", { name: /^Save$/ }));

    expect(onSave).toHaveBeenLastCalledWith(
      expect.objectContaining({
        omnirouteSidecarApiKey: "new-key",
        omnirouteSidecarFullModels: ["omniroute/test-chat"],
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

    await user.type(screen.getByLabelText("New full model for OmniRoute Integration"), "manual/model");
    await user.click(screen.getByRole("button", { name: "Add full model" }));
    expect(screen.getByText("manual/model")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^Save$/ }));
    expect(onSave).toHaveBeenLastCalledWith(
      expect.objectContaining({
        omnirouteSidecarFullModels: ["omniroute/test-chat", "manual/model"],
        omnirouteSidecarSelectedModels: ["omniroute/test-chat", "manual/model"],
      }),
    );

    await user.click(screen.getByRole("button", { name: "Remove manual/model" }));
    expect(screen.queryByText("manual/model")).not.toBeInTheDocument();
  });

  it("keeps discovered models collapsed inside the configuration card above actions", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderWithQueryClient(<OmniRouteSidecarSettings settings={ENABLED_SETTINGS} busy={false} onSave={onSave} />);

    const disclosure = await screen.findByRole("button", { name: /Discovered models/i });
    const saveButton = screen.getByRole("button", { name: /^Save$/ });

    expect(disclosure.compareDocumentPosition(saveButton) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(disclosure).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByLabelText("Search OmniRoute models")).not.toBeInTheDocument();
    expect(screen.getByText("omniroute/test-chat")).toBeInTheDocument();

    await user.click(disclosure);

    expect(disclosure).toHaveAttribute("aria-expanded", "true");
    expect(await screen.findByLabelText("Search models")).toBeInTheDocument();
    await screen.findAllByText("omniroute/test-chat");
    expect(screen.getByRole("button", { name: /Added omniroute\/test-chat/ })).toBeDisabled();
  });

  it("does not render a manual Test connection button", () => {
    renderWithQueryClient(<OmniRouteSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={vi.fn()} />);

    expect(screen.queryByRole("button", { name: "Test connection" })).not.toBeInTheDocument();
  });

  it("runs the connection test after a successful save", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    const testSpy = vi.fn();
    server.use(
      http.post("*/api/omniroute-sidecar/test", () => {
        testSpy();
        return HttpResponse.json({
          enabled: true,
          configured: true,
          status: "healthy",
          message: "OmniRoute sidecar reachable",
          baseUrl: "http://127.0.0.1:20128/v1",
          modelCount: 0,
          lastCheckedAt: "2026-01-01T00:00:00Z",
          models: [],
        });
      }),
    );
    renderWithQueryClient(<OmniRouteSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={onSave} />);

    await user.click(screen.getByRole("button", { name: /^Save$/ }));

    await waitFor(() => expect(testSpy).toHaveBeenCalledTimes(1));
  });

  it("opens the OmniRoute link in a new tab", () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderWithQueryClient(<OmniRouteSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={onSave} />);

    const link = screen.getByRole("link", { name: /open omniroute/i });
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });
});
