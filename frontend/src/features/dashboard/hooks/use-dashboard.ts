import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { getDashboardOverview, getDashboardProjections } from "@/features/dashboard/api";
import {
  DEFAULT_OVERVIEW_TIMEFRAME,
  type OverviewTimeframe,
} from "@/features/dashboard/schemas";

export function useDashboard(timeframe: OverviewTimeframe = DEFAULT_OVERVIEW_TIMEFRAME) {
  return useQuery({
    queryKey: ["dashboard", "overview", timeframe],
    queryFn: () => getDashboardOverview({ timeframe }),
    refetchOnWindowFocus: false,
    // Switching timeframe keeps the current overview on screen (with the
    // refresh spinner) instead of dropping back to the full-page skeleton.
    placeholderData: keepPreviousData,
  });
}

export function useDashboardProjections(enabled = true) {
  return useQuery({
    queryKey: ["dashboard", "projections"],
    queryFn: getDashboardProjections,
    enabled,
    refetchOnWindowFocus: false,
  });
}
