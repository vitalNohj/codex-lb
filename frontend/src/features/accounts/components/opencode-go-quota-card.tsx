import { useId, useMemo, useState } from "react";
import { Clock, Gauge, Settings as SettingsIcon } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useOpenCodeGoQuota } from "@/features/accounts/hooks/use-opencode-go-quota";
import { OPENCODE_GO_SETTINGS_ANCHOR } from "@/features/accounts/opencode-go-schemas";
import {
  hasExhaustedWindow,
  resolveOpenCodeGoCardState,
  type OpenCodeGoCardState,
  type OpenCodeGoNoticeKind,
  type QuotaWindowView,
} from "@/features/accounts/opencode-go-quota-view";
import { useDateDisplayFormatStore } from "@/hooks/use-date-format";
import { cn } from "@/lib/utils";
import { quotaBarColor, quotaBarTrack } from "@/utils/account-status";
import { formatDateTimeInline, formatQuotaResetLabel } from "@/utils/formatters";

const ALL_MODELS_VALUE = "__all__";

/**
 * Accounts-section card for the OpenCode Go subscription.
 *
 * Go is an external flat-rate subscription, so it gets a sibling card beside the
 * account list rather than a row pretending to be a ChatGPT OAuth account. The
 * backend's synthetic Go summary covers connection/health in the account detail
 * pane; this card covers exactly one thing that summary deliberately omits - the
 * five-hour and weekly usage windows - read from the quota lane's own endpoint.
 *
 * Everything it renders is bounded by what the quota contract actually
 * guarantees: used-direction percentages only, scope stated rather than assumed,
 * no per-model rows without a real model dimension, and no invented reset times,
 * remaining percentages or dollar limits.
 */
export function OpenCodeGoQuotaCard() {
  const { quotaQuery } = useOpenCodeGoQuota();
  const state = useMemo(
    () =>
      resolveOpenCodeGoCardState({
        data: quotaQuery.data,
        isPending: quotaQuery.isPending,
        error: quotaQuery.error,
      }),
    [quotaQuery.data, quotaQuery.error, quotaQuery.isPending],
  );

  // A deployment without the Go quota endpoint shows no card at all, so the
  // Accounts page is unchanged for everyone who has not configured Go.
  if (state.kind === "absent") {
    return null;
  }

  return (
    <section
      data-testid="opencode-go-quota-card"
      aria-labelledby="opencode-go-quota-card-title"
      className="animate-fade-in-up min-w-0 space-y-3 rounded-xl border bg-card p-4 sm:p-5"
    >
      <CardHeader state={state} />
      <CardBody state={state} />
    </section>
  );
}

function CardHeader({ state }: { state: OpenCodeGoCardState }) {
  const { t } = useTranslation();
  const exhausted = hasExhaustedWindow(state);
  return (
    <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
      <div className="flex min-w-0 items-start gap-2.5">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10">
          <Gauge className="h-4 w-4 text-primary" aria-hidden="true" />
        </div>
        <div className="min-w-0">
          <h2
            id="opencode-go-quota-card-title"
            className="flex flex-wrap items-center gap-x-2 gap-y-1 text-base font-semibold"
          >
            {t("accounts.opencodeGo.title")}
            <Badge variant="outline" className="font-normal">
              {t("accounts.opencodeGo.subscriptionBadge")}
            </Badge>
            {exhausted ? (
              <Badge
                variant="outline"
                className="border-red-500/20 bg-red-500/15 font-normal text-red-700 dark:text-red-400"
              >
                {t("accounts.opencodeGo.exhaustedBadge")}
              </Badge>
            ) : null}
          </h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {t("accounts.opencodeGo.subtitle")}
          </p>
        </div>
      </div>
      <Button asChild type="button" size="sm" variant="outline" className="h-8 shrink-0 gap-1.5 text-xs">
        <Link to={OPENCODE_GO_SETTINGS_ANCHOR}>
          <SettingsIcon className="h-3.5 w-3.5" aria-hidden="true" />
          {t("accounts.opencodeGo.openSettings")}
        </Link>
      </Button>
    </div>
  );
}

function CardBody({ state }: { state: OpenCodeGoCardState }) {
  if (state.kind === "absent") {
    return null;
  }
  if (state.kind === "loading") {
    return <QuotaLoading />;
  }
  if (state.kind === "notice") {
    return (
      <Notice
        notice={state.notice}
        message={state.message}
        actionable={state.actionable}
        stale={state.stale}
      />
    );
  }
  return <QuotaContent state={state} />;
}

