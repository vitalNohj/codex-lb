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

  if (error) {
    if (error instanceof ApiError && error.status === 404) {
      return { kind: "absent" };
    }
    // A schema mismatch is an integration bug, not a provider outage, and an
    // operator needs to be able to tell those apart at a glance.
    if (error instanceof ApiError && error.code === "invalid_response_schema") {
      return { kind: "notice", notice: "malformed", message: null, actionable: false };
    }
    // Anything else is "we could not read our own snapshot". Deliberately not
    // reported as an upstream credential problem: per the contract a 401 here
    // means the dashboard session expired and says nothing about the Go key.
    return {
      kind: "notice",
      notice: "unavailable",
      message: error instanceof Error && error.message ? error.message : null,
      actionable: false,
    };
  }

  if (isPending || !data) {
    return { kind: "loading" };
  }

  const message = data.message?.trim() ? data.message.trim() : null;

  if (data.status === "disabled") {
    return { kind: "notice", notice: "disabled", message, actionable: true };
  }
  if (data.status === "not_configured") {
    return { kind: "notice", notice: "not_configured", message, actionable: true };
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
    };
  }

  return {
    kind: "quota",
    scope: data.scope,
    windows,
    models: hasModelDetail ? models.filter((model) => model.windows.length > 0) : [],
    hasModelDetail,
    stale: data.stale || data.status === "stale",
    staleReason: data.staleReason?.trim() ? data.staleReason.trim() : null,
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
