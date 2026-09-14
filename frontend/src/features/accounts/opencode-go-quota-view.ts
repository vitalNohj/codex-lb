import type {
  OpenCodeGoQuotaModel,
  OpenCodeGoQuotaResponse,
  OpenCodeGoQuotaScope,
  OpenCodeGoQuotaWindow,
  OpenCodeGoQuotaWindowStatus,
} from "@/features/accounts/opencode-go-schemas";
import { ApiError } from "@/lib/api-client";

/**
 * Pure presentation logic for the OpenCode Go quota card.
 *
 * React- and i18n-free so every honesty rule the quota contract imposes is
 * directly testable:
 *
 * 1. Unknown is unknown. A null `percentUsed` never becomes 0% or 100%, and it
 *    never produces a bar fill.
 * 2. Only the used direction is ever shown. The contract publishes no remaining
 *    field precisely so a single-source directional inference is not laundered
 *    into a second confirmation, so nothing here derives one.
 * 3. Scope is reported, never assumed. `scope: "unknown"` is captioned as
 *    unknown; it is not relabelled "Account total" to make a tidier card.
 * 4. The model picker is gated on `modelBreakdownAvailable` plus real rows, so
 *    an aggregate value can never be duplicated under invented model headings.
 * 5. Stale data stays visible but is marked, with the reason and the time the
 *    values were actually obtained.
 */

export type QuotaWindowView = {
  key: string;
  /** OpenCode's own key, shown so our naming is auditable. */
  upstreamKey: string | null;
  /** True for the three contract-defined keys we have copy for. */
  known: boolean;
  /** 0-100 used, clamped. Null when genuinely unknown. */
  percentUsed: number | null;
  /**
   * Remaining headroom derived from `percentUsed` for **bar colour only**. It is
   * never displayed as a number, which is what keeps rule 2 intact.
   */
  headroomPercent: number | null;
  status: OpenCodeGoQuotaWindowStatus;
  resetsAt: string | null;
  /** Null means undeterminable, which is distinct from false. */
  limitReached: boolean | null;
};

export type QuotaModelView = {
  modelId: string;
  displayName: string | null;
  windows: QuotaWindowView[];
};

/** Why the card is showing a message instead of numbers. */
export type OpenCodeGoNoticeKind =
  | "disabled"
  | "not_configured"
  | "unauthorized"
  | "rate_limited"
  | "unavailable"
  | "malformed";

export type OpenCodeGoCardState =
  /**
   * The deployment has no Go quota endpoint, so the integration is not part of
   * this build. The card renders nothing rather than reporting a fault, which
   * also lets this page ship before the backend lane lands.
   */
  | { kind: "absent" }
  | { kind: "loading" }
  | {
      kind: "notice";
      notice: OpenCodeGoNoticeKind;
      /** Server-sanitized detail, safe to display. */
      message: string | null;
      /** True when the user can fix this in Go settings. */
      actionable: boolean;
      /**
       * True when this notice describes a *cached* response whose latest refetch
       * failed. A notice is a claim about the integration's current state, so a
       * stale one must say so - otherwise an old `disabled` or `unavailable`
       * answer is presented as though it were just confirmed.
       */
      stale: boolean;
    }
  | {
      kind: "quota";
      scope: OpenCodeGoQuotaScope;
      windows: QuotaWindowView[];
      models: QuotaModelView[];
      /** True only when the server reports a real model dimension. */
      hasModelDetail: boolean;
      stale: boolean;
      staleReason: string | null;
      /**
       * True when the values on screen came from a cached snapshot whose most
       * recent *client-side* refetch failed. Distinct from `stale`, which is the
       * server telling us its own upstream refresh failed - here our own request
       * to the dashboard failed, and the numbers are from an earlier success.
       */
      refreshFailed: boolean;
      /**
       * True when that failed refetch was a 404 on a route we had already used
       * successfully, i.e. the endpoint stopped answering rather than never
       * having existed. Narrower than `refreshFailed` and worth its own copy.
       */
      endpointUnavailable: boolean;
      message: string | null;
      /** When the displayed values were obtained upstream. */
      checkedAt: string | null;
      refreshedAt: string | null;
    };

export type OpenCodeGoCardInput = {
  data: OpenCodeGoQuotaResponse | undefined;
  isPending: boolean;
  error: unknown;
};

const KNOWN_WINDOW_KEYS = new Set(["five_hour", "weekly", "monthly"]);

function clampPercent(value: number): number {
  return Math.max(0, Math.min(100, value));
}

