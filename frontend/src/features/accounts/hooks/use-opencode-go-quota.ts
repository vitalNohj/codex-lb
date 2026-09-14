import { useQuery } from "@tanstack/react-query";

import { getOpenCodeGoQuota } from "@/features/accounts/opencode-go-api";

export const OPENCODE_GO_QUOTA_QUERY_KEY = ["accounts", "opencode-go", "quota"] as const;

/**
 * Query for the OpenCode Go subscription quota snapshot.
 *
 * Deliberately carries no `refetchInterval`: the shared query client's
 * `staleTime` is the app's established freshness policy, and the server owns
 * upstream polling. Adding a page-level poll here would create a second,
 * uncoordinated usage cadence against an undocumented upstream route.
 *
 * A failed read is not an error banner on the Accounts page - the card renders
 * its own "unavailable" state - so failures stay local to this query.
 */
export function useOpenCodeGoQuota() {
  const quotaQuery = useQuery({
    queryKey: OPENCODE_GO_QUOTA_QUERY_KEY,
    queryFn: getOpenCodeGoQuota,
  });
  return { quotaQuery };
}
