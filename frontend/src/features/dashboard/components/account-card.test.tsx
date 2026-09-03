import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AccountCard, ClaudeAuthCard } from "@/features/dashboard/components/account-card";
import { usePrivacyStore } from "@/hooks/use-privacy";
import { createAccountSummary } from "@/test/mocks/factories";
import { renderWithProviders } from "@/test/utils";

afterEach(() => {
  act(() => {
    usePrivacyStore.setState({ blurred: false });
  });
});

describe("AccountCard", () => {
  it("renders both 5h and weekly quota bars for regular accounts", () => {
    const account = createAccountSummary();
    render(<AccountCard account={account} />);

    expect(screen.getByText("Plus")).toBeInTheDocument();
    expect(screen.getByText("5h")).toBeInTheDocument();
    expect(screen.getByText("Weekly")).toBeInTheDocument();
  });

  it("hides 5h quota bar for weekly-only accounts", () => {
    const account = createAccountSummary({
      planType: "free",
      usage: {
        primaryRemainingPercent: null,
        secondaryRemainingPercent: 76,
      },
      windowMinutesPrimary: null,
      windowMinutesSecondary: 10_080,
    });

    render(<AccountCard account={account} />);

    expect(screen.getByText("Free")).toBeInTheDocument();
    expect(screen.queryByText("5h")).not.toBeInTheDocument();
    expect(screen.getByText("Weekly")).toBeInTheDocument();
  });

  it("shows Monthly only for monthly-only free accounts", () => {
    const account = createAccountSummary({
      planType: "free",
      usage: {
        primaryRemainingPercent: null,
        secondaryRemainingPercent: null,
        monthlyRemainingPercent: 76,
      },
      windowMinutesPrimary: null,
      windowMinutesSecondary: null,
      windowMinutesMonthly: 43_200,
      resetAtPrimary: null,
      resetAtSecondary: null,
      resetAtMonthly: "2026-01-31T00:00:00.000Z",
    });

    render(<AccountCard account={account} />);

    expect(screen.getByText("Monthly")).toBeInTheDocument();
    expect(screen.queryByText("5h")).not.toBeInTheDocument();
    expect(screen.queryByText("Weekly")).not.toBeInTheDocument();
  });

  it("labels staggered idle warm-up attempts as 5h", () => {
    const attemptedAt = new Date("2026-06-03T12:00:00Z").toISOString();
    const account = createAccountSummary({
      limitWarmupEnabled: true,
      limitWarmup: {
        window: "primary_idle",
        resetAt: 18_000,
        status: "succeeded",
        model: "gpt-5.1-codex-mini",
        attemptedAt,
        completedAt: attemptedAt,
        errorCode: null,
        errorMessage: null,
      },
    });

    render(<AccountCard account={account} />);

    expect(
      screen.getByText((text) => text.includes("Succeeded | 5h | Gpt-5.1-codex-mini")),
    ).toBeInTheDocument();
  });

  it("blurs the dashboard card title when privacy mode is enabled", () => {
    act(() => {
      usePrivacyStore.setState({ blurred: true });
    });
    const account = createAccountSummary({
      displayName: "AWS Account MSP",
      email: "aws-account@example.com",
    });

    const { container } = render(<AccountCard account={account} />);

    expect(screen.getByText("AWS Account MSP")).toBeInTheDocument();
    expect(container.querySelector(".privacy-blur")).not.toBeNull();
  });

  it("renders subscription and purchased credits separately", () => {
    const account = createAccountSummary({
      creditsBalance: 0,
      remainingCreditsSecondary: 5_065.2,
    });

    render(<AccountCard account={account} />);

    expect(screen.getByText("Subscription quota:")).toBeInTheDocument();
    expect(screen.getByText("5065.20")).toBeInTheDocument();
    expect(screen.getByText("Purchased credits:")).toBeInTheDocument();
    expect(screen.getByText("0.00")).toBeInTheDocument();
  });

  it("applies unlimited only to purchased credits", () => {
    const account = createAccountSummary({
      creditsUnlimited: true,
      creditsBalance: null,
      remainingCreditsSecondary: 5_065.2,
    });

    render(<AccountCard account={account} />);

    expect(screen.getByText("5065.20")).toBeInTheDocument();
    expect(screen.getByText("Unlimited")).toBeInTheDocument();
  });

  it("renders re-auth status and action for re-auth required accounts", () => {
    const account = createAccountSummary({ status: "reauth_required" });

    render(<AccountCard account={account} />);

    expect(screen.getByText("Re-auth required")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Re-auth" })).toBeInTheDocument();
  });

  it("shows a Pause action and dispatches the pause action for a normal active account", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();
    const account = createAccountSummary({ status: "active" });

    render(<AccountCard account={account} onAction={onAction} />);

    const pauseButton = screen.getByRole("button", { name: "Pause" });
    expect(pauseButton).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Resume" })).not.toBeInTheDocument();

    await user.click(pauseButton);

    expect(onAction).toHaveBeenCalledWith(account, "pause");
  });

  it("shows Resume instead of Pause for a paused account", () => {
    const account = createAccountSummary({ status: "paused" });

    render(<AccountCard account={account} onAction={vi.fn()} />);

    expect(screen.getByRole("button", { name: "Resume" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pause" })).not.toBeInTheDocument();
  });

  it("does not show Pause for re-auth required accounts", () => {
    const account = createAccountSummary({ status: "reauth_required" });

    render(<AccountCard account={account} onAction={vi.fn()} />);

    expect(screen.queryByRole("button", { name: "Pause" })).not.toBeInTheDocument();
  });

  it("renders a per-auth CLI Proxy API card with codex-style layout and pause action", () => {
    const account = createAccountSummary({
      accountId: "claude-sidecar",
      email: "cliproxyapi.local",
      displayName: "CLI Proxy API",
      planType: "claude",
      status: "active",
      synthetic: true,
      readOnly: true,
      kind: "sidecar",
      provider: "claude",
      healthStatus: "healthy",
      baseUrl: "http://127.0.0.1:8317",
      usage: null,
    });
    const auth = {
      name: "claude-1",
      authIndex: "0",
      email: "claude-one@example.com",
      provider: "claude",
      paused: false,
      quotaExceeded: false,
      modelsExceeded: [],
      success: 0,
      failed: 0,
      usageSource: "oauth_usage",
      primaryRemainingPercent: 75,
      secondaryRemainingPercent: 96,
      resetAtPrimary: "2026-06-10T17:00:00+00:00",
      resetAtSecondary: "2026-06-17T12:00:00+00:00",
    };

    renderWithProviders(<ClaudeAuthCard account={account} auth={auth} />);

    expect(screen.getByText("claude-one@example.com")).toBeInTheDocument();
    expect(screen.getByText(/Claude/)).toBeInTheDocument();
    expect(screen.getByText("5h")).toBeInTheDocument();
    expect(screen.getByText("Weekly")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Details" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pause claude-one@example.com" })).toBeInTheDocument();
    expect(screen.queryByText("Health")).toBeNull();
    expect(screen.queryByText("Requests")).toBeNull();
    expect(screen.queryByRole("button", { name: /Warm-up/i })).toBeNull();
    expect(screen.queryByText("Credits:")).toBeNull();
  });

  it("shows Resume for a paused CLI Proxy API auth card", () => {
    const account = createAccountSummary({
      accountId: "claude-sidecar",
      displayName: "CLI Proxy API",
      planType: "claude",
      status: "active",
      synthetic: true,
      kind: "sidecar",
      provider: "claude",
      usage: null,
    });
    const auth = {
      name: "claude-1",
      authIndex: "0",
      email: "claude-one@example.com",
      paused: true,
      quotaExceeded: false,
      modelsExceeded: [],
      success: 0,
      failed: 0,
      usageSource: "oauth_usage",
      primaryRemainingPercent: 100,
      secondaryRemainingPercent: 38,
    };

    renderWithProviders(<ClaudeAuthCard account={account} auth={auth} />);

    expect(screen.getByRole("button", { name: "Resume claude-one@example.com" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pause claude-one@example.com" })).toBeNull();
  });

  it("shows Re-auth required badge for expired Claude OAuth auth", () => {
    const account = createAccountSummary({
      accountId: "claude-sidecar",
      displayName: "CLI Proxy API",
      planType: "claude",
      status: "active",
      synthetic: true,
      kind: "sidecar",
      provider: "claude",
      usage: null,
    });
    const auth = {
      name: "claude-1",
      authIndex: "0",
      email: "vitalnohj@example.com",
      status: "reauth_required",
      paused: false,
      quotaExceeded: false,
      modelsExceeded: [],
      success: 0,
      failed: 1,
      usageSource: "oauth_usage",
      primaryRemainingPercent: 100,
      secondaryRemainingPercent: 79,
    };

    renderWithProviders(<ClaudeAuthCard account={account} auth={auth} />);

    expect(screen.getByText("Re-auth required")).toBeInTheDocument();
  });

  it("falls back to CLIProxyAPI in the subtitle when the auth provider is unknown", () => {
    const account = createAccountSummary({
      accountId: "claude-sidecar",
      displayName: "CLI Proxy API",
      planType: "claude",
      status: "active",
      synthetic: true,
      kind: "sidecar",
      provider: "claude",
      usage: null,
    });
    const auth = {
      name: "claude-1",
      authIndex: "0",
      email: "claude-one@example.com",
      provider: null,
      planType: "max20",
      paused: false,
      quotaExceeded: false,
      modelsExceeded: [],
      success: 0,
      failed: 0,
      usageSource: "oauth_usage",
      primaryRemainingPercent: 75,
      secondaryRemainingPercent: 96,
    };

    renderWithProviders(<ClaudeAuthCard account={account} auth={auth} />);

    expect(screen.getByText(/CLIProxyAPI/)).toBeInTheDocument();
    expect(screen.queryByText(/Claude/)).toBeNull();
  });

  it("blurs the CLI Proxy API auth title when privacy mode is enabled", () => {
    act(() => {
      usePrivacyStore.setState({ blurred: true });
    });
    const account = createAccountSummary({
      accountId: "claude-sidecar",
      displayName: "CLI Proxy API",
      planType: "claude",
      status: "active",
      synthetic: true,
      kind: "sidecar",
      provider: "claude",
      usage: null,
    });
    const auth = {
      name: "claude-1",
      authIndex: "0",
      email: "claude-one@example.com",
      paused: false,
      quotaExceeded: false,
      modelsExceeded: [],
      success: 0,
      failed: 0,
      usageSource: "oauth_usage",
      primaryRemainingPercent: 75,
      secondaryRemainingPercent: 96,
    };

    const { container } = renderWithProviders(<ClaudeAuthCard account={account} auth={auth} />);

    expect(screen.getByText("claude-one@example.com")).toBeInTheDocument();
    expect(container.querySelector(".privacy-blur")).not.toBeNull();
  });

  it("renders a fallback Claude Usage panel when no auth accounts exist", () => {
    const account = createAccountSummary({
      accountId: "claude-sidecar",
      email: "cliproxyapi.local",
      displayName: "CLI Proxy API",
      planType: "claude",
      status: "active",
      synthetic: true,
      readOnly: true,
      kind: "sidecar",
      provider: "claude",
      usage: {
        primaryRemainingPercent: 75,
        secondaryRemainingPercent: 96,
      },
      resetAtPrimary: "2026-06-10T17:00:00+00:00",
      resetAtSecondary: "2026-06-17T12:00:00+00:00",
      windowMinutesPrimary: 300,
      windowMinutesSecondary: 10080,
    });

    renderWithProviders(<AccountCard account={account} />);

    expect(screen.getByText("Claude Usage")).toBeInTheDocument();
    expect(screen.getByText("Estimated")).toBeInTheDocument();
    expect(screen.getByText("5h")).toBeInTheDocument();
    expect(screen.getByText("Weekly")).toBeInTheDocument();
  });

  it("shows OpenRouter health and requests without a model count", () => {
    const openRouter = createAccountSummary({
      accountId: "openrouter-sidecar",
      email: "openrouter.ai",
      displayName: "OpenRouter",
      planType: "openrouter",
      status: "active",
      synthetic: true,
      readOnly: true,
      kind: "sidecar",
      provider: "openrouter",
      healthStatus: "healthy",
      baseUrl: "https://openrouter.ai/api/v1",
      modelCount: 3,
      usage: null,
      requestUsage: {
        requestCount: 4,
        totalTokens: 100,
        cachedInputTokens: 0,
        totalCostUsd: 0,
        totalSavingsUsd: 0.42,
      },
    });

    renderWithProviders(<AccountCard account={openRouter} />);

    expect(screen.getAllByText("OpenRouter")).toHaveLength(1);
    expect(screen.getByText("Health")).toBeInTheDocument();
    expect(screen.getByText("Healthy")).toBeInTheDocument();
    expect(screen.queryByText("Models")).not.toBeInTheDocument();
    expect(screen.getByText("Requests")).toBeInTheDocument();
    expect(screen.getByText("Saved")).toBeInTheDocument();
    expect(screen.getByText("$0.42")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pause" })).toBeNull();
  });

  it("hides the saved row when there are no savings", () => {
    const openRouter = createAccountSummary({
      accountId: "openrouter-sidecar",
      displayName: "OpenRouter",
      status: "active",
      synthetic: true,
      readOnly: true,
      kind: "sidecar",
      provider: "openrouter",
      healthStatus: "healthy",
      usage: null,
      requestUsage: {
        requestCount: 4,
        totalTokens: 100,
        cachedInputTokens: 0,
        totalCostUsd: 0,
        totalSavingsUsd: 0,
      },
    });

    renderWithProviders(<AccountCard account={openRouter} />);

    expect(screen.queryByText("Saved")).toBeNull();
  });

  it("shows OmniRoute health and requests without a model count", () => {
    const omniRoute = createAccountSummary({
      accountId: "omniroute-sidecar",
      email: "omniroute.local",
      displayName: "OmniRoute",
      planType: "omniroute",
      status: "active",
      synthetic: true,
      readOnly: true,
      kind: "sidecar",
      provider: "omniroute",
      healthStatus: "healthy",
      baseUrl: "http://127.0.0.1:20128/v1",
      modelCount: 117,
      usage: null,
      requestUsage: {
        requestCount: 9,
        totalTokens: 200,
        cachedInputTokens: 0,
        totalCostUsd: 0,
      },
    });

    renderWithProviders(<AccountCard account={omniRoute} />);

    expect(screen.getAllByText("OmniRoute")).toHaveLength(1);
    expect(screen.getByText("Health")).toBeInTheDocument();
    expect(screen.getByText("Healthy")).toBeInTheDocument();
    expect(screen.queryByText("Models")).not.toBeInTheDocument();
    expect(screen.queryByText("117")).not.toBeInTheDocument();
    expect(screen.getByText("Requests")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pause" })).toBeNull();
  });

  it("shows OrcaRouter health and requests without Claude pause/quota UI", () => {
    const orcaRouter = createAccountSummary({
      accountId: "orcarouter-sidecar",
      email: "orcarouter.ai",
      displayName: "OrcaRouter",
      planType: "orcarouter",
      status: "active",
      synthetic: true,
      readOnly: true,
      kind: "sidecar",
      provider: "orcarouter",
      healthStatus: "healthy",
      baseUrl: "https://api.orcarouter.ai/v1",
      modelCount: 3,
      usage: null,
      requestUsage: {
        requestCount: 4,
        totalTokens: 100,
        cachedInputTokens: 0,
        totalCostUsd: 0,
        totalSavingsUsd: 0.42,
      },
    });

    renderWithProviders(<AccountCard account={orcaRouter} />);

    expect(screen.getAllByText("OrcaRouter")).toHaveLength(1);
    expect(screen.getByText("Health")).toBeInTheDocument();
    expect(screen.getByText("Healthy")).toBeInTheDocument();
    expect(screen.queryByText("Models")).not.toBeInTheDocument();
    expect(screen.getByText("Requests")).toBeInTheDocument();
    expect(screen.getByText("Saved")).toBeInTheDocument();
    expect(screen.getByText("$0.42")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pause" })).toBeNull();
  });

  it("disables the limit warm-up toggle for read-only guests", () => {
    const account = createAccountSummary({
      displayName: "Read Only Account",
      limitWarmupEnabled: false,
    });

    render(<AccountCard account={account} readOnly />);

    expect(screen.getByRole("button", { name: "Enable limit warm-up for Read Only Account" })).toBeDisabled();
  });

  it("shows reset action when reset credits are available", () => {
    const account = createAccountSummary({
      availableResetCredits: 2,
      resetCreditNearestExpiresAt: "2026-01-03T12:00:00.000Z",
    });

    render(<AccountCard account={account} />);

    expect(screen.getByRole("button", { name: "Reset (2)" })).toBeInTheDocument();
  });

  it("hides reset action when no reset credits are available", () => {
    const account = createAccountSummary({ availableResetCredits: 0 });

    render(<AccountCard account={account} />);

    expect(screen.queryByRole("button", { name: /Reset \(/ })).not.toBeInTheDocument();
  });

  it("disables reset action for paused accounts", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();
    const account = createAccountSummary({
      accountId: "acc-paused",
      displayName: "Paused Account",
      status: "paused",
      availableResetCredits: 1,
      resetCreditNearestExpiresAt: "2026-01-03T12:00:00.000Z",
    });

    render(<AccountCard account={account} onAction={onAction} />);

    const resetButton = screen.getByRole("button", { name: "Reset (1)" });
    expect(resetButton).toBeDisabled();

    await user.click(resetButton);
    expect(onAction).not.toHaveBeenCalledWith(account, "reset-credit");
  });
});
