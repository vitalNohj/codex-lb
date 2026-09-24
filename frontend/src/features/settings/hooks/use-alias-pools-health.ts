import { useQuery } from "@tanstack/react-query";

import { getAliasPoolsHealth } from "@/features/settings/api";

export const ALIAS_POOLS_HEALTH_QUERY_KEY = ["settings", "alias-pools", "health"] as const;

export const ALIAS_POOLS_HEALTH_POLL_MS = 15_000;

/**
 * Per-target failover state for the alias pool editor.
 *
 * Polls while the caller is mounted and `enabled`; React Query stops the
 * interval on unmount so a collapsed Routing section issues no requests.
 * `gcTime: 0` drops the cached snapshot immediately so a re-opened section
 * never paints stale cooldowns before the first fresh poll lands.
 */
export function useAliasPoolsHealth(options: { enabled: boolean }) {
  return useQuery({
    queryKey: ALIAS_POOLS_HEALTH_QUERY_KEY,
    queryFn: getAliasPoolsHealth,
    enabled: options.enabled,
    refetchInterval: ALIAS_POOLS_HEALTH_POLL_MS,
    refetchIntervalInBackground: false,
    gcTime: 0,
  });
}
