import { useLocation } from "react-router-dom";

import { useDashboardPreferencesStore } from "@/hooks/use-dashboard-preferences";

/** Default content width shared by the header, page body, and status bar. */
export const PAGE_MAX_WIDTH_CLASS = "max-w-[1500px]";
/** Split view drops the cap so wide (2K/4K) screens are used edge to edge. */
export const PAGE_FULL_WIDTH_CLASS = "max-w-none";

/**
 * Max-width class for the app shell. The header and status bar follow the
 * page body so their edges stay aligned when the dashboard goes full width.
 */
export function usePageMaxWidthClass(): string {
  const { pathname } = useLocation();
  const splitViewEnabled = useDashboardPreferencesStore((s) => s.splitViewEnabled);
  const isDashboard = pathname === "/dashboard" || pathname.startsWith("/dashboard/");
  return splitViewEnabled && isDashboard ? PAGE_FULL_WIDTH_CLASS : PAGE_MAX_WIDTH_CLASS;
}
