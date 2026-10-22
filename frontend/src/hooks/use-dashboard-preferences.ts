import { create } from "zustand";

import type { AccountListSort, AccountListSortKey } from "@/features/dashboard/components/account-list";
import { OMNIROUTE_ENABLED } from "@/lib/product-capabilities";

const ACCOUNT_BURNRATE_STORAGE_KEY = "codex-lb-account-burnrate-enabled";
const ACCOUNT_VIEW_MODE_STORAGE_KEY = "codex-lb-dashboard-account-view-mode";
const REQUEST_LOG_VIEW_MODE_STORAGE_KEY = "codex-lb-dashboard-request-log-view-mode";
const ACCOUNT_TYPE_VISIBILITY_STORAGE_KEY = "codex-lb-dashboard-account-type-visibility";
const ACCOUNT_LIST_SORT_STORAGE_KEY = "codex-lb-dashboard-account-list-sort";
<<<<<<< 22625a07e
const ACCOUNT_PANEL_HEIGHT_STORAGE_KEY = "codex-lb-dashboard-account-panel-height";
const SPLIT_VIEW_STORAGE_KEY = "codex-lb-dashboard-split-view";

/** Bounds for the operator-resized accounts panel, in px. */
export const ACCOUNT_PANEL_MIN_HEIGHT_PX = 160;
export const ACCOUNT_PANEL_MAX_HEIGHT_PX = 2400;
||||||| 84fde5a1e
=======
const DASHBOARD_REFRESH_STORAGE_KEY = "codex-lb-dashboard-refresh-seconds";

export type DashboardRefreshSeconds = 5 | 15 | 30 | 60;
>>>>>>> 72630bbfe

export type DashboardAccountViewMode = "cards" | "list";
export type DashboardRequestLogViewMode = "simplified" | "expanded";

export type AccountTypeKey =
  | "codex"
  | "cliproxy"
  | "openrouter"
  | "orcarouter"
  | "omniroute"
  | "opencode_go"
  | "openai_compat";
export type AccountTypeVisibility = Record<AccountTypeKey, boolean>;

/**
 * Account-type filters offered in the UI.
 *
 * `omniroute` stays in the `AccountTypeKey` union (stored preferences and the
 * visibility record still carry it) but is not offered as a filter while the
 * capability is disabled, since no OmniRoute account can be rendered.
 */
export const ACCOUNT_TYPE_KEYS: AccountTypeKey[] = [
  "codex",
  "cliproxy",
  "openrouter",
  "orcarouter",
  ...(OMNIROUTE_ENABLED ? (["omniroute"] as const) : []),
  "opencode_go",
  "openai_compat",
];

function defaultAccountTypeVisibility(): AccountTypeVisibility {
  return {
    codex: true,
    cliproxy: true,
    openrouter: true,
    orcarouter: true,
    omniroute: true,
    opencode_go: true,
    openai_compat: true,
  };
}

type DashboardPreferencesState = {
  accountBurnrateEnabled: boolean;
  accountViewMode: DashboardAccountViewMode;
  requestLogViewMode: DashboardRequestLogViewMode;
  accountTypeVisibility: AccountTypeVisibility;
  accountListSort: AccountListSort;
<<<<<<< 22625a07e
  /** Operator-resized accounts panel height in px; `null` = component default. */
  accountPanelHeight: number | null;
  /** Wide-screen layout: page spans the viewport and sections sit side by side. */
  splitViewEnabled: boolean;
||||||| 84fde5a1e
=======
  refreshSeconds: DashboardRefreshSeconds;
>>>>>>> 72630bbfe
  initialized: boolean;
  initializePreferences: () => void;
  setAccountBurnrateEnabled: (enabled: boolean) => void;
  setAccountViewMode: (mode: DashboardAccountViewMode) => void;
  setRequestLogViewMode: (mode: DashboardRequestLogViewMode) => void;
  setAccountTypeVisibility: (key: AccountTypeKey, enabled: boolean) => void;
  setAccountListSort: (sort: AccountListSort) => void;
<<<<<<< 22625a07e
  setAccountPanelHeight: (height: number | null) => void;
  setSplitViewEnabled: (enabled: boolean) => void;
||||||| 84fde5a1e
=======
  setRefreshSeconds: (seconds: DashboardRefreshSeconds) => void;
>>>>>>> 72630bbfe
};

const ACCOUNT_LIST_SORT_KEYS: AccountListSortKey[] = [
  "account",
  "status",
  "plan",
  "quota",
  "subscriptionCredits",
  "purchasedCredits",
  "warmup",
];

function isAccountListSortKey(value: unknown): value is AccountListSortKey {
  return typeof value === "string" && ACCOUNT_LIST_SORT_KEYS.includes(value as AccountListSortKey);
}