function QuotaLoading() {
  const { t } = useTranslation();
  return (
    <div
      className="space-y-3 rounded-lg border bg-muted/30 p-4"
      data-testid="opencode-go-quota-loading"
      aria-busy="true"
    >
      <span className="sr-only">{t("accounts.opencodeGo.loading")}</span>
      <Skeleton className="h-3 w-28" />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {[0, 1].map((index) => (
          <div key={index} className="space-y-1.5">
            <div className="flex items-center justify-between gap-2">
              <Skeleton className="h-3 w-24" />
              <Skeleton className="h-3 w-10" />
            </div>
            <Skeleton className="h-1.5 w-full rounded-full" />
            <Skeleton className="h-3 w-20" />
          </div>
        ))}
      </div>
    </div>
  );
}

const NOTICE_TONE: Record<OpenCodeGoNoticeKind, string> = {
  disabled: "border-border bg-muted/30 text-muted-foreground",
  not_configured: "border-border bg-muted/30 text-muted-foreground",
  unauthorized: "border-amber-500/20 bg-amber-500/10 text-amber-700 dark:text-amber-300",
  rate_limited: "border-amber-500/20 bg-amber-500/10 text-amber-700 dark:text-amber-300",
  unavailable: "border-amber-500/20 bg-amber-500/10 text-amber-700 dark:text-amber-300",
  malformed: "border-destructive/20 bg-destructive/10 text-destructive",
};

function Notice({
  notice,
  message,
  actionable,
  stale = false,
}: {
  notice: OpenCodeGoNoticeKind;
  message: string | null;
  actionable: boolean;
  stale?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div
      data-testid="opencode-go-quota-notice"
      data-notice={notice}
      data-stale={stale ? "true" : undefined}
      className={cn("space-y-1.5 rounded-lg border p-4 text-xs", NOTICE_TONE[notice])}
    >
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm font-medium">
        {t(`accounts.opencodeGo.notices.${notice}.title`)}
        {/*
          A notice is a claim about the integration's current state, so a cached
          one must say it is cached. Without this, an old "Go is off" reads as
          though it had just been confirmed.
        */}
        {stale ? (
          <Badge
            data-testid="opencode-go-notice-stale-badge"
            variant="outline"
            className="border-amber-500/20 bg-amber-500/10 font-normal text-amber-700 dark:text-amber-300"
          >
            {t("accounts.opencodeGo.staleBadge")}
          </Badge>
        ) : null}
      </p>
      <p>{t(`accounts.opencodeGo.notices.${notice}.description`)}</p>
      {stale ? <p>{t("accounts.opencodeGo.noticeStale")}</p> : null}
      {message ? (
        <p className="break-words font-mono text-[11px] opacity-80">{message}</p>
      ) : null}
      {actionable ? (
        <p>
          <Link
            to={OPENCODE_GO_SETTINGS_ANCHOR}
            className="font-medium underline underline-offset-2"
          >
            {t("accounts.opencodeGo.openSettings")}
          </Link>
        </p>
      ) : null}
    </div>
  );
}

