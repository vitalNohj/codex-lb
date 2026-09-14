import { get } from "@/lib/api-client";

import {
  OPENCODE_GO_QUOTA_PATH,
  OpenCodeGoQuotaResponseSchema,
} from "@/features/accounts/opencode-go-schemas";

/**
 * Read the OpenCode Go subscription quota snapshot.
 *
 * Read-only by design: the dashboard never triggers an upstream quota call, it
 * only displays what the server already published. There is no second usage
 * backend here and no direct provider request from the browser.
 */
export function getOpenCodeGoQuota() {
  return get(OPENCODE_GO_QUOTA_PATH, OpenCodeGoQuotaResponseSchema);
}
