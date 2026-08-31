/**
 * Centralized product-capability boundary for the dashboard.
 *
 * Mirrors `app/core/config/product_capabilities.py`, which is the authoritative
 * server-side boundary. The dashboard ships with the server it talks to, so a
 * constant keeps every surface consistent without an async capability fetch.
 *
 * A disabled capability must be invisible in the UI *and* unreachable on the
 * server. Hiding the UI alone is not sufficient - the server refuses the same
 * capability independently.
 *
 * To re-enable an integration, flip the constant here and remove the matching
 * entry from `DISABLED_PRODUCT_CAPABILITIES` on the server. Dormant components
 * and API helpers stay in the tree for exactly that reason.
 */

/** Whether the OmniRoute integration is enabled as a product. */
export const OMNIROUTE_ENABLED = false;

/** Account `provider` values whose capability is disabled at the product level. */
const DISABLED_ACCOUNT_PROVIDERS: ReadonlySet<string> = new Set(OMNIROUTE_ENABLED ? [] : ["omniroute"]);

/** Request-log `source` values whose capability is disabled at the product level. */
const DISABLED_REQUEST_LOG_SOURCES: ReadonlySet<string> = new Set(
  OMNIROUTE_ENABLED ? [] : ["omniroute_sidecar"],
);

/**
 * Whether an account belongs to a disabled capability and must not be rendered.
 *
 * The server already omits these accounts; this is the UI half of the boundary.
 */
export function isDisabledCapabilityAccount(account: { provider?: string | null }): boolean {
  return DISABLED_ACCOUNT_PROVIDERS.has(account.provider ?? "");
}

/**
 * Whether a request-log source belongs to a disabled capability.
 *
 * Historical request logs are never deleted or rewritten, so rows from a
 * disabled integration can still exist. They stay in the table, but their
 * provider branding is not rendered.
 */
export function isDisabledCapabilityRequestSource(source: string | null | undefined): boolean {
  return DISABLED_REQUEST_LOG_SOURCES.has(source ?? "");
}
