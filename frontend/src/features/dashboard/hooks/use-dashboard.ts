import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { getDashboardOverview, getDashboardProjections } from "@/features/dashboard/api";
import {
  DEFAULT_OVERVIEW_TIMEFRAME,
  type OverviewTimeframe,
} from "@/features/dashboard/schemas";
import { useDashboardPreferencesStore } from "@/hooks/use-dashboard-preferences";

export function useDashboard(timeframe: OverviewTimeframe = DEFAULT_OVERVIEW_TIMEFRAME) {
  const refreshSeconds = useDashboardPreferencesStore((state) => state.refreshSeconds);
  return useQuery({
    queryKey: ["dashboard", "overview", timeframe],
    queryFn: () => getDashboardOverview({ timeframe }),
<<<<<<< 22625a07e
    refetchOnWindowFocus: false,
    // Switching timeframe keeps the current overview on screen (with the
    // refresh spinner) instead of dropping back to the full-page skeleton.
    placeholderData: keepPreviousData,
||||||| 84fde5a1e
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
=======
    refetchInterval: refreshSeconds * 1_000,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
>>>>>>> 72630bbfe
  });
}

export function useDashboardProjections(enabled = true) {
  const refreshSeconds = useDashboardPreferencesStore((state) => state.refreshSeconds);
  return useQuery({
    queryKey: ["dashboard", "projections"],
    queryFn: getDashboardProjections,
    enabled,
<<<<<<< 22625a07e
    refetchOnWindowFocus: false,
||||||| 84fde5a1e
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
=======
    refetchInterval: refreshSeconds * 1_000,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
>>>>>>> 72630bbfe
  });
}