function QuotaContent({
  state,
}: {
  state: Extract<OpenCodeGoCardState, { kind: "quota" }>;
}) {
  const { t } = useTranslation();
  const [selectedModelId, setSelectedModelId] = useState<string>(ALL_MODELS_VALUE);
  const modelSelectId = useId();
  const dateDisplayFormat = useDateDisplayFormatStore((s) => s.dateDisplayFormat);

  const visibleModels = useMemo(() => {
    if (selectedModelId === ALL_MODELS_VALUE) {
      return state.models;
    }
    return state.models.filter((model) => model.modelId === selectedModelId);
  }, [selectedModelId, state.models]);

  // `checkedAt` is when the numbers on screen were obtained upstream, which is
  // the only timestamp that describes the data itself. `refreshedAt` describes
  // when the answer was produced and is a weaker fallback. When our own refetch
  // fails, both still describe the cached snapshot - which is the true age of
  // what is on screen, so the label stays correct without special-casing.
  const freshnessLabel =
    state.checkedAt !== null
      ? t("accounts.opencodeGo.measuredAt", {
          time: formatDateTimeInline(state.checkedAt, dateDisplayFormat),
        })
      : state.refreshedAt !== null
        ? t("accounts.opencodeGo.checkedAt", {
            time: formatDateTimeInline(state.refreshedAt, dateDisplayFormat),
          })
        : t("accounts.opencodeGo.freshnessUnknown");

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[11px] text-muted-foreground">
        <span data-testid="opencode-go-freshness">{freshnessLabel}</span>
        {state.stale ? (
          <Badge
            data-testid="opencode-go-stale-badge"
            variant="outline"
            className="border-amber-500/20 bg-amber-500/10 font-normal text-amber-700 dark:text-amber-300"
          >
            {t("accounts.opencodeGo.staleBadge")}
          </Badge>
        ) : null}
      </div>

      {state.stale ? (
        <div
          data-testid="opencode-go-degraded"
          className={cn("space-y-1 rounded-lg border p-3 text-xs", NOTICE_TONE.unavailable)}
        >
          <p className="font-medium">
            {state.endpointUnavailable
              ? t("accounts.opencodeGo.endpointUnavailableTitle")
              : state.refreshFailed
                ? t("accounts.opencodeGo.refreshFailedTitle")
                : t("accounts.opencodeGo.staleTitle")}
          </p>
          <p>{t("accounts.opencodeGo.showingLastKnown")}</p>
          {/*
            Only show the server's stale reason when the server is the one that
            failed. When our own refetch failed, that error belongs to a
            different request and must not be presented as upstream's.
          */}
          {!state.refreshFailed && (state.staleReason ?? state.message) ? (
            <p className="break-words font-mono text-[11px] opacity-80">
              {state.staleReason ?? state.message}
            </p>
          ) : null}
        </div>
      ) : null}

      {state.windows.length > 0 ? (
        <div
          data-testid="opencode-go-windows"
          className="min-w-0 space-y-3 rounded-lg border bg-muted/30 p-4"
        >
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              {t("accounts.opencodeGo.windowsTitle")}
            </h3>
            {/*
              Scope is stated from the server's own field. With scope "unknown"
              this says so plainly: OpenCode documents per-model dollar caps but
              its usage payload carries no model dimension, so neither "account
              total" nor "per model" is a claim we are entitled to make.
            */}
            <p
              data-testid="opencode-go-scope-note"
              className="mt-1 text-[11px] text-muted-foreground"
            >
              {t(`accounts.opencodeGo.scope.${state.scope}`)}
            </p>
          </div>
          {/*
            Subgrid keeps the label, bar and footer of every window on shared
            rows, so a wrapping label ("Weekly used" beside a wide "Unknown")
            cannot push its progress bar out of line with its neighbour's.
          */}
          <div
            className={cn(
              "grid gap-x-4 gap-y-4 [grid-template-rows:auto_auto_auto]",
              state.windows.length > 1 ? "grid-cols-1 sm:grid-cols-2" : "grid-cols-1",
            )}
          >
            {state.windows.map((window) => (
              <QuotaWindowRow key={window.key} window={window} />
            ))}
          </div>
        </div>
      ) : null}

      {state.hasModelDetail ? (
        <div
          data-testid="opencode-go-model-windows"
          className="min-w-0 space-y-3 rounded-lg border bg-muted/10 p-4"
        >
          <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
            <div className="min-w-0">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                {t("accounts.opencodeGo.modelWindowsTitle")}
              </h3>
              <p className="mt-1 text-[11px] text-muted-foreground">
                {t("accounts.opencodeGo.modelWindowsHelp")}
              </p>
            </div>
            {state.models.length > 1 ? (
              <label className="min-w-0 space-y-1 text-[11px] font-medium" htmlFor={modelSelectId}>
                {t("accounts.opencodeGo.modelFilterLabel")}
                <Select value={selectedModelId} onValueChange={setSelectedModelId}>
                  <SelectTrigger
                    id={modelSelectId}
                    size="sm"
                    className="h-8 w-full min-w-0 max-w-[16rem] text-xs sm:w-56"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="max-w-[min(20rem,90vw)]">
                    <SelectItem value={ALL_MODELS_VALUE}>
                      {t("accounts.opencodeGo.allModels", { count: state.models.length })}
                    </SelectItem>
                    {state.models.map((model) => (
                      <SelectItem
                        key={model.modelId}
                        value={model.modelId}
                        // Radix wraps children in its own ItemText span, which
                        // defaults to min-width:auto and so refuses to shrink.
                        // Without min-w-0 on that wrapper a long upstream model
                        // id is hard-clipped at the popover edge with no
                        // ellipsis to show the text was cut.
                        className="min-w-0 [&>span]:min-w-0"
                      >
                        <span
                          className="block min-w-0 flex-1 truncate"
                          title={model.displayName ?? model.modelId}
                        >
                          {model.displayName ?? model.modelId}
                        </span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </label>
            ) : null}
          </div>
          <div className="space-y-3">
            {visibleModels.map((model) => (
              <div
                key={model.modelId}
                data-testid="opencode-go-model-row"
                className="min-w-0 space-y-2.5 rounded-md border bg-background/60 px-3 py-2.5"
              >
                <div className="min-w-0">
                  <p
                    className="truncate text-xs font-medium"
                    title={model.displayName ?? model.modelId}
                  >
                    {model.displayName ?? model.modelId}
                  </p>
                  {model.displayName ? (
                    <p
                      className="truncate font-mono text-[11px] text-muted-foreground"
                      title={model.modelId}
                    >
                      {model.modelId}
                    </p>
                  ) : null}
                </div>
                <div
                  className={cn(
                    "grid gap-x-3 gap-y-3 [grid-template-rows:auto_auto_auto]",
                    model.windows.length > 1 ? "grid-cols-1 sm:grid-cols-2" : "grid-cols-1",
                  )}
                >
                  {model.windows.map((window) => (
                    <QuotaWindowRow key={window.key} window={window} compact />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <p data-testid="opencode-go-no-model-detail" className="text-[11px] text-muted-foreground">
          {t("accounts.opencodeGo.noModelDetail")}
        </p>
      )}

      <p className="text-[11px] text-muted-foreground">
        {t("accounts.opencodeGo.useBalanceNote")}
      </p>
    </div>
  );
}

function QuotaWindowRow({
  window,
  compact = false,
}: {
  window: QuotaWindowView;
  compact?: boolean;
}) {
  const { t } = useTranslation();
  // Known keys get real copy; an unrecognized future key falls back to the
  // upstream key rather than being hidden or guessed at.
  const windowName = window.known
    ? t(`accounts.opencodeGo.window.names.${window.key}`)
    : (window.upstreamKey ?? window.key);
  // "used" is always part of the label. A reader must never have to guess
  // whether 42% is consumption or headroom.
  const label = t("accounts.opencodeGo.window.usedLabel", { label: windowName });

  const known = window.percentUsed !== null && window.headroomPercent !== null;
  const valueText = known
    ? t("accounts.opencodeGo.window.percentValue", {
        percent: Math.round(window.percentUsed as number),
      })
    : t("accounts.opencodeGo.window.unknownValue");

  return (
    <div
      className="row-span-3 grid min-w-0 gap-1.5 [grid-template-rows:subgrid]"
      data-testid="opencode-go-window"
      data-window-key={window.key}
    >
      <div className="flex items-start justify-between gap-2 text-xs">
        <span className="min-w-0 font-medium">{label}</span>
        <span
          data-testid="opencode-go-window-value"
          className={cn(
            "shrink-0 tabular-nums font-medium",
            !known
              ? "text-muted-foreground"
              : (window.headroomPercent as number) >= 70
                ? "text-emerald-600 dark:text-emerald-400"
                : (window.headroomPercent as number) >= 30
                  ? "text-amber-600 dark:text-amber-400"
                  : "text-red-600 dark:text-red-400",
          )}
        >
          {valueText}
        </span>
      </div>
      {known ? (
        <>
          <progress
            className="sr-only"
            aria-label={t("accounts.opencodeGo.window.progressAria", {
              label,
              percent: Math.round(window.percentUsed as number),
            })}
            value={Math.round(window.percentUsed as number)}
            max={100}
          />
          <div
            aria-hidden="true"
            className={cn(
              "w-full overflow-hidden rounded-full",
              compact ? "h-1" : "h-1.5",
              quotaBarTrack(window.headroomPercent as number),
            )}
          >
            <div
              data-testid="opencode-go-window-fill"
              className={cn(
                "h-full rounded-full transition-all duration-500 ease-out",
                quotaBarColor(window.headroomPercent as number),
              )}
              style={{ width: `${window.percentUsed}%` }}
            />
          </div>
        </>
      ) : (
        // No fill at all when the value is unknown: an empty bar reads as 0% and
        // a full bar as 100%, and neither is something we know.
        <div
          aria-hidden="true"
          data-testid="opencode-go-window-unknown-track"
          className={cn(
            "w-full rounded-full border border-dashed border-muted-foreground/30 bg-muted/40",
            compact ? "h-1" : "h-1.5",
          )}
        />
      )}
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted-foreground">
        {window.resetsAt !== null ? (
          <span className="flex items-center gap-1.5">
            <Clock className="h-3 w-3 shrink-0" aria-hidden="true" />
            {t("accounts.opencodeGo.window.resetsAt", {
              label: formatQuotaResetLabel(window.resetsAt),
            })}
          </span>
        ) : (
          <span>{t("accounts.opencodeGo.window.resetUnknown")}</span>
        )}
        {window.limitReached === true ? (
          <span className="font-medium text-red-600 dark:text-red-400">
            {t("accounts.opencodeGo.window.exhausted")}
          </span>
        ) : window.status === "rate_limited" ? (
          <span className="font-medium text-amber-600 dark:text-amber-400">
            {t("accounts.opencodeGo.window.rateLimited")}
          </span>
        ) : null}
      </div>
    </div>
  );
}
