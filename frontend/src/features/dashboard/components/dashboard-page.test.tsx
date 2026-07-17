import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { renderWithProviders } from "@/test/utils";
import {
  createAccountSummary,
  createDashboardOverview,
  createDashboardProjections,
  type DashboardOverview,
} from "@/test/mocks/factories";
import { useAccountMutations } from "@/features/accounts/hooks/use-accounts";
import { useDashboard, useDashboardProjections } from "@/features/dashboard/hooks/use-dashboard";
import { useRequestLogs } from "@/features/dashboard/hooks/use-request-logs";
import { buildDashboardView } from "@/features/dashboard/utils";
import { useDashboardPreferencesStore } from "@/hooks/use-dashboard-preferences";

import { DashboardPage } from "./dashboard-page";

const {
  accountCardsSpy,
  accountListSpy,
  accountSummaryLineSpy,
  requestFiltersSpy,
  recentRequestsTableSpy,
} = vi.hoisted(() => ({
  accountCardsSpy: vi.fn(),
  accountListSpy: vi.fn(),
  accountSummaryLineSpy: vi.fn(),
  requestFiltersSpy: vi.fn(),
  recentRequestsTableSpy: vi.fn(),
}));

vi.mock("@/features/accounts/hooks/use-accounts", () => ({
  useAccountMutations: vi.fn(),
}));

vi.mock("@/features/dashboard/hooks/use-dashboard", () => ({
  useDashboard: vi.fn(),
  useDashboardProjections: vi.fn(),
}));

vi.mock("@/features/dashboard/hooks/use-request-logs", () => ({
  useRequestLogs: vi.fn(),
}));

vi.mock("@/features/dashboard/utils", () => ({
  buildDashboardView: vi.fn(),
  accountTypeKey: (account: {
    synthetic?: boolean;
    provider?: string | null;
  }) => {
    if (!account.synthetic) {
      return "codex";
    }
    if (account.provider === "openrouter") {
      return "openrouter";
    }
    if (account.provider === "omniroute") {
      return "omniroute";
    }
    if (account.provider === "claude") {
      return "cliproxy";
    }
    return "other";
  },
}));

vi.mock("@/features/dashboard/components/account-cards", () => ({
  AccountCards: ({ accounts }: { accounts: Array<{ accountId: string }> }) => {
    accountCardsSpy(accounts);
    return <div data-testid="account-cards">Cards for {accounts.length} accounts</div>;
  },
}));

vi.mock("@/features/dashboard/components/account-list", () => ({
  AccountList: ({
    accounts,
    sort,
    onSortChange,
  }: {
    accounts: Array<{ accountId: string }>;
    sort: { key: string; direction: string } | null;
    onSortChange: (sort: { key: string; direction: string }) => void;
  }) => {
    accountListSpy({ accounts, sort });
    return (
      <button
        type="button"
        data-testid="account-list"
        onClick={() => onSortChange({ key: "credits", direction: "desc" })}
      >
        List for {accounts.length} accounts
      </button>
    );
  },
}));

vi.mock("@/features/dashboard/components/account-summary-line", () => ({
  AccountSummaryLine: ({ accounts }: { accounts: Array<{ accountId: string }> }) => {
    accountSummaryLineSpy(accounts);
    return <div data-testid="account-summary-line">Summary for {accounts.length} accounts</div>;
  },
}));

vi.mock("@/features/dashboard/components/dashboard-skeleton", () => ({
  DashboardSkeleton: () => <div data-testid="dashboard-skeleton" />,
}));

vi.mock("@/features/dashboard/components/filters/overview-timeframe-select", () => ({
  OverviewTimeframeSelect: () => <div data-testid="overview-timeframe-select" />,
}));

vi.mock("@/features/dashboard/components/filters/request-filters", () => ({
  RequestFilters: ({
    viewMode,
    onViewModeChange,
  }: {
    viewMode: string;
    onViewModeChange: (mode: "expanded") => void;
  }) => {
    requestFiltersSpy({ viewMode });
    return (
      <button
        type="button"
        data-testid="request-filters"
        onClick={() => onViewModeChange("expanded")}
      >
        Filters in {viewMode}
      </button>
    );
  },
}));

