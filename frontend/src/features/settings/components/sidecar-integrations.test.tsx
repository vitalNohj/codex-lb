import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-client";
import { ClaudeSidecarSettings } from "@/features/settings/components/claude-sidecar-settings";
import { OmniRouteSidecarSettings } from "@/features/settings/components/omniroute-sidecar-settings";
import { OpenRouterSidecarSettings } from "@/features/settings/components/openrouter-sidecar-settings";
import type { DashboardSettings, SettingsUpdateRequest } from "@/features/settings/schemas";

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
  claudeSidecarEnabled: true,
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
  omnirouteSidecarEnabled: true,
  omnirouteSidecarBaseUrl: "http://127.0.0.1:20128/v1",
  omnirouteSidecarApiKeyConfigured: true,
  omnirouteSidecarModelPrefixes: [],
  omnirouteSidecarFullModels: ["omniroute/test-chat"],
  omnirouteSidecarSelectedModels: ["omniroute/test-chat"],
  omnirouteSidecarConnectTimeoutSeconds: 8,
  omnirouteSidecarRequestTimeoutSeconds: 600,
  omnirouteSidecarModelsCacheTtlSeconds: 60,
  guestAccessEnabled: false,
  guestPasswordConfigured: false,
} as DashboardSettings;

function renderWithQueryClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe("shared sidecar integration settings", () => {
  it("persists per-prefix strip toggle changes immediately", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderWithQueryClient(<ClaudeSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={onSave} />);

    await user.click(screen.getByRole("checkbox", { name: "Remove prefix claude before forwarding" }));

    await waitFor(() =>
      expect(onSave).toHaveBeenLastCalledWith(
        expect.objectContaining({
          claudeSidecarModelPrefixes: [{ prefix: "claude", strip: true }],
        }),
      ),
    );
  });

  it("rejects duplicate prefixes across integrations inline", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<OmniRouteSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={vi.fn()} />);

    await user.type(screen.getByLabelText("New prefix for OmniRoute Integration"), "deepseek/");
    await user.click(screen.getByRole("button", { name: "Add prefix" }));

    expect(screen.getByText("Prefix deepseek/ is already used by OpenRouter.")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "Remove prefix deepseek/ before forwarding" })).not.toBeInTheDocument();
  });

  it("adds a discovered model to the full-model list outside the browser and persists immediately", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderWithQueryClient(
      <OpenRouterSidecarSettings
        settings={{ ...BASE_SETTINGS, openrouterSidecarEnabled: true }}
        busy={false}
        onSave={onSave}
      />,
    );

    await user.click(await screen.findByRole("button", { name: /Discovered models/i }));
    await screen.findAllByText("deepseek/deepseek-chat");
    await user.click(await screen.findByRole("button", { name: /Add full model deepseek\/deepseek-chat/ }));

    const fullModels = screen.getByLabelText("Configured full models for OpenRouter Integration");
    expect(within(fullModels).getByText("deepseek/deepseek-chat")).toBeInTheDocument();

    await waitFor(() =>
      expect(onSave).toHaveBeenLastCalledWith(
        expect.objectContaining({
          openrouterSidecarFullModels: ["deepseek/deepseek-chat"],
        }),
      ),
    );
  });

  it("does not persist a full model while a cross-integration conflict is unresolved", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderWithQueryClient(
      <OpenRouterSidecarSettings
        settings={{
          ...BASE_SETTINGS,
          openrouterSidecarFullModels: ["omniroute/test-chat"],
          omnirouteSidecarFullModels: ["omniroute/test-chat"],
          omnirouteSidecarSelectedModels: ["omniroute/test-chat"],
        }}
        busy={false}
        onSave={onSave}
      />,
    );

    expect(screen.getByText("Full model omniroute/test-chat is already used by OmniRoute.")).toBeInTheDocument();
    expect(onSave).not.toHaveBeenCalled();
  });

  it("surfaces backend sidecar conflict details from error.details", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockRejectedValue(
      new ApiError({
        status: 400,
        code: "sidecar_routing_conflict",
        message: "Sidecar routing conflict",
        details: {
          code: "sidecar_routing_conflict",
          message: "Sidecar routing conflict",
          details: {
            code: "sidecar_routing_conflict",
            value: "deepseek/",
            kind: "prefix",
            owning_integration: "OpenRouter",
            challenging_integration: "OmniRoute",
          },
        },
      }),
    );
    renderWithQueryClient(
      <OmniRouteSidecarSettings
        settings={{ ...BASE_SETTINGS, openrouterSidecarModelPrefixes: [] }}
        busy={false}
        onSave={onSave as (payload: SettingsUpdateRequest) => Promise<void>}
      />,
    );

    await user.type(screen.getByLabelText("New prefix for OmniRoute Integration"), "deepseek/");
    await user.click(screen.getByRole("button", { name: "Add prefix" }));

    await waitFor(() => {
      expect(
        screen.getByText("Prefix deepseek/ conflicts with OpenRouter while saving OmniRoute."),
      ).toBeInTheDocument();
    });
  });
});
