/**
 * Quota-display semantics the OpenCode Go Accounts card has to satisfy.
 *
 * The captain asked for a Go card showing five-hour and weekly usage "per model
 * or total for the account, whichever is available". The evidence behind that
 * is thinner than the request implies: the `/zen/go/v1/usage` route is
 * confirmed to exist by an unauthenticated probe, but its response shape comes
 * from reading two third-party parsers, it is undocumented by OpenCode, and
 * whether it reports per-model or account-aggregate usage is not known by
 * anyone who published about it.
 *
 * So the display rules that matter are the ones about *not knowing*: unknown
 * must not render as zero, a per-model selector must not appear when only an
 * aggregate is available, and a stale reading must not look current. These
 * tests pin those rules against the rendering primitives the Go card will be
 * built from, using synthetic data only.
 *
 * The card itself is owned by `codexlb-opencode-go-accounts-r1` and does not
 * exist yet. What is verified here is the shared behavior underneath it - the
 * existing synthetic account card and the formatters - so the rules are
 * executable before the card lands rather than asserted afterwards. Where a
 * rule can only be enforced by the card, the test says so rather than
 * pretending coverage.
 */

import { screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AccountSummarySchema, type AccountSummary } from "@/features/accounts/schemas";
import { formatPercentNullable, formatQuotaResetLabel } from "@/utils/formatters";
import { renderWithProviders } from "@/test/utils";
import { SyntheticAccountDetail } from "@/features/accounts/components/synthetic-account-detail";

const NOW = new Date("2026-09-14T12:00:00.000Z");

function syntheticAccount(overrides: Record<string, unknown> = {}): AccountSummary {
  return AccountSummarySchema.parse({
    accountId: "opencode-go-sidecar",
    email: "opencode.ai",
    displayName: "OpenCode Go",
    planType: "opencode_go",
    status: "active",
    kind: "sidecar",
    provider: "orcarouter",
    readOnly: true,
    synthetic: true,
    healthStatus: "healthy",
    baseUrl: "https://opencode.ai/zen/go/v1",
    additionalQuotas: [],
    limitWarmupEnabled: false,
    sidecarAuths: [],
    ...overrides,
  });
}

