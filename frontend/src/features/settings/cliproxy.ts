import { formatSlug } from "@/utils/formatters";

export const CLIPROXY_QUOTA_WINDOWS = ["five_hour", "weekly"] as const;

export type CLIProxyQuotaWindow = (typeof CLIPROXY_QUOTA_WINDOWS)[number];

export function cliproxyProviderLabel(provider: string | null | undefined): string {
  if (provider === "claude") {
    return "Claude";
  }
  if (provider === "xai") {
    return "Grok";
  }
  if (!provider || provider === "unknown") {
    return "CLIProxyAPI";
  }
  return formatSlug(provider);
}

export function hasCLIProxyQuotaWindow(
  quotaWindows: readonly CLIProxyQuotaWindow[] | null | undefined,
  window: CLIProxyQuotaWindow,
): boolean {
  // Omitted by older backends ⇒ legacy Claude cards show both windows.
  // Explicit [] from new adapters ⇒ no live windows for that auth.
  if (quotaWindows == null) {
    return true;
  }
  return quotaWindows.includes(window);
}
