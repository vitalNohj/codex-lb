import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { AccountCards } from "@/features/dashboard/components/account-cards";
import { createAccountSummary } from "@/test/mocks/factories";
import { renderWithProviders } from "@/test/utils";

describe("AccountCards", () => {
  it("caps the dashboard account grid at two visible rows without clipping taller cards", () => {
    render(
      <AccountCards
        accounts={Array.from({ length: 7 }, (_, index) =>
          createAccountSummary({
            accountId: `acc-${index + 1}`,
            email: `account-${index + 1}@example.com`,
            displayName: `Account ${index + 1}`,
          }),
        )}
        onAction={vi.fn()}
      />,
    );

    expect(screen.getByTestId("dashboard-account-cards")).toHaveStyle({
      maxHeight: "calc(2 * 16rem + 1rem)",
    });
  });

  it("keeps the scrollbar hidden on the dashboard account grid", () => {
    render(
      <AccountCards
        accounts={[createAccountSummary(), createAccountSummary({ accountId: "acc-2", email: "two@example.com" })]}
        onAction={vi.fn()}
      />,
    );

    expect(screen.getByTestId("dashboard-account-cards")).toHaveClass(
      "overflow-y-auto",
      "[scrollbar-width:none]",
      "[&::-webkit-scrollbar]:hidden",
    );
  });

  it("gives each warm-up toggle a descriptive account-specific name", () => {
    render(
      <AccountCards
        accounts={[
          createAccountSummary({
            accountId: "acc-1",
            email: "one@example.com",
            displayName: "One Account",
            limitWarmupEnabled: false,
          }),
          createAccountSummary({
            accountId: "acc-2",
            email: "two@example.com",
            displayName: "Two Account",
            limitWarmupEnabled: true,
          }),
        ]}
        onAction={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Enable limit warm-up for One Account" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Disable limit warm-up for Two Account" })).toBeInTheDocument();
  });

  it("shows account ids only for backend-marked duplicate account slots", () => {
    render(
      <AccountCards
        accounts={[
          createAccountSummary({
            accountId: "d48f0bfc-8ea6-48a7-8d76-d0e5ef1816c5_6f12b5d5",
            email: "dup@example.com",
            displayName: "Same email, different workspace",
            isEmailDuplicate: false,
          }),
          createAccountSummary({
            accountId: "7f9de2ad-7621-4a6f-88bc-ec7f3d914701_91a95cee",
            email: "dup@example.com",
            displayName: "Same email, duplicate slot",
            isEmailDuplicate: true,
          }),
        ]}
        onAction={vi.fn()}
      />,
    );

    expect(screen.queryByText((_content, el) => el?.tagName === "P" && !!el.textContent?.match(/dup@example\.com .* ID d48f0bfc\.\.\.12b5d5/))).not.toBeInTheDocument();
    expect(screen.getByText((_content, el) => el?.tagName === "P" && !!el.textContent?.match(/dup@example\.com .* ID 7f9de2ad\.\.\.a95cee/))).toBeInTheDocument();
  });

  it("expands a Claude sidecar account into one card per auth account", () => {
    renderWithProviders(
      <AccountCards
        accounts={[
          createAccountSummary({
            accountId: "claude-sidecar",
            displayName: "CLI Proxy API",
            planType: "claude",
            status: "active",
            synthetic: true,
            kind: "sidecar",
            provider: "claude",
            usage: null,
            sidecarAuths: [
              {
                name: "claude-1",
                authIndex: "0",
                email: "one@example.com",
                paused: false,
                quotaExceeded: false,
                modelsExceeded: [],
                success: 0,
                failed: 0,
                usageSource: "oauth_usage",
                primaryRemainingPercent: 75,
                secondaryRemainingPercent: 96,
              },
              {
                name: "claude-2",
                authIndex: "1",
                email: "two@example.com",
                paused: true,
                quotaExceeded: false,
                modelsExceeded: [],
                success: 0,
                failed: 0,
                usageSource: "oauth_usage",
                primaryRemainingPercent: 100,
                secondaryRemainingPercent: 38,
              },
            ],
          }),
        ]}
        onAction={vi.fn()}
      />,
    );

    expect(screen.getByText("one@example.com")).toBeInTheDocument();
    expect(screen.getByText("two@example.com")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pause one@example.com" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Resume two@example.com" })).toBeInTheDocument();
  });

  // Regression: the expanders classified any synthetic that was not OpenRouter
  // or OmniRoute as Claude, so a provider that later emits sidecarAuths would
  // silently inherit Claude pause controls. The check is now an allowlist.
  it("does not expand a non-Claude synthetic into Claude auth cards", () => {
    renderWithProviders(
      <AccountCards
        accounts={[
          createAccountSummary({
            accountId: "orcarouter-sidecar",
            displayName: "OrcaRouter",
            status: "active",
            synthetic: true,
            kind: "sidecar",
            provider: "orcarouter",
            usage: null,
            sidecarAuths: [
              {
                name: "orca-1",
                authIndex: "0",
                email: "orca-auth@example.com",
                paused: false,
                quotaExceeded: false,
                modelsExceeded: [],
                success: 0,
                failed: 0,
              },
            ],
          }),
        ]}
        onAction={vi.fn()}
      />,
    );

    expect(screen.getByText("OrcaRouter")).toBeInTheDocument();
    expect(screen.queryByText("orca-auth@example.com")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pause orca-auth@example.com" })).not.toBeInTheDocument();
  });

  // Regression: the allowlist required provider === "claude" exactly, but the
  // schema declares provider as nullable/optional and the card subtitle already
  // falls back to Claude, so a Claude summary without a provider silently lost
  // its per-auth cards and pause controls.
  it("still expands a Claude synthetic whose provider is absent", () => {
    renderWithProviders(
      <AccountCards
        accounts={[
          createAccountSummary({
            accountId: "claude-sidecar",
            displayName: "CLI Proxy API",
            status: "active",
            synthetic: true,
            kind: "sidecar",
            provider: null,
            usage: null,
            sidecarAuths: [
              {
                name: "claude-1",
                authIndex: "0",
                email: "one@example.com",
                paused: false,
                quotaExceeded: false,
                modelsExceeded: [],
                success: 0,
                failed: 0,
              },
            ],
          }),
        ]}
        onAction={vi.fn()}
      />,
    );

    // ClaudeAuthCard titles each card with the auth identity; the fallback
    // SyntheticAccountCard would title it with the account displayName instead.
    expect(screen.getByText("one@example.com")).toBeInTheDocument();
    expect(screen.queryByText("CLI Proxy API")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pause one@example.com" })).toBeInTheDocument();
  });

  it("links the empty-account state to the Accounts page", () => {
    render(
      <MemoryRouter>
        <AccountCards accounts={[]} />
      </MemoryRouter>,
    );

    expect(screen.getByRole("link", { name: "Add accounts" })).toHaveAttribute("href", "/accounts");
  });
});