vi.mock("@/features/dashboard/components/recent-requests-table", () => ({
  RecentRequestsTable: ({ viewMode }: { viewMode: string }) => {
    recentRequestsTableSpy({ viewMode });
    return <div data-testid="recent-requests-table">Table in {viewMode}</div>;
  },
}));

vi.mock("@/features/dashboard/components/stats-grid", () => ({
  StatsGrid: () => <div data-testid="stats-grid" />,
}));

vi.mock("@/features/dashboard/components/usage-donuts", () => ({
  UsageDonuts: () => <div data-testid="usage-donuts" />,
}));

vi.mock("@/features/dashboard/components/weekly-credits-pace-card", () => ({
  WeeklyCreditsPaceCard: () => <div data-testid="weekly-credits-pace-card" />,
}));

const useAccountMutationsMock = vi.mocked(useAccountMutations);
const useDashboardMock = vi.mocked(useDashboard);
const useDashboardProjectionsMock = vi.mocked(useDashboardProjections);
const useRequestLogsMock = vi.mocked(useRequestLogs);
const buildDashboardViewMock = vi.mocked(buildDashboardView);

describe("DashboardPage", () => {
  beforeEach(() => {
    accountCardsSpy.mockReset();
    accountListSpy.mockReset();
    accountSummaryLineSpy.mockReset();
    requestFiltersSpy.mockReset();
    recentRequestsTableSpy.mockReset();
    useAccountMutationsMock.mockReset();
    useDashboardMock.mockReset();
    useDashboardProjectionsMock.mockReset();
    useRequestLogsMock.mockReset();
    buildDashboardViewMock.mockReset();
    useDashboardPreferencesStore.setState({
      accountBurnrateEnabled: true,
      accountViewMode: "cards",
      requestLogViewMode: "simplified",
      accountTypeVisibility: { codex: true, cliproxy: true, openrouter: true, omniroute: true },
      accountListSort: null,
      initialized: true,
    });
  });

  function mockReadyDashboard(overviewOverride?: DashboardOverview) {
    const overview = overviewOverride ?? createDashboardOverview();

    useAccountMutationsMock.mockReturnValue({
      pauseMutation: { mutateAsync: vi.fn() },
      resumeMutation: { mutateAsync: vi.fn() },
      limitWarmupMutation: { mutateAsync: vi.fn() },
    } as unknown as ReturnType<typeof useAccountMutations>);
    useDashboardMock.mockReturnValue({
      data: overview,
      isFetching: false,
      error: null,
    } as ReturnType<typeof useDashboard>);
    useDashboardProjectionsMock.mockReturnValue({
      data: createDashboardProjections(),
      isFetching: false,
      error: null,
    } as ReturnType<typeof useDashboardProjections>);
    useRequestLogsMock.mockReturnValue({
      filters: {
        search: "",
        timeframe: "all",
        accountIds: [],
        apiKeyIds: [],
        modelOptions: [],
        statuses: [],
        limit: 25,
        offset: 0,
      },
      listFilters: {
        search: undefined,
        limit: 25,
        offset: 0,
        accountIds: [],
        apiKeyIds: [],
        statuses: [],
        modelOptions: [],
        since: undefined,
      },
      facetFilters: {
        since: undefined,
        accountIds: [],
        apiKeyIds: [],
        modelOptions: [],
      },
      logsQuery: {
        data: { requests: [], total: 0, hasMore: false },
        isFetching: false,
        error: null,
      },
      optionsQuery: {
        data: { accountIds: [], apiKeys: [], modelOptions: [], statuses: [] },
        error: null,
      },
      updateFilters: vi.fn(),
    } as unknown as ReturnType<typeof useRequestLogs>);
    buildDashboardViewMock.mockReturnValue({
      stats: [],
      weeklyCreditPace: null,
      primaryUsageItems: [],
      secondaryUsageItems: [],
      primaryTotal: 0,
      secondaryTotal: 0,
      safeLinePrimary: null,
      safeLineSecondary: null,
      requestLogs: [],
    } as ReturnType<typeof buildDashboardView>);

    return overview;
  }

  it("renders the account summary line in the Accounts header using overview accounts", () => {
    const overview = mockReadyDashboard();

    renderWithProviders(<DashboardPage />);

    const accountsHeader = screen.getByRole("heading", { name: "Accounts" }).parentElement;

    expect(accountsHeader).not.toBeNull();
    expect(within(accountsHeader as HTMLElement).getByTestId("account-summary-line")).toHaveTextContent(
      "Summary for 2 accounts",
    );
    expect(accountSummaryLineSpy).toHaveBeenCalledWith(overview.accounts);
  });

  it("defaults the Accounts section to card view", () => {
    const overview = mockReadyDashboard();

    renderWithProviders(<DashboardPage />);

    expect(screen.getByTestId("account-cards")).toHaveTextContent("Cards for 2 accounts");
    expect(screen.queryByTestId("account-list")).not.toBeInTheDocument();
    expect(accountCardsSpy).toHaveBeenCalledWith(overview.accounts);
    expect(screen.getByRole("radio", { name: "View accounts as cards" })).toHaveAttribute("aria-checked", "true");
  });

  it("switches the Accounts section to list view", async () => {
    const user = userEvent.setup();
    const overview = mockReadyDashboard();

    renderWithProviders(<DashboardPage />);

    await user.click(screen.getByRole("radio", { name: "View accounts as list" }));

    expect(screen.getByTestId("account-list")).toHaveTextContent("List for 2 accounts");
    expect(screen.queryByTestId("account-cards")).not.toBeInTheDocument();
    expect(accountListSpy).toHaveBeenCalledWith({ accounts: overview.accounts, sort: null });
    expect(useDashboardPreferencesStore.getState().accountViewMode).toBe("list");
  });

  it("hides accounts of a disabled type from the cards while keeping summary counts intact", async () => {
    const user = userEvent.setup();
    const codexAccount = createAccountSummary({ accountId: "acc_codex" });
    const openRouterAccount = createAccountSummary({
      accountId: "acc_openrouter",
      synthetic: true,
      kind: "sidecar",
      provider: "openrouter",
      displayName: "OpenRouter",
    });
    const overview = createDashboardOverview({
      accounts: [codexAccount, openRouterAccount],
    });
    mockReadyDashboard(overview);

    renderWithProviders(<DashboardPage />);

    expect(accountCardsSpy).toHaveBeenLastCalledWith([codexAccount, openRouterAccount]);

    await user.click(screen.getByRole("button", { name: "Hide OpenRouter accounts" }));

    expect(accountCardsSpy).toHaveBeenLastCalledWith([codexAccount]);
    expect(useDashboardPreferencesStore.getState().accountTypeVisibility.openrouter).toBe(false);
    // Summary line keeps using the full, unfiltered account list.
    expect(accountSummaryLineSpy).toHaveBeenLastCalledWith(overview.accounts);
  });

  it("passes persisted account list sort through and updates it from the list", async () => {
    const user = userEvent.setup();
    const overview = mockReadyDashboard();
    useDashboardPreferencesStore.setState({
      accountBurnrateEnabled: true,
      accountViewMode: "list",
      accountListSort: { key: "quota", direction: "asc" },
      initialized: true,
    });

    renderWithProviders(<DashboardPage />);

    expect(screen.getByTestId("account-list")).toHaveTextContent("List for 2 accounts");
    expect(accountListSpy).toHaveBeenCalledWith({
      accounts: overview.accounts,
      sort: { key: "quota", direction: "asc" },
    });

    await user.click(screen.getByTestId("account-list"));

    expect(useDashboardPreferencesStore.getState().accountListSort).toEqual({ key: "credits", direction: "desc" });
  });

  it("passes request-log view mode to filters and table and persists changes", async () => {
    const user = userEvent.setup();
    mockReadyDashboard();

    renderWithProviders(<DashboardPage />);

    expect(requestFiltersSpy).toHaveBeenLastCalledWith({ viewMode: "simplified" });
    expect(recentRequestsTableSpy).toHaveBeenLastCalledWith({ viewMode: "simplified" });

    await user.click(screen.getByTestId("request-filters"));

    expect(useDashboardPreferencesStore.getState().requestLogViewMode).toBe("expanded");
    expect(requestFiltersSpy).toHaveBeenLastCalledWith({ viewMode: "expanded" });
    expect(recentRequestsTableSpy).toHaveBeenLastCalledWith({ viewMode: "expanded" });
  });
});
