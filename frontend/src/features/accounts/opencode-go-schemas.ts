import { z } from "zod";

/**
 * Dashboard-side types for the OpenCode Go subscription quota endpoint.
 *
 * **This file is a consumer, not an author.** It mirrors the quota lane's
 * published contract (`quota-contract.md`, owner `codexlb-opencode-go-quota-r1`)
 * field for field. When that contract changes, this file follows it; the
 * dashboard does not invent a competing shape.
 *
 * Two properties of that contract drive every display decision downstream, and
 * both exist to prevent the same class of bug - presenting an unknown as a fact:
 *
 * 1. **`status` and `scope` are independent axes.** `status` answers "do we have
 *    data, and how good is it". `scope` answers "what are the numbers about".
 *    Only `ok` and `stale` ever carry windows; every other status carries an
 *    empty list, which means *unknown* - not zero, and not full.
 *
 * 2. **`percentUsed` is the only percentage.** The contract deliberately omits a
 *    remaining field, because the used direction rests on a single-source
 *    inference and deriving a remaining value would dress that inference up as
 *    a second confirmation. The dashboard therefore labels what it shows as
 *    "used" and never prints a remaining percentage.
 *
 * Today the server reports `scope: "unknown"` and `modelBreakdownAvailable:
 * false` - upstream sends three unlabelled windows with no model dimension. The
 * card must say that honestly rather than captioning them "Account total", and
 * must not render a model picker over data that has no model dimension.
 */

/** Read path for the Go quota snapshot. Single point of reconciliation. */
export const OPENCODE_GO_QUOTA_PATH = "/api/opencode-go/quota";

/**
 * Where a user configures Go. The Settings lane owns that section; this is the
 * one place the Accounts card names its anchor, matching the existing
 * `/settings#<integration>-sidecar` convention.
 */
export const OPENCODE_GO_SETTINGS_ANCHOR = "/settings#opencode-go-sidecar";

/**
 * Snapshot status - "do we have data, and how good is it".
 *
 * `disabled` and `not_configured` are guaranteed by the contract to issue zero
 * upstream traffic. `rate_limited` here means the *usage endpoint itself* was
 * throttled; it is emphatically not a model quota signal, and the UI must not
 * present it as one.
 */
export const OpenCodeGoQuotaStatusSchema = z.enum([
  "disabled",
  "not_configured",
  "ok",
  "stale",
  "unauthorized",
  "rate_limited",
  "unavailable",
]);

/**
 * What the numbers are about. The server computes this from the payload it
 * actually received. `unknown` is the current real-world value and is not a
 * placeholder to be prettified into `account`.
 */
export const OpenCodeGoQuotaScopeSchema = z.enum(["unknown", "account", "per_model"]);

/** codex-lb's stable window names, ordered five_hour, weekly, monthly. */
export const OpenCodeGoQuotaWindowKeySchema = z.enum(["five_hour", "weekly", "monthly"]);

/**
 * Per-window state. `unknown` means upstream sent a status string we have no
 * evidence for; the window is still returned because its percent and reset may
 * be usable.
 */
export const OpenCodeGoQuotaWindowStatusSchema = z.enum(["ok", "rate_limited", "unknown"]);

export const OpenCodeGoQuotaWindowSchema = z.object({
  /** Stable codex-lb name. Unrecognized future keys are tolerated as strings. */
  key: OpenCodeGoQuotaWindowKeySchema.or(z.string()),
  /**
   * OpenCode's own key, preserved verbatim so the `rolling` -> `five_hour`
   * mapping stays auditable rather than silently asserted.
   */
  upstreamKey: z.string().nullable().optional(),
  status: OpenCodeGoQuotaWindowStatusSchema.default("unknown"),
  /**
   * 0-100 in the **used** direction, or null when upstream sent nothing
   * parseable. Null is unknown; it is never rendered as 0%.
   */
  percentUsed: z.number().nullable().optional(),
  /** Null when absent or unparseable upstream. Never synthesized. */
  resetsAt: z.iso.datetime({ offset: true }).nullable().optional(),
  /**
   * The field to trust for exhaustion. Null means undeterminable - which is
   * distinct from `false`.
   */
  limitReached: z.boolean().nullable().optional(),
});

export const OpenCodeGoQuotaModelSchema = z.object({
  modelId: z.string().min(1),
  displayName: z.string().nullable().optional(),
  windows: z.array(OpenCodeGoQuotaWindowSchema).default([]),
});

export const OpenCodeGoQuotaResponseSchema = z.object({
  status: OpenCodeGoQuotaStatusSchema,
  scope: OpenCodeGoQuotaScopeSchema.default("unknown"),
  /** Sanitized by the server; guaranteed never to carry a credential. */
  message: z.string().nullable().optional(),
  /** When `windows` were obtained upstream. Null when never fetched. */
  checkedAt: z.iso.datetime({ offset: true }).nullable().optional(),
  /** When this answer was produced. Null when never fetched. */
  refreshedAt: z.iso.datetime({ offset: true }).nullable().optional(),
  /** True iff status is `stale`. */
  stale: z.boolean().default(false),
  /** Sanitized reason the refresh failed. Present only when stale. */
  staleReason: z.string().nullable().optional(),
  /**
   * Gates the model picker entirely. False today; when upstream grows a model
   * dimension the control appears on its own, with no UI change needed.
   */
  modelBreakdownAvailable: z.boolean().default(false),
  /** Always empty while `modelBreakdownAvailable` is false. */
  models: z.array(OpenCodeGoQuotaModelSchema).default([]),
  /**
   * Ordered five_hour, weekly, monthly. A window whose upstream entry was
   * missing or malformed is **omitted**, not zero-filled, so consumers must
   * handle 0-3 entries.
   */
  windows: z.array(OpenCodeGoQuotaWindowSchema).default([]),
});

export type OpenCodeGoQuotaStatus = z.infer<typeof OpenCodeGoQuotaStatusSchema>;
export type OpenCodeGoQuotaScope = z.infer<typeof OpenCodeGoQuotaScopeSchema>;
export type OpenCodeGoQuotaWindowStatus = z.infer<
  typeof OpenCodeGoQuotaWindowStatusSchema
>;
export type OpenCodeGoQuotaWindow = z.infer<typeof OpenCodeGoQuotaWindowSchema>;
export type OpenCodeGoQuotaModel = z.infer<typeof OpenCodeGoQuotaModelSchema>;
export type OpenCodeGoQuotaResponse = z.infer<typeof OpenCodeGoQuotaResponseSchema>;