describe("quota display semantics for a subscription provider card", () => {
  beforeEach(() => {
    vi.spyOn(Date, "now").mockReturnValue(NOW.getTime());
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe("unknown is not zero", () => {
    it("renders a missing percentage as a placeholder, never as 0%", () => {
      // The single most damaging display bug available here: an operator who
      // reads "0%" concludes their subscription is exhausted and stops working.
      expect(formatPercentNullable(null)).toBe("--");
      expect(formatPercentNullable(undefined)).toBe("--");
      expect(formatPercentNullable("")).toBe("--");
      expect(formatPercentNullable("not-a-number")).toBe("--");
    });

    it("renders a genuine zero as 0%, so exhaustion is still visible", () => {
      // The inverse must hold too, or the fix for the bug above hides a real
      // exhausted state behind the same placeholder.
      expect(formatPercentNullable(0)).toBe("0%");
      expect(formatPercentNullable("0")).toBe("0%");
    });

    it("keeps unknown and zero visually distinct", () => {
      expect(formatPercentNullable(null)).not.toBe(formatPercentNullable(0));
    });
  });

  describe("reset labels", () => {
    it("reports an unusable reset timestamp instead of inventing a time", () => {
      const missing = formatQuotaResetLabel(null);
      const malformed = formatQuotaResetLabel("not-a-date");
      // Whatever the label is, it must not read as a real future reset.
      expect(missing).not.toMatch(/^\d+[hmd]$/);
      expect(malformed).not.toMatch(/^\d+[hmd]$/);
      expect(malformed).toBe(missing);
    });

    it("reports an already-elapsed reset as due rather than as a negative duration", () => {
      const past = new Date(NOW.getTime() - 60_000).toISOString();
      const label = formatQuotaResetLabel(past);
      expect(label).not.toContain("-");
    });

    it("formats a future reset as a relative duration", () => {
      const future = new Date(NOW.getTime() + 3 * 3_600_000).toISOString();
      expect(formatQuotaResetLabel(future)).toMatch(/\d/);
    });
  });

  describe("the synthetic account card", () => {
    it("does not show five-hour or weekly quota rows for a provider that supplies none", () => {
      // The existing card gates quota rows on the Claude provider specifically,
      // rather than showing empty windows for every synthetic account. A Go
      // card must make the same choice explicitly: show the windows only when
      // the provider actually supplies them, so absence is not rendered as an
      // empty reading the operator may misread as zero.
      renderWithProviders(<SyntheticAccountDetail account={syntheticAccount()} busy={false} />);

      expect(screen.queryByText(/5h remaining/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/weekly remaining/i)).not.toBeInTheDocument();
      // Connection state is still shown, so the card is not simply blank.
      expect(screen.getByText(/Base URL/i)).toBeInTheDocument();
    });

    it("labels usage provenance rather than presenting every number as measured", () => {
      // A subscription provider's windows may be estimated, reported, or
      // absent, and those are different claims. The existing card carries a
      // provenance word in the label ("Estimated"/"OAuth"/"Unavailable"); the
      // Go card must not drop that distinction, because a list-price estimate
      // and an actual charge are not the same quantity.
      renderWithProviders(
        <SyntheticAccountDetail
          account={syntheticAccount({ provider: "claude", usage: null })}
          busy={false}
        />,
      );

      const fiveHour = screen.getByText(/5h remaining/i);
      expect(fiveHour.textContent).toMatch(/Unavailable|Estimated|OAuth/);
    });

    it("shows unavailable windows as placeholders, not as zero, end to end", () => {
      renderWithProviders(
        <SyntheticAccountDetail
          account={syntheticAccount({ provider: "claude", usage: null })}
          busy={false}
        />,
      );

      // The label and its value are siblings inside the field wrapper, so step
      // up one level from the label before scoping the value assertions.
      const fiveHourField = screen.getByText(/5h remaining/i).parentElement;
      expect(fiveHourField).not.toBeNull();
      const field = fiveHourField as HTMLElement;
      expect(within(field).getByText(/--/)).toBeInTheDocument();
      expect(within(field).queryByText(/\b0%/)).not.toBeInTheDocument();
    });

    it("renders a long display name and base URL without losing the surrounding layout", () => {
      // Long text is the usual way a card's layout breaks. The base URL is the
      // realistic long value here, and it is rendered in a monospace field.
      const longUrl = `https://opencode.ai/zen/go/v1/${"segment-".repeat(20)}end`;
      renderWithProviders(
        <SyntheticAccountDetail
          account={syntheticAccount({
            displayName: "OpenCode Go subscription account with an unusually long display name",
            baseUrl: longUrl,
          })}
          busy={false}
        />,
      );

      expect(screen.getByText(longUrl)).toBeInTheDocument();
      expect(
        screen.getByText(/OpenCode Go subscription account with an unusually long display name/),
      ).toBeInTheDocument();
    });

    it("keeps the connection test control reachable and labelled", () => {
      renderWithProviders(<SyntheticAccountDetail account={syntheticAccount()} busy={false} />);

      const buttons = screen.getAllByRole("button");
      expect(buttons.length).toBeGreaterThan(0);
      for (const button of buttons) {
        // Every control needs an accessible name; an icon-only button with none
        // is unreachable by keyboard and screen reader alike.
        expect(button.textContent?.trim() || button.getAttribute("aria-label")).toBeTruthy();
      }
    });

    it("disables its controls while an account action is in flight", () => {
      renderWithProviders(<SyntheticAccountDetail account={syntheticAccount()} busy={true} />);

      const buttons = screen.getAllByRole("button").filter((button) => !button.closest("a"));
      expect(buttons.some((button) => button.hasAttribute("disabled"))).toBe(true);
    });
  });

  describe("per-model selector availability", () => {
    /**
     * These encode the rule rather than the widget: a model selector may only
     * appear when per-model data exists. Whether the Go provider reports
     * per-model windows at all is unverified, so the Go card must derive the
     * selector from the data it received and never render a chooser over an
     * account-wide number relabelled as a model's.
     */
    type QuotaShape = { scope: "aggregate" | "per_model"; models?: string[] };

    function selectorShouldRender(quota: QuotaShape | null): boolean {
      return quota?.scope === "per_model" && (quota.models?.length ?? 0) > 1;
    }

    it("hides the selector when the provider reported only an account aggregate", () => {
      expect(selectorShouldRender({ scope: "aggregate" })).toBe(false);
    });

    it("hides the selector when nothing was reported at all", () => {
      expect(selectorShouldRender(null)).toBe(false);
    });

    it("hides the selector when per-model data covers a single model", () => {
      // A one-entry dropdown is a control that cannot be used; it implies a
      // choice the data does not offer.
      expect(selectorShouldRender({ scope: "per_model", models: ["glm-5.3"] })).toBe(false);
    });

    it("shows the selector only when several models were actually reported", () => {
      expect(selectorShouldRender({ scope: "per_model", models: ["glm-5.3", "kimi-k3"] })).toBe(true);
    });
  });

  describe("staleness", () => {
    function isStale(lastCheckedAt: string | null, maxAgeMs: number): boolean {
      if (!lastCheckedAt) {
        return true;
      }
      return Date.now() - new Date(lastCheckedAt).getTime() > maxAgeMs;
    }

    it("treats a never-checked reading as stale rather than as current", () => {
      expect(isStale(null, 300_000)).toBe(true);
    });

    it("treats an old reading as stale", () => {
      const old = new Date(NOW.getTime() - 3_600_000).toISOString();
      expect(isStale(old, 300_000)).toBe(true);
    });

    it("treats a recent reading as current", () => {
      const recent = new Date(NOW.getTime() - 30_000).toISOString();
      expect(isStale(recent, 300_000)).toBe(false);
    });

    it("shows the last-checked time on the card so staleness is legible", () => {
      renderWithProviders(<SyntheticAccountDetail account={syntheticAccount()} busy={false} />);
      expect(screen.getByText(/Last checked/i)).toBeInTheDocument();
      // Never-checked states say "Never" rather than showing a blank that reads
      // as "checked, nothing to report".
      expect(screen.getByText(/Never/)).toBeInTheDocument();
    });
  });

  describe("existing account cards are unaffected", () => {
    it("still renders the OrcaRouter card with its own description", () => {
      renderWithProviders(
        <SyntheticAccountDetail
          account={syntheticAccount({ displayName: "OrcaRouter", provider: "orcarouter" })}
          busy={false}
        />,
      );
      expect(screen.getByText(/Read-only OrcaRouter account/i)).toBeInTheDocument();
    });

    it("still renders the Claude card with its quota rows", () => {
      renderWithProviders(
        <SyntheticAccountDetail
          account={syntheticAccount({ displayName: "Claude", provider: "claude" })}
          busy={false}
        />,
      );
      expect(screen.getByText(/Read-only Claude sidecar account/i)).toBeInTheDocument();
      expect(screen.getByText(/5h remaining/i)).toBeInTheDocument();
    });

    it("does not give an unknown provider Claude's quota controls by default", () => {
      // The allowlist in the component exists for exactly this: a new
      // integration must not inherit pause/quota controls it has no data for.
      renderWithProviders(
        <SyntheticAccountDetail
          account={syntheticAccount({ provider: "opencode_go" })}
          busy={false}
        />,
      );
      expect(screen.queryByText(/5h remaining/i)).not.toBeInTheDocument();
    });
  });
});
