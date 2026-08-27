import { beforeEach, describe, expect, it, vi } from "vitest";

function installLocalStorageMock() {
  const storage = new Map<string, string>();
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => {
        storage.set(key, value);
      },
      removeItem: (key: string) => {
        storage.delete(key);
      },
      clear: () => {
        storage.clear();
      },
    },
  });
}

describe("useDashboardPreferencesStore", () => {
  beforeEach(() => {
    installLocalStorageMock();
    vi.resetModules();
  });

  it("defaults account view mode to cards", async () => {
    const { useDashboardPreferencesStore } = await import("@/hooks/use-dashboard-preferences");

    useDashboardPreferencesStore.getState().initializePreferences();

    expect(useDashboardPreferencesStore.getState().accountViewMode).toBe("cards");
    expect(useDashboardPreferencesStore.getState().accountListSort).toBeNull();
    expect(window.localStorage.getItem("codex-lb-dashboard-account-view-mode")).toBe("cards");
    expect(window.localStorage.getItem("codex-lb-dashboard-account-list-sort")).toBeNull();
  });

  it("persists account view mode updates", async () => {
    const { useDashboardPreferencesStore } = await import("@/hooks/use-dashboard-preferences");

    useDashboardPreferencesStore.getState().setAccountViewMode("list");

    expect(useDashboardPreferencesStore.getState().accountViewMode).toBe("list");
    expect(window.localStorage.getItem("codex-lb-dashboard-account-view-mode")).toBe("list");
  });

  it("defaults request-log view mode to simplified", async () => {
    const { useDashboardPreferencesStore } = await import("@/hooks/use-dashboard-preferences");

    useDashboardPreferencesStore.getState().initializePreferences();

    expect(useDashboardPreferencesStore.getState().requestLogViewMode).toBe("simplified");
    expect(window.localStorage.getItem("codex-lb-dashboard-request-log-view-mode")).toBe(
      "simplified",
    );
  });

  it("restores a stored expanded request-log view mode", async () => {
    window.localStorage.setItem("codex-lb-dashboard-request-log-view-mode", "expanded");
    const { useDashboardPreferencesStore } = await import("@/hooks/use-dashboard-preferences");

    useDashboardPreferencesStore.getState().initializePreferences();

    expect(useDashboardPreferencesStore.getState().requestLogViewMode).toBe("expanded");
  });

  it("replaces an invalid stored request-log view mode with simplified", async () => {
    window.localStorage.setItem("codex-lb-dashboard-request-log-view-mode", "invalid");
    const { useDashboardPreferencesStore } = await import("@/hooks/use-dashboard-preferences");

    useDashboardPreferencesStore.getState().initializePreferences();

    expect(useDashboardPreferencesStore.getState().requestLogViewMode).toBe("simplified");
    expect(window.localStorage.getItem("codex-lb-dashboard-request-log-view-mode")).toBe(
      "simplified",
    );
  });

  it("persists request-log view mode updates", async () => {
    const { useDashboardPreferencesStore } = await import("@/hooks/use-dashboard-preferences");

    useDashboardPreferencesStore.getState().setRequestLogViewMode("expanded");

    expect(useDashboardPreferencesStore.getState().requestLogViewMode).toBe("expanded");
    expect(window.localStorage.getItem("codex-lb-dashboard-request-log-view-mode")).toBe(
      "expanded",
    );
  });

  it("defaults all account types to visible", async () => {
    const { useDashboardPreferencesStore } = await import("@/hooks/use-dashboard-preferences");

    useDashboardPreferencesStore.getState().initializePreferences();

    expect(useDashboardPreferencesStore.getState().accountTypeVisibility).toEqual({
      codex: true,
      cliproxy: true,
      openrouter: true,
      omniroute: true,
      orcarouter: true,
    });
    expect(window.localStorage.getItem("codex-lb-dashboard-account-type-visibility")).toBe(
      JSON.stringify({
        codex: true,
        cliproxy: true,
        openrouter: true,
        orcarouter: true,
        omniroute: true,
      }),
    );
  });

  it("persists account type visibility updates for a single key", async () => {
    const { useDashboardPreferencesStore } = await import("@/hooks/use-dashboard-preferences");

    useDashboardPreferencesStore.getState().setAccountTypeVisibility("openrouter", false);

    expect(useDashboardPreferencesStore.getState().accountTypeVisibility).toEqual({
      codex: true,
      cliproxy: true,
      openrouter: false,
      omniroute: true,
      orcarouter: true,
    });
    expect(window.localStorage.getItem("codex-lb-dashboard-account-type-visibility")).toBe(
      JSON.stringify({
        codex: true,
        cliproxy: true,
        openrouter: false,
        orcarouter: true,
        omniroute: true,
      }),
    );
  });

  it("hydrates preferences persisted before the orcarouter key existed without resetting other toggles", async () => {
    window.localStorage.setItem(
      "codex-lb-dashboard-account-type-visibility",
      JSON.stringify({ codex: true, cliproxy: false, openrouter: false, omniroute: true }),
    );
    const { useDashboardPreferencesStore } = await import("@/hooks/use-dashboard-preferences");

    useDashboardPreferencesStore.getState().initializePreferences();

    expect(useDashboardPreferencesStore.getState().accountTypeVisibility).toEqual({
      codex: true,
      cliproxy: false,
      openrouter: false,
      omniroute: true,
      orcarouter: true,
    });
  });

  it("reads stored account type visibility on init and fills missing keys", async () => {
    window.localStorage.setItem(
      "codex-lb-dashboard-account-type-visibility",
      JSON.stringify({ codex: false }),
    );
    const { useDashboardPreferencesStore } = await import("@/hooks/use-dashboard-preferences");

    useDashboardPreferencesStore.getState().initializePreferences();

    expect(useDashboardPreferencesStore.getState().accountTypeVisibility).toEqual({
      codex: false,
      cliproxy: true,
      openrouter: true,
      omniroute: true,
      orcarouter: true,
    });
  });

  it("persists account list sort updates", async () => {
    const { useDashboardPreferencesStore } = await import("@/hooks/use-dashboard-preferences");

    useDashboardPreferencesStore.getState().setAccountListSort({ key: "quota", direction: "asc" });

    expect(useDashboardPreferencesStore.getState().accountListSort).toEqual({ key: "quota", direction: "asc" });
    expect(window.localStorage.getItem("codex-lb-dashboard-account-list-sort")).toBe(
      JSON.stringify({ key: "quota", direction: "asc" }),
    );
  });

  it("restores stored account list sort on initialization", async () => {
    window.localStorage.setItem(
      "codex-lb-dashboard-account-list-sort",
      JSON.stringify({ key: "credits", direction: "desc" }),
    );
    const { useDashboardPreferencesStore } = await import("@/hooks/use-dashboard-preferences");

    useDashboardPreferencesStore.getState().initializePreferences();

    expect(useDashboardPreferencesStore.getState().accountListSort).toEqual({ key: "credits", direction: "desc" });
    expect(window.localStorage.getItem("codex-lb-dashboard-account-list-sort")).toBe(
      JSON.stringify({ key: "credits", direction: "desc" }),
    );
  });

  it("ignores invalid stored account list sort", async () => {
    window.localStorage.setItem(
      "codex-lb-dashboard-account-list-sort",
      JSON.stringify({ key: "invalid", direction: "desc" }),
    );
    const { useDashboardPreferencesStore } = await import("@/hooks/use-dashboard-preferences");

    useDashboardPreferencesStore.getState().initializePreferences();

    expect(useDashboardPreferencesStore.getState().accountListSort).toBeNull();
    expect(window.localStorage.getItem("codex-lb-dashboard-account-list-sort")).toBeNull();
  });
});
