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
  claudeSidecarModelPrefixes: [{ prefix: "claude", strip: false }],
  claudeSidecarFullModels: [],
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
  guestAccessEnabled: false,
  guestPasswordConfigured: false,
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

  it("does not render Save or Clear buttons", () => {
    renderWithQueryClient(<ClaudeSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={vi.fn()} />);

    expect(screen.queryByRole("button", { name: /^Save$/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Clear API key" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Clear management key" })).not.toBeInTheDocument();
  });

  it("persists the enabled toggle immediately without an auto-test", async () => {
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

    await user.click(screen.getByRole("switch", { name: "Enable CLI Proxy integration" }));
    expect(onSave).toHaveBeenLastCalledWith(expect.objectContaining({ claudeSidecarEnabled: true }));
    expect(testSpy).not.toHaveBeenCalled();
  });

  it("persists the base URL on blur", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderWithQueryClient(<ClaudeSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={onSave} />);

    await user.clear(screen.getByLabelText(/Base URL/));
    await user.type(screen.getByLabelText(/Base URL/), "http://127.0.0.1:9000");
    await user.tab();

    await waitFor(() =>
      expect(onSave).toHaveBeenLastCalledWith(
        expect.objectContaining({ claudeSidecarBaseUrl: "http://127.0.0.1:9000" }),
      ),
    );
  });

  it("persists a new prefix immediately", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderWithQueryClient(<ClaudeSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={onSave} />);

    await user.type(screen.getByLabelText("New prefix for CLIProxyAPI Integration"), "anthropic");
    await user.click(screen.getByRole("button", { name: "Add prefix" }));

    await waitFor(() =>
      expect(onSave).toHaveBeenLastCalledWith(
        expect.objectContaining({
          claudeSidecarModelPrefixes: [
            { prefix: "claude", strip: false },
            { prefix: "anthropic", strip: false },
          ],
        }),
      ),
    );
  });

  it("does not persist while a timeout is invalid", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderWithQueryClient(<ClaudeSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={onSave} />);

    await user.clear(screen.getByLabelText(/Connect timeout/));
    await user.type(screen.getByLabelText(/Connect timeout/), "0");
    await user.tab();

    expect(onSave).not.toHaveBeenCalled();
  });

  it("does not render a manual Test connection button", () => {
    renderWithQueryClient(<ClaudeSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={vi.fn()} />);

    expect(screen.queryByRole("button", { name: "Test connection" })).not.toBeInTheDocument();
  });

  it("adds an API key and runs the connection test after the save", async () => {
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

    await user.type(screen.getByLabelText(/API key/), "new-key");
    await user.click(screen.getByRole("button", { name: "Add API key" }));

    await waitFor(() =>
      expect(onSave).toHaveBeenLastCalledWith(expect.objectContaining({ claudeSidecarApiKey: "new-key" })),
    );
    expect(screen.getByLabelText(/API key/)).toHaveValue("");
    await waitFor(() => expect(testSpy).toHaveBeenCalledTimes(1));
  });

  it("does not render quota estimation controls", () => {
    renderWithQueryClient(<ClaudeSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={vi.fn()} />);

    expect(screen.queryByText("Quota estimation")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save quota estimates" })).not.toBeInTheDocument();
  });

  it("adds the management key when provided", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderWithQueryClient(<ClaudeSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={onSave} />);

    await user.type(screen.getByLabelText(/Management key/), "mgmt-secret");
    await user.click(screen.getByRole("button", { name: "Add management key" }));

    await waitFor(() =>
      expect(onSave).toHaveBeenLastCalledWith(
        expect.objectContaining({ claudeSidecarManagementKey: "mgmt-secret" }),
      ),
    );
    expect(screen.getByLabelText(/Management key/)).toHaveValue("");
  });

  it("renders CLIProxyAPI routing controls when management key is configured", async () => {
    renderWithQueryClient(
      <ClaudeSidecarSettings
        settings={{ ...BASE_SETTINGS, claudeSidecarManagementKeyConfigured: true }}
        busy={false}
        onSave={vi.fn()}
      />,
    );

    expect(await screen.findByText("CLIProxyAPI routing")).toBeInTheDocument();
    const firstPriority = await screen.findByLabelText("Priority for a@example.com");
    const secondPriority = await screen.findByLabelText("Priority for b@example.com");
    expect(screen.getByText("a@example.com")).toBeInTheDocument();
    expect(screen.getByText("b@example.com")).toBeInTheDocument();
    expect(firstPriority).toHaveValue(0);
    expect(secondPriority).toHaveValue(10);
  });

  it("hides CLIProxyAPI routing controls without a management key", () => {
    renderWithQueryClient(<ClaudeSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={vi.fn()} />);

    expect(screen.queryByText("CLIProxyAPI routing")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Priority for a@example.com")).not.toBeInTheDocument();
  });

  it("updates the routing strategy immediately", async () => {
    const user = userEvent.setup();
    let receivedStrategy: string | undefined;
    server.use(
      http.put("*/api/claude-sidecar/routing/strategy", async ({ request }) => {
        const body = (await request.json()) as { strategy?: string };
        receivedStrategy = body.strategy;
        return HttpResponse.json({
          status: "healthy",
          message: null,
          strategy: body.strategy,
          accounts: [],
        });
      }),
    );
    renderWithQueryClient(
      <ClaudeSidecarSettings
        settings={{ ...BASE_SETTINGS, claudeSidecarManagementKeyConfigured: true }}
        busy={false}
        onSave={vi.fn()}
      />,
    );

    await screen.findByText("CLIProxyAPI routing");
    await user.click(screen.getByRole("combobox", { name: /Routing strategy/ }));
    await user.click(await screen.findByRole("option", { name: "Round robin" }));

    await waitFor(() => expect(receivedStrategy).toBe("round_robin"));
  });

  it("updates account priority on blur", async () => {
    const user = userEvent.setup();
    let receivedBody: unknown;
    server.use(
      http.put("*/api/claude-sidecar/routing/priority", async ({ request }) => {
        receivedBody = await request.json();
        return HttpResponse.json({
          status: "healthy",
          message: null,
          strategy: "fill_first",
          accounts: [],
        });
      }),
    );
    renderWithQueryClient(
      <ClaudeSidecarSettings
        settings={{ ...BASE_SETTINGS, claudeSidecarManagementKeyConfigured: true }}
        busy={false}
        onSave={vi.fn()}
      />,
    );

    const priorityInput = await screen.findByLabelText("Priority for a@example.com");
    await user.clear(priorityInput);
    await user.type(priorityInput, "100");
    await user.tab();

    await waitFor(() =>
      expect(receivedBody).toEqual({ name: "claude-a@example.com.json", priority: 100 }),
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
