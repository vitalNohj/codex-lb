import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { BrowserRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { AccountDetail } from "@/features/accounts/components/account-detail";
import { createAccountSummary } from "@/test/mocks/factories";

function renderWithClient(ui: ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>{ui}</BrowserRouter>
    </QueryClientProvider>,
  );
}

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
        onSetAlias={vi.fn()}
        onDelete={vi.fn()}
        onReauth={vi.fn()}
        onExportAuth={vi.fn()}
        onLimitWarmupChange={vi.fn()}
        onRoutingPolicyChange={vi.fn()}
        onSecurityWorkAuthorizedChange={vi.fn()}
      />,
    );

    expect(screen.getByText("Read-only Claude sidecar account")).toBeInTheDocument();
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
          status: "active",
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
        onSetAlias={vi.fn()}
        onDelete={vi.fn()}
        onReauth={vi.fn()}
        onExportAuth={vi.fn()}
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
        onSetAlias={vi.fn().mockResolvedValue(undefined)}
        onDelete={vi.fn()}
        onReauth={vi.fn()}
        onExportAuth={vi.fn()}
        onLimitWarmupChange={vi.fn()}
        onRoutingPolicyChange={onRoutingPolicyChange}
        onSecurityWorkAuthorizedChange={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("combobox", { name: "Routing policy" }));
    await user.click(await screen.findByRole("option", { name: "Preserve" }));

    expect(onRoutingPolicyChange).toHaveBeenCalledWith(account.accountId, "preserve");
  });
});
