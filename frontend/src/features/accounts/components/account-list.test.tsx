import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AccountList } from "@/features/accounts/components/account-list";
import { AccountSummarySchema, type AccountSummary } from "@/features/accounts/schemas";
import { useAccountQuotaDisplayStore } from "@/hooks/use-account-quota-display";

function accountList(values: unknown[]): AccountSummary[] {
  return values.map((value) => AccountSummarySchema.parse(value));
}

describe("AccountList", () => {
  beforeEach(() => {
    useAccountQuotaDisplayStore.setState({ quotaDisplay: "both" });
    vi.spyOn(Date, "now").mockReturnValue(
      new Date("2026-01-01T12:00:00.000Z").getTime(),
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders items and filters by search", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();

    render(
      <AccountList
        accounts={accountList([
          {
            accountId: "acc-1",
            email: "primary@example.com",
            displayName: "Primary",
            planType: "plus",
            status: "active",
            limitWarmupEnabled: false,
            additionalQuotas: [],
          },
          {
            accountId: "acc-2",
            email: "secondary@example.com",
            displayName: "Secondary",
            planType: "pro",
            status: "paused",
            limitWarmupEnabled: false,
            additionalQuotas: [],
          },
        ])}
        selectedAccountId="acc-1"
        onSelect={onSelect}
        onOpenImport={() => {}}
        onOpenOauth={() => {}}
      />,
    );

    expect(screen.getByText("primary@example.com")).toBeInTheDocument();
    expect(screen.getByText("secondary@example.com")).toBeInTheDocument();

    await user.type(
      screen.getByPlaceholderText("Search accounts..."),
      "secondary",
    );
    expect(screen.queryByText("primary@example.com")).not.toBeInTheDocument();
    expect(screen.getByText("secondary@example.com")).toBeInTheDocument();

    await user.click(screen.getByText("secondary@example.com"));
    expect(onSelect).toHaveBeenCalledWith("acc-2");
  });

  it("sorts accounts by the rows actually rendered", () => {
    useAccountQuotaDisplayStore.setState({ quotaDisplay: "weekly" });

    render(
      <AccountList
        accounts={accountList([
          {
            accountId: "acc-hidden-early",
            email: "hidden-early@example.com",
            displayName: "Hidden Early",
            planType: "plus",
            status: "active",
            limitWarmupEnabled: false,
            usage: {
              primaryRemainingPercent: 42,
              secondaryRemainingPercent: 18,
            },
            resetAtPrimary: "2026-01-01T12:05:00.000Z",
            resetAtSecondary: "2026-01-01T13:00:00.000Z",
            windowMinutesPrimary: 300,
            windowMinutesSecondary: 10_080,
            additionalQuotas: [],
          },
          {
            accountId: "acc-visible-early",
            email: "visible-early@example.com",
            displayName: "Visible Early",
            planType: "plus",
            status: "active",
            limitWarmupEnabled: false,
            usage: {
              primaryRemainingPercent: 82,
              secondaryRemainingPercent: 73,
            },
            resetAtPrimary: "2026-01-01T12:30:00.000Z",
            resetAtSecondary: "2026-01-01T12:10:00.000Z",
            windowMinutesPrimary: 300,
            windowMinutesSecondary: 10_080,
            additionalQuotas: [],
          },
        ])}
        selectedAccountId={null}
        onSelect={() => {}}
        onOpenImport={() => {}}
        onOpenOauth={() => {}}
      />,
    );

    expect(
      screen
        .getAllByText(/^(Hidden Early|Visible Early)$/)
        .map((el) => el.textContent),
    ).toEqual(["Visible Early", "Hidden Early"]);
  });

  it("ignores elapsed reset timestamps when sorting", () => {
    render(
      <AccountList
        accounts={accountList([
          {
            accountId: "acc-stale",
            email: "stale@example.com",
            displayName: "Stale",
            planType: "plus",
            status: "active",
            limitWarmupEnabled: false,
            usage: {
              primaryRemainingPercent: 42,
              secondaryRemainingPercent: 18,
            },
            resetAtPrimary: "2026-01-01T11:30:00.000Z",
            resetAtSecondary: "2026-01-01T11:45:00.000Z",
            windowMinutesPrimary: 300,
            windowMinutesSecondary: 10_080,
            additionalQuotas: [],
          },
          {
            accountId: "acc-fresh",
            email: "fresh@example.com",
            displayName: "Fresh",
            planType: "plus",
            status: "active",
            limitWarmupEnabled: false,
            usage: {
              primaryRemainingPercent: 82,
              secondaryRemainingPercent: 73,
            },
            resetAtPrimary: "2026-01-01T12:30:00.000Z",
            resetAtSecondary: "2026-01-01T12:20:00.000Z",
            windowMinutesPrimary: 300,
            windowMinutesSecondary: 10_080,
            additionalQuotas: [],
          },
        ])}
        selectedAccountId={null}
        onSelect={() => {}}
        onOpenImport={() => {}}
        onOpenOauth={() => {}}
      />,
    );

    expect(
      screen.getAllByText(/^(Fresh|Stale)$/).map((el) => el.textContent),
    ).toEqual(["Fresh", "Stale"]);
  });

  it("sorts legacy primary quota rows by their reset timestamp", () => {
    render(
      <AccountList
        accounts={accountList([
          {
            accountId: "acc-late",
            email: "late@example.com",
            displayName: "Late",
            planType: "plus",
            status: "active",
            limitWarmupEnabled: false,
            usage: {
              primaryRemainingPercent: 42,
              secondaryRemainingPercent: null,
            },
            resetAtPrimary: "2026-01-01T13:00:00.000Z",
            resetAtSecondary: null,
            windowMinutesPrimary: null,
            windowMinutesSecondary: null,
            additionalQuotas: [],
          },
          {
            accountId: "acc-early",
            email: "early@example.com",
            displayName: "Early",
            planType: "plus",
            status: "active",
            limitWarmupEnabled: false,
            usage: {
              primaryRemainingPercent: 82,
              secondaryRemainingPercent: null,
            },
            resetAtPrimary: "2026-01-01T12:10:00.000Z",
            resetAtSecondary: null,
            windowMinutesPrimary: null,
            windowMinutesSecondary: null,
            additionalQuotas: [],
          },
        ])}
        selectedAccountId={null}
        onSelect={() => {}}
        onOpenImport={() => {}}
        onOpenOauth={() => {}}
      />,
    );

    expect(
      screen.getAllByText(/^(Early|Late)$/).map((el) => el.textContent),
    ).toEqual(["Early", "Late"]);
  });

  it("sorts accounts by name", () => {
    render(
      <AccountList
        accounts={accountList([
          {
            accountId: "acc-z",
            email: "z@example.com",
            displayName: "Zeta",
            planType: "pro",
            status: "active",
            limitWarmupEnabled: false,
            resetAtPrimary: "2026-01-01T12:30:00.000Z",
            additionalQuotas: [],
          },
          {
            accountId: "acc-a",
            email: "a@example.com",
            displayName: "Alpha",
            planType: "plus",
            status: "active",
            limitWarmupEnabled: false,
            resetAtPrimary: "2026-01-01T12:10:00.000Z",
            additionalQuotas: [],
          },
        ])}
        selectedAccountId={null}
        onSelect={() => {}}
        onOpenImport={() => {}}
        onOpenOauth={() => {}}
        sortMode="name_asc"
        onSortModeChange={() => {}}
      />,
    );

    expect(screen.getAllByText(/^(Alpha|Zeta)$/).map((el) => el.textContent)).toEqual([
      "Alpha",
      "Zeta",
    ]);
  });

  it("supports reverse name sorting", () => {
    render(
      <AccountList
        accounts={accountList([
          {
            accountId: "acc-b",
            email: "b@example.com",
            displayName: "Beta",
            planType: "plus",
            status: "active",
            limitWarmupEnabled: false,
            resetAtPrimary: "2026-01-01T12:10:00.000Z",
            additionalQuotas: [],
          },
          {
            accountId: "acc-a",
            email: "a@example.com",
            displayName: "Alpha",
            planType: "plus",
            status: "active",
            limitWarmupEnabled: false,
            resetAtPrimary: "2026-01-01T12:20:00.000Z",
            additionalQuotas: [],
          },
        ])}
        selectedAccountId={null}
        onSelect={() => {}}
        onOpenImport={() => {}}
        onOpenOauth={() => {}}
        sortMode="name_desc"
        onSortModeChange={() => {}}
      />,
    );

    expect(screen.getAllByText(/^(Alpha|Beta)$/).map((el) => el.textContent)).toEqual([
      "Beta",
      "Alpha",
    ]);
  });

  it("can sort by latest reset first", () => {
    render(
      <AccountList
        accounts={accountList([
          {
            accountId: "acc-a",
            email: "a@example.com",
            displayName: "Alpha",
            planType: "plus",
            status: "active",
            limitWarmupEnabled: false,
            resetAtPrimary: "2026-01-01T12:10:00.000Z",
            additionalQuotas: [],
          },
          {
            accountId: "acc-z",
            email: "z@example.com",
            displayName: "Zeta",
            planType: "plus",
            status: "active",
            limitWarmupEnabled: false,
            resetAtPrimary: "2026-01-01T12:40:00.000Z",
            additionalQuotas: [],
          },
        ])}
        selectedAccountId={null}
        onSelect={() => {}}
        onOpenImport={() => {}}
        onOpenOauth={() => {}}
        sortMode="reset_latest"
        onSortModeChange={() => {}}
      />,
    );

    expect(screen.getAllByText(/^(Zeta|Alpha)$/).map((el) => el.textContent)).toEqual([
      "Zeta",
      "Alpha",
    ]);
  });

  it("keeps unknown resets last when sorting by latest reset", () => {
    render(
      <AccountList
        accounts={accountList([
          {
            accountId: "acc-unknown",
            email: "unknown@example.com",
            displayName: "Unknown",
            planType: "plus",
            status: "active",
            limitWarmupEnabled: false,
            additionalQuotas: [],
          },
          {
            accountId: "acc-stale",
            email: "stale@example.com",
            displayName: "Stale",
            planType: "plus",
            status: "active",
            limitWarmupEnabled: false,
            resetAtPrimary: "2026-01-01T11:30:00.000Z",
            additionalQuotas: [],
          },
          {
            accountId: "acc-latest",
            email: "latest@example.com",
            displayName: "Latest",
            planType: "plus",
            status: "active",
            limitWarmupEnabled: false,
            resetAtPrimary: "2026-01-01T12:40:00.000Z",
            additionalQuotas: [],
          },
          {
            accountId: "acc-earlier",
            email: "earlier@example.com",
            displayName: "Earlier",
            planType: "plus",
            status: "active",
            limitWarmupEnabled: false,
            resetAtPrimary: "2026-01-01T12:10:00.000Z",
            additionalQuotas: [],
          },
        ])}
        selectedAccountId={null}
        onSelect={() => {}}
        onOpenImport={() => {}}
        onOpenOauth={() => {}}
        sortMode="reset_latest"
        onSortModeChange={() => {}}
      />,
    );

    expect(screen.getAllByText(/^(Latest|Earlier|Stale|Unknown)$/).map((el) => el.textContent)).toEqual([
      "Latest",
      "Earlier",
      "Stale",
      "Unknown",
    ]);
  });

  it("shows empty state when no items match filter", async () => {
    const user = userEvent.setup();

    render(
      <AccountList
        accounts={accountList([
          {
            accountId: "acc-1",
            email: "primary@example.com",
            displayName: "Primary",
            planType: "plus",
            status: "active",
            limitWarmupEnabled: false,
            additionalQuotas: [],
          },
        ])}
        selectedAccountId={null}
        onSelect={() => {}}
        onOpenImport={() => {}}
        onOpenOauth={() => {}}
      />,
    );

    await user.type(
      screen.getByPlaceholderText("Search accounts..."),
      "not-found",
    );
    expect(screen.getByText("No matching accounts")).toBeInTheDocument();
  });

  it("keeps the add account action outside the scrollable account list", () => {
    render(
      <AccountList
        accounts={[
          {
            accountId: "acc-1",
            email: "primary@example.com",
            displayName: "Primary",
            planType: "plus",
            status: "active",
            limitWarmupEnabled: false,
            additionalQuotas: [],
          },
        ]}
        selectedAccountId={null}
        onSelect={() => {}}
        onOpenImport={() => {}}
        onOpenOauth={() => {}}
      />,
    );

    const addAccountButton = screen.getByRole("button", { name: "Add account" });
    const scrollRegion = screen.getByTestId("account-list-scroll-region");

    expect(scrollRegion).not.toContainElement(addAccountButton);
  });

  it("filters re-auth required accounts by status", async () => {
    const user = userEvent.setup();

    render(
      <AccountList
        accounts={accountList([
          {
            accountId: "acc-active",
            email: "active@example.com",
            displayName: "Active",
            planType: "plus",
            status: "active",
            limitWarmupEnabled: false,
            additionalQuotas: [],
          },
          {
            accountId: "acc-reauth",
            email: "reauth@example.com",
            displayName: "Needs Reauth",
            planType: "pro",
            status: "reauth_required",
            limitWarmupEnabled: false,
            additionalQuotas: [],
          },
        ])}
        selectedAccountId={null}
        onSelect={() => {}}
        onOpenImport={() => {}}
        onOpenOauth={() => {}}
      />,
    );

    await user.click(screen.getByRole("combobox", { name: "Filter accounts by status" }));
    await user.click(screen.getByRole("option", { name: "Reauth required" }));

    expect(screen.queryByText("active@example.com")).not.toBeInTheDocument();
    expect(screen.getByText("reauth@example.com")).toBeInTheDocument();
  });

  it("uses the backend duplicate indicator instead of recomputing by email", () => {
    render(
      <AccountList
        accounts={accountList([
          {
            accountId: "d48f0bfc-8ea6-48a7-8d76-d0e5ef1816c5_6f12b5d5",
            email: "dup@example.com",
            displayName: "Same email, different workspace",
            planType: "plus",
            status: "active",
            limitWarmupEnabled: false,
            isEmailDuplicate: false,
            additionalQuotas: [],
          },
          {
            accountId: "7f9de2ad-7621-4a6f-88bc-ec7f3d914701_91a95cee",
            email: "dup@example.com",
            displayName: "Same email, duplicate slot",
            planType: "plus",
            status: "active",
            limitWarmupEnabled: false,
            isEmailDuplicate: true,
            additionalQuotas: [],
          },
          {
            accountId: "acc-3",
            email: "unique@example.com",
            displayName: "Unique",
            planType: "pro",
            status: "active",
            limitWarmupEnabled: false,
            additionalQuotas: [],
          },
        ])}
        selectedAccountId={null}
        onSelect={() => {}}
        onOpenImport={() => {}}
        onOpenOauth={() => {}}
      />,
    );

    expect(
      screen.queryByText(
        (_content, el) =>
          el?.tagName === "P" &&
          !!el.textContent?.match(
            /dup@example\.com .* ID d48f0bfc\.\.\.12b5d5/,
          ),
      ),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(
        (_content, el) =>
          el?.tagName === "P" &&
          !!el.textContent?.match(
            /dup@example\.com .* ID 7f9de2ad\.\.\.a95cee/,
          ),
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(
        (_content, el) =>
          el?.tagName === "P" &&
          !!el.textContent?.match(/unique@example\.com \| ID/),
      ),
    ).not.toBeInTheDocument();
  });

  it("renders estimated quota rows for synthetic sidecar accounts", () => {
    render(
      <AccountList
        accounts={accountList([
          {
            accountId: "claude-sidecar",
            email: "cliproxyapi.local",
            displayName: "Claude via CLIProxyAPI",
            planType: "claude",
            status: "active",
            synthetic: true,
            readOnly: true,
            kind: "sidecar",
            provider: "claude",
            baseUrl: "http://127.0.0.1:8317",
            limitWarmupEnabled: false,
            usage: {
              primaryRemainingPercent: 75,
              secondaryRemainingPercent: 96,
            },
            resetAtPrimary: "2026-01-01T17:00:00.000Z",
            resetAtSecondary: "2026-01-08T12:00:00.000Z",
            windowMinutesPrimary: 300,
            windowMinutesSecondary: 10080,
            additionalQuotas: [],
          },
        ])}
        selectedAccountId={null}
        onSelect={() => {}}
        onOpenImport={() => {}}
        onOpenOauth={() => {}}
      />,
    );

    expect(screen.getByText("5h estimated")).toBeInTheDocument();
    expect(screen.getByText("Weekly estimated")).toBeInTheDocument();
  });

  it("omits provider badges and model rows for OpenRouter and OmniRoute synthetic items", () => {
    render(
      <AccountList
        accounts={accountList([
          {
            accountId: "openrouter-sidecar",
            email: "openrouter.local",
            displayName: "OpenRouter",
            planType: "openrouter",
            status: "active",
            synthetic: true,
            readOnly: true,
            kind: "sidecar",
            provider: "openrouter",
            baseUrl: "https://openrouter.ai/api/v1",
            modelCount: 12,
            limitWarmupEnabled: false,
            additionalQuotas: [],
          },
          {
            accountId: "omniroute-sidecar",
            email: "omniroute.local",
            displayName: "OmniRoute",
            planType: "omniroute",
            status: "active",
            synthetic: true,
            readOnly: true,
            kind: "sidecar",
            provider: "omniroute",
            baseUrl: "http://127.0.0.1:20128/v1",
            modelCount: 7,
            limitWarmupEnabled: false,
            additionalQuotas: [],
          },
        ])}
        selectedAccountId={null}
        onSelect={() => {}}
        onOpenImport={() => {}}
        onOpenOauth={() => {}}
      />,
    );

    // Provider name appears once (the title), not duplicated as a badge.
    expect(screen.getAllByText("OpenRouter")).toHaveLength(1);
    expect(screen.getAllByText("OmniRoute")).toHaveLength(1);
    expect(screen.queryByText("Models")).not.toBeInTheDocument();
  });

  it("renders placeholder quota rows for synthetic sidecar accounts without usage yet", () => {
    render(
      <AccountList
        accounts={accountList([
          {
            accountId: "claude-sidecar",
            email: "cliproxyapi.local",
            displayName: "Claude via CLIProxyAPI",
            planType: "claude",
            status: "active",
            synthetic: true,
            readOnly: true,
            kind: "sidecar",
            provider: "claude",
            baseUrl: "http://127.0.0.1:8317",
            limitWarmupEnabled: false,
            usage: null,
            additionalQuotas: [],
          },
        ])}
        selectedAccountId={null}
        onSelect={() => {}}
        onOpenImport={() => {}}
        onOpenOauth={() => {}}
      />,
    );

    expect(screen.getByText("5h unavailable")).toBeInTheDocument();
    expect(screen.getByText("Weekly unavailable")).toBeInTheDocument();
  });
});
