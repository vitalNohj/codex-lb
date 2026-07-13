import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import type { ReactElement } from "react";
import { BrowserRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AccountDetail } from "@/features/accounts/components/account-detail";
import { createAccountSummary, createUpstreamProxyAdmin } from "@/test/mocks/factories";
import { server } from "@/test/mocks/server";

const testMutateAsync = vi.fn().mockResolvedValue(undefined);

vi.mock("@/features/settings/hooks/use-settings", async () => {
  const actual = await vi.importActual<typeof import("@/features/settings/hooks/use-settings")>(
    "@/features/settings/hooks/use-settings",
  );
  return {
    ...actual,
    useSidecarConnectionTest: vi.fn(() => ({
      mutate: vi.fn(),
      mutateAsync: testMutateAsync,
      isPending: false,
    })),
  };
});

beforeEach(() => {
  testMutateAsync.mockClear();
});

function renderWithClient(ui: ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>{ui}</BrowserRouter>
    </QueryClientProvider>,
  );
}

const detailHandlers = {
  onPause: vi.fn(),
  onResume: vi.fn(),
  onProbe: vi.fn(),
  onResetUsage: vi.fn(),
  onSetAlias: vi.fn(),
  onDelete: vi.fn(),
  onReauth: vi.fn(),
  onExportAuth: vi.fn(),
  onResetCredit: vi.fn(),
  onLimitWarmupChange: vi.fn(),
  onRoutingPolicyChange: vi.fn(),
  onSecurityWorkAuthorizedChange: vi.fn(),
};

