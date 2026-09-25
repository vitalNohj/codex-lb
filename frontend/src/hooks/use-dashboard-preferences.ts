import { create } from "zustand";

import type { AccountListSort, AccountListSortKey } from "@/features/dashboard/components/account-list";
import { OMNIROUTE_ENABLED } from "@/lib/product-capabilities";

const ACCOUNT_BURNRATE_STORAGE_KEY = "codex-lb-account-burnrate-enabled";
const ACCOUNT_VIEW_MODE_STORAGE_KEY = "codex-lb-dashboard-account-view-mode";
const REQUEST_LOG_VIEW_MODE_STORAGE_KEY = "codex-lb-dashboard-request-log-view-mode";
const ACCOUNT_TYPE_VISIBILITY_STORAGE_KEY = "codex-lb-dashboard-account-type-visibility";
const ACCOUNT_LIST_SORT_STORAGE_KEY = "codex-lb-dashboard-account-list-sort";
const ACCOUNT_PANEL_HEIGHT_STORAGE_KEY = "codex-lb-dashboard-account-panel-height";

/** Bounds for the operator-resized accounts panel, in px. */
export const ACCOUNT_PANEL_MIN_HEIGHT_PX = 160;
export const ACCOUNT_PANEL_MAX_HEIGHT_PX = 2400;

export type DashboardAccountViewMode = "cards" | "list";
export type DashboardRequestLogViewMode = "simplified" | "expanded";

export type AccountTypeKey =
  | "codex"
  | "cliproxy"
  | "openrouter"
  | "nvidia"
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
  "nvidia",
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
    nvidia: true,
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
  /** Operator-resized accounts panel height in px; `null` = component default. */
  accountPanelHeight: number | null;
  initialized: boolean;
  initializePreferences: () => void;
  setAccountBurnrateEnabled: (enabled: boolean) => void;
  setAccountViewMode: (mode: DashboardAccountViewMode) => void;
  setRequestLogViewMode: (mode: DashboardRequestLogViewMode) => void;
  setAccountTypeVisibility: (key: AccountTypeKey, enabled: boolean) => void;
  setAccountListSort: (sort: AccountListSort) => void;
  setAccountPanelHeight: (height: number | null) => void;
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

export const useDashboardPreferencesStore = create<DashboardPreferencesState>((set, get) => ({
  accountBurnrateEnabled: true,
  accountViewMode: "cards",
  requestLogViewMode: "simplified",
  accountTypeVisibility: defaultAccountTypeVisibility(),
  accountListSort: null,
  accountPanelHeight: null,
  initialized: false,
  initializePreferences: () => {
    const accountBurnrateEnabled = readStoredAccountBurnrateEnabled() ?? true;
    const accountViewMode = readStoredAccountViewMode() ?? "cards";
    const requestLogViewMode = readStoredRequestLogViewMode() ?? "simplified";
    const accountTypeVisibility = readStoredAccountTypeVisibility() ?? defaultAccountTypeVisibility();
    const accountListSort = readStoredAccountListSort();
    const accountPanelHeight = readStoredAccountPanelHeight();
    persistAccountBurnrateEnabled(accountBurnrateEnabled);
    persistAccountViewMode(accountViewMode);
    persistRequestLogViewMode(requestLogViewMode);
    persistAccountTypeVisibility(accountTypeVisibility);
    persistAccountListSort(accountListSort);
    set({
      accountBurnrateEnabled,
      accountViewMode,
      requestLogViewMode,
      accountTypeVisibility,
      accountListSort,
      accountPanelHeight,
      initialized: true,
    });
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
  setAccountPanelHeight: (height) => {
    const next =
      height === null
        ? null
        : Math.min(ACCOUNT_PANEL_MAX_HEIGHT_PX, Math.max(ACCOUNT_PANEL_MIN_HEIGHT_PX, Math.round(height)));
    persistAccountPanelHeight(next);
    set({ accountPanelHeight: next, initialized: true });
  },
}));
