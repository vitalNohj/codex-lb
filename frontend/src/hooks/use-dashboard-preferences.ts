import { create } from "zustand";

const ACCOUNT_BURNRATE_STORAGE_KEY = "codex-lb-account-burnrate-enabled";
const ACCOUNT_VIEW_MODE_STORAGE_KEY = "codex-lb-dashboard-account-view-mode";
const ACCOUNT_TYPE_VISIBILITY_STORAGE_KEY = "codex-lb-dashboard-account-type-visibility";

export type DashboardAccountViewMode = "cards" | "list";

export type AccountTypeKey = "codex" | "cliproxy" | "openrouter" | "omniroute";
export type AccountTypeVisibility = Record<AccountTypeKey, boolean>;

export const ACCOUNT_TYPE_KEYS: AccountTypeKey[] = ["codex", "cliproxy", "openrouter", "omniroute"];

function defaultAccountTypeVisibility(): AccountTypeVisibility {
  return { codex: true, cliproxy: true, openrouter: true, omniroute: true };
}

type DashboardPreferencesState = {
  accountBurnrateEnabled: boolean;
  accountViewMode: DashboardAccountViewMode;
  accountTypeVisibility: AccountTypeVisibility;
  initialized: boolean;
  initializePreferences: () => void;
  setAccountBurnrateEnabled: (enabled: boolean) => void;
  setAccountViewMode: (mode: DashboardAccountViewMode) => void;
  setAccountTypeVisibility: (key: AccountTypeKey, enabled: boolean) => void;
};

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

export const useDashboardPreferencesStore = create<DashboardPreferencesState>((set, get) => ({
  accountBurnrateEnabled: true,
  accountViewMode: "cards",
  accountTypeVisibility: defaultAccountTypeVisibility(),
  initialized: false,
  initializePreferences: () => {
    const accountBurnrateEnabled = readStoredAccountBurnrateEnabled() ?? true;
    const accountViewMode = readStoredAccountViewMode() ?? "cards";
    const accountTypeVisibility = readStoredAccountTypeVisibility() ?? defaultAccountTypeVisibility();
    persistAccountBurnrateEnabled(accountBurnrateEnabled);
    persistAccountViewMode(accountViewMode);
    persistAccountTypeVisibility(accountTypeVisibility);
    set({ accountBurnrateEnabled, accountViewMode, accountTypeVisibility, initialized: true });
  },
  setAccountBurnrateEnabled: (enabled) => {
    persistAccountBurnrateEnabled(enabled);
    set({ accountBurnrateEnabled: enabled, initialized: true });
  },
  setAccountViewMode: (mode) => {
    persistAccountViewMode(mode);
    set({ accountViewMode: mode, initialized: true });
  },
  setAccountTypeVisibility: (key, enabled) => {
    const next = { ...get().accountTypeVisibility, [key]: enabled };
    persistAccountTypeVisibility(next);
    set({ accountTypeVisibility: next, initialized: true });
  },
}));