describe("AccountDetail", () => {
  it("renders synthetic sidecar account as read-only", () => {
    const account = createAccountSummary({
      accountId: "claude-sidecar",
      email: "cliproxyapi.local",
      displayName: "Claude via CLIProxyAPI",
      planType: "claude",
      status: "paused",
      synthetic: true,
      readOnly: true,
      kind: "sidecar",
      provider: "claude",
      healthStatus: "unreachable",
      healthMessage: "connection refused",
      baseUrl: "http://127.0.0.1:8317",
      modelCount: 0,
    });

    renderWithClient(
      <AccountDetail
        account={account}
        busy={false}
        onPause={vi.fn()}
        onResume={vi.fn()}
        onProbe={vi.fn()}
        onResetUsage={vi.fn()}
        onSetAlias={vi.fn()}
        onDelete={vi.fn()}
        onReauth={vi.fn()}
        onExportAuth={vi.fn()}
        onResetCredit={vi.fn()}
        onLimitWarmupChange={vi.fn()}
        onRoutingPolicyChange={vi.fn()}
        onSecurityWorkAuthorizedChange={vi.fn()}
      />,
    );

    expect(screen.getByText("Read-only CLIProxyAPI multi-provider account")).toBeInTheDocument();
    expect(screen.getByText("http://127.0.0.1:8317")).toBeInTheDocument();
    expect(screen.getByText("connection refused")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Configure/ })).toHaveAttribute("href", "/settings#claude-sidecar");
    expect(screen.queryByRole("button", { name: /Pause/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Delete/i })).not.toBeInTheDocument();
  });

  it("shows sidecar auth quota rows when present", () => {
    const account = createAccountSummary({
      accountId: "claude-sidecar",
      email: "cliproxyapi.local",
      displayName: "Claude via CLIProxyAPI",
      planType: "claude",
      status: "rate_limited",
      synthetic: true,
      readOnly: true,
      kind: "sidecar",
      provider: "claude",
      healthStatus: "healthy",
      baseUrl: "http://127.0.0.1:8317",
      modelCount: 4,
      resetAtPrimary: "2026-06-10T17:00:00+00:00",
      lastRefreshAt: "2026-06-10T12:00:00+00:00",
      usage: {
        primaryRemainingPercent: 75,
        secondaryRemainingPercent: 96,
      },
      resetAtSecondary: "2026-06-17T12:00:00+00:00",
      sidecarAuths: [
        {
          name: "claude-1",
          authIndex: "0",
          email: "exceeded@example.com",
          provider: "claude",
          quotaWindows: ["five_hour", "weekly"],
          supportsManualPlan: true,
          status: "active",
          paused: false,
          quotaExceeded: true,
          nextRecoverAt: "2026-06-10T17:00:00+00:00",
          modelsExceeded: ["claude-opus-4"],
          success: 4,
          failed: 1,
          planType: "custom",
          primaryRemainingPercent: 0,
          secondaryRemainingPercent: 96,
          primaryUsedTokens: 25,
          secondaryUsedTokens: 25,
          primaryTokenBudget: 100,
          secondaryTokenBudget: 700,
          confidence: "estimated",
        },
      ],
    });

    renderWithClient(
      <AccountDetail
        account={account}
        busy={false}
        onPause={vi.fn()}
        onResume={vi.fn()}
        onProbe={vi.fn()}
        onResetUsage={vi.fn()}
        onSetAlias={vi.fn()}
        onDelete={vi.fn()}
        onReauth={vi.fn()}
        onExportAuth={vi.fn()}
        onResetCredit={vi.fn()}
        onLimitWarmupChange={vi.fn()}
        onRoutingPolicyChange={vi.fn()}
        onSecurityWorkAuthorizedChange={vi.fn()}
      />,
    );

    expect(screen.getByText("exceeded@example.com")).toBeInTheDocument();
    expect(screen.getByText("Estimated 5h remaining")).toBeInTheDocument();
    expect(screen.getByText(/Exhausted — recovers/)).toBeInTheDocument();
    expect(screen.getByText(/claude-opus-4/)).toBeInTheDocument();
    expect(screen.getByText(/Custom/)).toBeInTheDocument();
    expect(screen.getByText(/25 \/ 100 tok/)).toBeInTheDocument();
  });

  it("hides undeclared CLIProxyAPI quota windows in synthetic detail", () => {
    const account = createAccountSummary({
      accountId: "claude-sidecar",
      displayName: "CLIProxyAPI",
      synthetic: true,
      readOnly: true,
      kind: "sidecar",
      provider: "claude",
      status: "active",
      usage: {
        primaryRemainingPercent: null,
        secondaryRemainingPercent: 82,
      },
      sidecarAuths: [{
        name: "xai-1",
        email: "grok@example.com",
        provider: "xai",
        quotaWindows: ["weekly"],
        supportsManualPlan: true,
        paused: false,
        quotaExceeded: false,
        modelsExceeded: [],
        success: 1,
        failed: 0,
        planType: "custom",
        secondaryRemainingPercent: 82,
      }],
    });

    renderWithClient(<AccountDetail account={account} busy={false} {...detailHandlers} />);

    expect(screen.queryByText("Estimated 5h remaining")).not.toBeInTheDocument();
    expect(screen.getByText("Estimated weekly remaining")).toBeInTheDocument();
    const authRow = screen.getByText("grok@example.com").closest("li");
    expect(authRow).toHaveTextContent("Grok");
    expect(authRow).toHaveTextContent("weekly 82%");
    expect(authRow).not.toHaveTextContent("5h");
  });

  it("shows connection status and no provider badge for a synthetic account", () => {
    const account = createAccountSummary({
      accountId: "openrouter-sidecar",
      displayName: "OpenRouter",
      synthetic: true,
      readOnly: true,
      kind: "sidecar",
      provider: "openrouter",
      status: "active",
      healthStatus: "healthy",
      healthMessage: "OpenRouter reachable",
      baseUrl: "https://openrouter.ai/api/v1",
      lastCheckedAt: "2026-06-10T12:00:00+00:00",
      modelCount: 12,
    });

    renderWithClient(<AccountDetail account={account} busy={false} {...detailHandlers} />);

    expect(screen.getByText("Connection")).toBeInTheDocument();
    expect(screen.getByText("Base URL")).toBeInTheDocument();
    expect(screen.getByText("Last checked")).toBeInTheDocument();
    expect(screen.getByText("OpenRouter reachable")).toBeInTheDocument();
    // The title still names the provider, but there must be no duplicate badge.
    const badges = screen.queryAllByText("OpenRouter");
    expect(badges).toHaveLength(1);
  });

  it("runs a manual connection test from the synthetic detail", async () => {
    const user = userEvent.setup();
    const account = createAccountSummary({
      accountId: "omniroute-sidecar",
      displayName: "OmniRoute",
      synthetic: true,
      readOnly: true,
      kind: "sidecar",
      provider: "omniroute",
      status: "active",
      healthStatus: "healthy",
      baseUrl: "http://127.0.0.1:20128/v1",
    });

    renderWithClient(<AccountDetail account={account} busy={false} {...detailHandlers} />);

    await user.click(screen.getByRole("button", { name: /Test connection/i }));
    await waitFor(() => expect(testMutateAsync).toHaveBeenCalledTimes(1));
  });

  it("renders CLIProxyAPI quota estimation controls and saves plans", async () => {
    const account = createAccountSummary({
      accountId: "claude-sidecar",
      displayName: "Claude via CLIProxyAPI",
      synthetic: true,
      readOnly: true,
      kind: "sidecar",
      provider: "claude",
      status: "active",
      healthStatus: "healthy",
      baseUrl: "http://127.0.0.1:8317",
    });

    renderWithClient(<AccountDetail account={account} busy={false} {...detailHandlers} />);

    expect(await screen.findByText("claude@example.com")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save quota estimates" })).toBeInTheDocument();
  });

  it("uses custom weekly-only estimation for non-Claude CLIProxyAPI auths", async () => {
    const user = userEvent.setup();
    let savedPlans: unknown;
    server.use(
      http.get("*/api/claude-sidecar/quota", () => HttpResponse.json({
        status: "healthy",
        accounts: [
          {
            name: "claude@example.com",
            authIndex: "0",
            email: "claude@example.com",
            provider: "claude",
            quotaWindows: ["five_hour", "weekly"],
            supportsManualPlan: true,
            modelsExceeded: [],
          },
          {
            name: "xai@example.com",
            authIndex: "0",
            email: "grok@example.com",
            provider: "xai",
            quotaWindows: [],
            supportsManualPlan: true,
            modelsExceeded: [],
          },
        ],
      })),
      http.put("*/api/settings", async ({ request }) => {
        const body = await request.json() as { claudeSidecarAuthPlans?: unknown };
        savedPlans = body.claudeSidecarAuthPlans;
        return HttpResponse.json(body);
      }),
    );
    const account = createAccountSummary({
      accountId: "claude-sidecar",
      displayName: "CLIProxyAPI",
      synthetic: true,
      readOnly: true,
      kind: "sidecar",
      provider: "claude",
      status: "active",
    });

    renderWithClient(<AccountDetail account={account} busy={false} {...detailHandlers} />);

    const grokRow = (await screen.findByText("grok@example.com")).closest("div.grid");
    expect(grokRow).not.toBeNull();
    expect(within(grokRow as HTMLElement).getByRole("combobox", { name: "Plan" })).toHaveTextContent("Custom");
    expect(within(grokRow as HTMLElement).queryByLabelText("5-hour tokens")).not.toBeInTheDocument();
    const weeklyInput = within(grokRow as HTMLElement).getByLabelText("Weekly tokens");
    expect(weeklyInput).toHaveValue(null);
    await user.type(weeklyInput, "123000");
    await user.click(screen.getByRole("button", { name: "Save quota estimates" }));

    await waitFor(() => expect(savedPlans).toEqual(expect.arrayContaining([
      expect.objectContaining({
        provider: "claude",
        planType: "pro",
        primaryTokenBudget: 40_000,
        secondaryTokenBudget: 280_000,
      }),
      expect.objectContaining({
        provider: "xai",
        planType: "custom",
        secondaryTokenBudget: 123_000,
      }),
    ])));
    expect(savedPlans).not.toEqual(expect.arrayContaining([
      expect.objectContaining({ provider: "xai", primaryTokenBudget: expect.any(Number) }),
    ]));
  });

  it("omits quota estimation controls for OpenRouter and OmniRoute", () => {
    const account = createAccountSummary({
      accountId: "openrouter-sidecar",
      displayName: "OpenRouter",
      synthetic: true,
      readOnly: true,
      kind: "sidecar",
      provider: "openrouter",
      status: "active",
      healthStatus: "healthy",
      baseUrl: "https://openrouter.ai/api/v1",
    });

    renderWithClient(<AccountDetail account={account} busy={false} {...detailHandlers} />);

    expect(screen.queryByRole("button", { name: "Save quota estimates" })).not.toBeInTheDocument();
  });

  it("lets operators change account routing policy", async () => {
    const user = userEvent.setup();
    const onRoutingPolicyChange = vi.fn();
    const account = createAccountSummary({ routingPolicy: "normal" });

    renderWithClient(
      <AccountDetail
        account={account}
        busy={false}
        onPause={vi.fn()}
        onResume={vi.fn()}
        onProbe={vi.fn()}
        onResetUsage={vi.fn()}
        onSetAlias={vi.fn().mockResolvedValue(undefined)}
        onDelete={vi.fn()}
        onReauth={vi.fn()}
        onExportAuth={vi.fn()}
        onResetCredit={vi.fn()}
        onLimitWarmupChange={vi.fn()}
        onRoutingPolicyChange={onRoutingPolicyChange}
        onSecurityWorkAuthorizedChange={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("combobox", { name: "Routing policy" }));
    await user.click(await screen.findByRole("option", { name: "Preserve" }));

    expect(onRoutingPolicyChange).toHaveBeenCalledWith(account.accountId, "preserve");
  });

  it("disables alias and proxy binding controls for read-only guests", () => {
    const onSetAlias = vi.fn().mockResolvedValue(undefined);
    const onProxyBindingSave = vi.fn().mockResolvedValue(undefined);
    const account = createAccountSummary({ accountId: "acc_primary", alias: "Personal" });

    renderWithClient(
      <AccountDetail
        account={account}
        busy={false}
        readOnly
        onPause={vi.fn()}
        onResume={vi.fn()}
        onProbe={vi.fn()}
        onResetUsage={vi.fn()}
        onSetAlias={onSetAlias}
        onDelete={vi.fn()}
        onReauth={vi.fn()}
        onExportAuth={vi.fn()}
        onResetCredit={vi.fn()}
        onLimitWarmupChange={vi.fn()}
        onRoutingPolicyChange={vi.fn()}
        onSecurityWorkAuthorizedChange={vi.fn()}
        onProxyBindingSave={onProxyBindingSave}
        upstreamProxyAdmin={createUpstreamProxyAdmin({
          bindings: [{ accountId: "acc_primary", poolId: "pool_primary", isActive: true }],
        })}
        resetCredits={{ availableCount: 1 }}
      />,
    );

    expect(screen.getByRole("button", { name: "Edit alias" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reset usage" })).toBeDisabled();
    expect(screen.getByRole("switch", { name: "Enable account proxy binding" })).toBeDisabled();
    expect(screen.getByRole("combobox", { name: "Account proxy pool" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save binding" })).toBeDisabled();
  });

  it("disables usage reset for paused accounts", () => {
    const account = createAccountSummary({ status: "paused" });

    renderWithClient(
      <AccountDetail
        account={account}
        busy={false}
        onPause={vi.fn()}
        onResume={vi.fn()}
        onProbe={vi.fn()}
        onResetUsage={vi.fn()}
        onSetAlias={vi.fn().mockResolvedValue(undefined)}
        onDelete={vi.fn()}
        onReauth={vi.fn()}
        onExportAuth={vi.fn()}
        onResetCredit={vi.fn()}
        onLimitWarmupChange={vi.fn()}
        onRoutingPolicyChange={vi.fn()}
        onSecurityWorkAuthorizedChange={vi.fn()}
        resetCredits={{ availableCount: 2 }}
      />,
    );

    expect(screen.getByRole("button", { name: "Reset usage" })).toBeDisabled();
  });
});