function readStoredAccountBurnrateEnabled(): boolean | null {
  if (typeof window === "undefined") {
    return null;
  }
  const stored = window.localStorage.getItem(ACCOUNT_BURNRATE_STORAGE_KEY);
  if (stored === "true") {
    return true;
  }
  if (stored === "false") {
    return false;
  }
  return null;
}

function readStoredAccountViewMode(): DashboardAccountViewMode | null {
  if (typeof window === "undefined") {
    return null;
  }
  const stored = window.localStorage.getItem(ACCOUNT_VIEW_MODE_STORAGE_KEY);
  return stored === "cards" || stored === "list" ? stored : null;
}

function readStoredRequestLogViewMode(): DashboardRequestLogViewMode | null {
  if (typeof window === "undefined") {
    return null;
  }
  const stored = window.localStorage.getItem(REQUEST_LOG_VIEW_MODE_STORAGE_KEY);
  return stored === "simplified" || stored === "expanded" ? stored : null;
}

function readStoredAccountListSort(): AccountListSort {
  if (typeof window === "undefined") {
    return null;
  }
  const stored = window.localStorage.getItem(ACCOUNT_LIST_SORT_STORAGE_KEY);
  if (!stored) {
    return null;
  }
  try {
    const parsed = JSON.parse(stored) as { key?: unknown; direction?: unknown };
    if (parsed.key === "credits") {
      parsed.key = "purchasedCredits";
    }
    if (
      isAccountListSortKey(parsed.key) &&
      (parsed.direction === "asc" || parsed.direction === "desc")
    ) {
      return { key: parsed.key, direction: parsed.direction };
    }
  } catch {
    return null;
  }
  return null;
}

<<<<<<< 22625a07e
function readStoredAccountPanelHeight(): number | null {
  if (typeof window === "undefined") {
    return null;
  }
  const stored = window.localStorage.getItem(ACCOUNT_PANEL_HEIGHT_STORAGE_KEY);
  if (stored === null) {
    return null;
  }
  const parsed = Number(stored);
  if (!Number.isFinite(parsed)) {
    return null;
  }
  return Math.min(ACCOUNT_PANEL_MAX_HEIGHT_PX, Math.max(ACCOUNT_PANEL_MIN_HEIGHT_PX, Math.round(parsed)));
}

function persistAccountPanelHeight(height: number | null): void {
  if (typeof window === "undefined") {
    return;
  }
  if (height === null) {
    window.localStorage.removeItem(ACCOUNT_PANEL_HEIGHT_STORAGE_KEY);
    return;
  }
  window.localStorage.setItem(ACCOUNT_PANEL_HEIGHT_STORAGE_KEY, String(height));
}

function readStoredSplitViewEnabled(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  return window.localStorage.getItem(SPLIT_VIEW_STORAGE_KEY) === "true";
}

function persistSplitViewEnabled(enabled: boolean): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(SPLIT_VIEW_STORAGE_KEY, String(enabled));
||||||| 84fde5a1e
=======
function readStoredRefreshSeconds(): DashboardRefreshSeconds | null {
  if (typeof window === "undefined") {
    return null;
  }
  const numeric = Number(window.localStorage.getItem(DASHBOARD_REFRESH_STORAGE_KEY));
  return numeric === 5 || numeric === 15 || numeric === 30 || numeric === 60
    ? numeric
    : null;
>>>>>>> 72630bbfe
}

function persistAccountBurnrateEnabled(enabled: boolean): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(ACCOUNT_BURNRATE_STORAGE_KEY, String(enabled));
}

function persistAccountViewMode(mode: DashboardAccountViewMode): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(ACCOUNT_VIEW_MODE_STORAGE_KEY, mode);
}

function persistRequestLogViewMode(mode: DashboardRequestLogViewMode): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(REQUEST_LOG_VIEW_MODE_STORAGE_KEY, mode);
}

function readStoredAccountTypeVisibility(): AccountTypeVisibility | null {
  if (typeof window === "undefined") {
    return null;
  }
  const stored = window.localStorage.getItem(ACCOUNT_TYPE_VISIBILITY_STORAGE_KEY);
  if (!stored) {
    return null;
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(stored);
  } catch {
    return null;
  }
  if (typeof parsed !== "object" || parsed === null) {
    return null;
  }
  const source = parsed as Record<string, unknown>;
  const visibility = defaultAccountTypeVisibility();
  for (const key of ACCOUNT_TYPE_KEYS) {
    if (typeof source[key] === "boolean") {
      visibility[key] = source[key] as boolean;
    }
  }
  return visibility;
}

function persistAccountTypeVisibility(visibility: AccountTypeVisibility): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(ACCOUNT_TYPE_VISIBILITY_STORAGE_KEY, JSON.stringify(visibility));
}

