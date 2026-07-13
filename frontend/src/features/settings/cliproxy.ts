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
  return quotaWindows?.includes(window) ?? false;
}