function isUsableNumber(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function toQuotaWindowView(window: OpenCodeGoQuotaWindow): QuotaWindowView {
  const percentUsed = isUsableNumber(window.percentUsed)
    ? clampPercent(window.percentUsed)
    : null;
  return {
    key: window.key,
    upstreamKey: window.upstreamKey?.trim() ? window.upstreamKey.trim() : null,
    known: KNOWN_WINDOW_KEYS.has(window.key),
    percentUsed,
    headroomPercent: percentUsed === null ? null : clampPercent(100 - percentUsed),
    status: window.status,
    resetsAt: window.resetsAt ?? null,
    limitReached: window.limitReached ?? null,
  };
}

function toQuotaModelView(model: OpenCodeGoQuotaModel): QuotaModelView {
  return {
    modelId: model.modelId,
    displayName: model.displayName?.trim() ? model.displayName.trim() : null,
    windows: model.windows.map(toQuotaWindowView),
  };
}

/**
 * Statuses that carry no windows map to a notice. Per the contract only `ok` and
 * `stale` ever carry data, so anything else means unknown - and unknown gets a
 * sentence, not an empty progress bar.
 */
function statusNotice(status: OpenCodeGoQuotaResponse["status"]): OpenCodeGoNoticeKind {
  switch (status) {
    case "disabled":
      return "disabled";
    case "not_configured":
      return "not_configured";
    case "unauthorized":
      return "unauthorized";
    case "rate_limited":
      return "rate_limited";
    default:
      return "unavailable";
  }
}

export function resolveOpenCodeGoCardState(
  input: OpenCodeGoCardInput,
): OpenCodeGoCardState {
  const { data, isPending, error } = input;

  // A failed request does NOT discard a snapshot we already read successfully.
  // Throwing away good data on a transient refetch or a remount would replace
  // real numbers with "unavailable", which is less true than what we know. The
  // values are kept and labelled as a failed refresh, never as current.
  const hasCachedData = data !== undefined;

  // A 404 means "this deployment has no Go quota route" only when we have never
  // seen the route work. Once a snapshot has been read successfully the route
  // demonstrably existed, so a later 404 is one failed request - a redeploy, a
  // rollback, a proxy hiccup - and it cannot retroactively prove the route never
  // existed. Treating it as absent would silently delete real numbers from the
  // page, which is the opposite of the no-data case this branch is for.
  if (error instanceof ApiError && error.status === 404 && !hasCachedData) {
    return { kind: "absent" };
  }

  if (error && !hasCachedData) {
    // A schema mismatch is an integration bug, not a provider outage, and an
    // operator needs to be able to tell those apart at a glance.
    if (error instanceof ApiError && error.code === "invalid_response_schema") {
      // No cached data reached this branch, so nothing here is stale - it is a
      // live failure with nothing behind it.
      return { kind: "notice", notice: "malformed", message: null, actionable: false, stale: false };
    }
    // Anything else is "we could not read our own snapshot". Deliberately not
    // reported as an upstream credential problem: per the contract a 401 here
    // means the dashboard session expired and says nothing about the Go key.
    return {
      kind: "notice",
      notice: "unavailable",
      message: error instanceof Error && error.message ? error.message : null,
      actionable: false,
      stale: false,
    };
  }

  // A malformed body or a vanished route with cached data present is still a
  // fault we must surface, but the known-good numbers stay visible behind it.
  const refreshFailed = Boolean(error) && hasCachedData;

  // A 404 against a route that previously worked is worth naming specifically:
  // "the endpoint is no longer answering" is actionable in a way that a generic
  // refresh failure is not.
  const endpointUnavailable =
    refreshFailed && error instanceof ApiError && error.status === 404;

  if (isPending || !data) {
    return { kind: "loading" };
  }

  const message = data.message?.trim() ? data.message.trim() : null;

  // Disabled/not-configured are deliberate configuration states, so they are
  // reported even when a stale snapshot from a previously configured key exists:
  // showing old numbers for a switched-off integration would be misleading.
  // They still carry `stale` when the latest refetch failed, because "Go is off"
  // read from a cached response is not the same claim as "Go is off right now".
  if (data.status === "disabled") {
    return { kind: "notice", notice: "disabled", message, actionable: true, stale: refreshFailed };
  }
  if (data.status === "not_configured") {
    return {
      kind: "notice",
      notice: "not_configured",
      message,
      actionable: true,
      stale: refreshFailed,
    };
  }

  const windows = data.windows.map(toQuotaWindowView);
  const models = data.models.map(toQuotaModelView);

  // Per-model detail requires the server's own flag *and* rows that actually
  // carry windows. A model list with no windows is not per-model quota data.
  const hasModelDetail =
    data.modelBreakdownAvailable && models.some((model) => model.windows.length > 0);

  // `ok`/`stale` with an empty window list is legal (every upstream entry was
  // malformed and therefore omitted). That is still unknown, so it reads as a
  // notice rather than as a card with nothing in it.
  if (windows.length === 0 && !hasModelDetail) {
    return {
      kind: "notice",
      notice: statusNotice(data.status),
      message: message ?? (data.staleReason?.trim() ? data.staleReason.trim() : null),
      actionable: data.status === "unauthorized",
      stale: refreshFailed || data.stale || data.status === "stale",
    };
  }

  return {
    kind: "quota",
    scope: data.scope,
    windows,
    models: hasModelDetail ? models.filter((model) => model.windows.length > 0) : [],
    hasModelDetail,
    // Either the server could not refresh upstream, or our own refetch failed.
    // Both mean the numbers on screen are not known to be current.
    stale: data.stale || data.status === "stale" || refreshFailed,
    staleReason: data.staleReason?.trim() ? data.staleReason.trim() : null,
    refreshFailed,
    endpointUnavailable,
    message,
    checkedAt: data.checkedAt ?? null,
    refreshedAt: data.refreshedAt ?? null,
  };
}

/**
 * Whether any reported window is at its limit, for the card's header badge.
 * Driven by `limitReached` (the contract's field of record) with the window
 * status as a secondary signal. A null `limitReached` is not treated as false.
 */
export function hasExhaustedWindow(state: OpenCodeGoCardState): boolean {
  if (state.kind !== "quota") {
    return false;
  }
  const atLimit = (window: QuotaWindowView) =>
    window.limitReached === true || window.status === "rate_limited";
  return (
    state.windows.some(atLimit) ||
    state.models.some((model) => model.windows.some(atLimit))
  );
}