function persistAccountListSort(sort: AccountListSort): void {
  if (typeof window === "undefined") {
    return;
  }
  if (sort === null) {
    window.localStorage.removeItem(ACCOUNT_LIST_SORT_STORAGE_KEY);
    return;
  }
  window.localStorage.setItem(ACCOUNT_LIST_SORT_STORAGE_KEY, JSON.stringify(sort));
}

<<<<<<< 22625a07e
export const useDashboardPreferencesStore = create<DashboardPreferencesState>((set, get) => ({
||||||| 84fde5a1e
export const useDashboardPreferencesStore = create<DashboardPreferencesState>((set) => ({
=======
function persistRefreshSeconds(seconds: DashboardRefreshSeconds): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(DASHBOARD_REFRESH_STORAGE_KEY, String(seconds));
}

export const useDashboardPreferencesStore = create<DashboardPreferencesState>((set) => ({
>>>>>>> 72630bbfe
  accountBurnrateEnabled: true,
  accountViewMode: "cards",
  requestLogViewMode: "simplified",
  accountTypeVisibility: defaultAccountTypeVisibility(),
  accountListSort: null,
<<<<<<< 22625a07e
  accountPanelHeight: null,
  splitViewEnabled: false,
||||||| 84fde5a1e
=======
  refreshSeconds: 15,
>>>>>>> 72630bbfe
  initialized: false,
  initializePreferences: () => {
    const accountBurnrateEnabled = readStoredAccountBurnrateEnabled() ?? true;
    const accountViewMode = readStoredAccountViewMode() ?? "cards";
    const requestLogViewMode = readStoredRequestLogViewMode() ?? "simplified";
    const accountTypeVisibility = readStoredAccountTypeVisibility() ?? defaultAccountTypeVisibility();
    const accountListSort = readStoredAccountListSort();
<<<<<<< 22625a07e
    const accountPanelHeight = readStoredAccountPanelHeight();
    const splitViewEnabled = readStoredSplitViewEnabled();
||||||| 84fde5a1e
=======
    const refreshSeconds = readStoredRefreshSeconds() ?? 15;
>>>>>>> 72630bbfe
    persistAccountBurnrateEnabled(accountBurnrateEnabled);
    persistAccountViewMode(accountViewMode);
    persistRequestLogViewMode(requestLogViewMode);
    persistAccountTypeVisibility(accountTypeVisibility);
    persistAccountListSort(accountListSort);
<<<<<<< 22625a07e
    set({
      accountBurnrateEnabled,
      accountViewMode,
      requestLogViewMode,
      accountTypeVisibility,
      accountListSort,
      accountPanelHeight,
      splitViewEnabled,
      initialized: true,
    });
||||||| 84fde5a1e
    set({ accountBurnrateEnabled, accountViewMode, accountListSort, initialized: true });
=======
    persistRefreshSeconds(refreshSeconds);
    set({ accountBurnrateEnabled, accountViewMode, accountListSort, refreshSeconds, initialized: true });
>>>>>>> 72630bbfe
  },
  setAccountBurnrateEnabled: (enabled) => {
    persistAccountBurnrateEnabled(enabled);
    set({ accountBurnrateEnabled: enabled, initialized: true });
  },
  setAccountViewMode: (mode) => {
    persistAccountViewMode(mode);
    set({ accountViewMode: mode, initialized: true });
  },
  setRequestLogViewMode: (mode) => {
    persistRequestLogViewMode(mode);
    set({ requestLogViewMode: mode, initialized: true });
  },
  setAccountTypeVisibility: (key, enabled) => {
    const next = { ...get().accountTypeVisibility, [key]: enabled };
    persistAccountTypeVisibility(next);
    set({ accountTypeVisibility: next, initialized: true });
  },
  setAccountListSort: (sort) => {
    persistAccountListSort(sort);
    set({ accountListSort: sort, initialized: true });
  },
<<<<<<< 22625a07e
  setAccountPanelHeight: (height) => {
    const next =
      height === null
        ? null
        : Math.min(ACCOUNT_PANEL_MAX_HEIGHT_PX, Math.max(ACCOUNT_PANEL_MIN_HEIGHT_PX, Math.round(height)));
    persistAccountPanelHeight(next);
    set({ accountPanelHeight: next, initialized: true });
  },
  setSplitViewEnabled: (enabled) => {
    persistSplitViewEnabled(enabled);
    set({ splitViewEnabled: enabled, initialized: true });
||||||| 84fde5a1e
=======
  setRefreshSeconds: (seconds) => {
    persistRefreshSeconds(seconds);
    set({ refreshSeconds: seconds, initialized: true });
>>>>>>> 72630bbfe
  },
}));
