import { Clock, ExternalLink, Pause, Play, RotateCcw, Zap } from "lucide-react";
import { useTranslation } from "react-i18next";

import { usePrivacyStore } from "@/hooks/use-privacy";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { SidecarEffortSelect } from "@/features/accounts/components/sidecar-effort-select";
import { useClaudeSidecarAccountPause } from "@/features/settings/hooks/use-settings";
import { StatusBadge } from "@/components/status-badge";
import { cn } from "@/lib/utils";
import type { AccountSummary } from "@/features/dashboard/schemas";
import type { SidecarAuthAccount } from "@/features/accounts/schemas";
import { formatCompactAccountId } from "@/utils/account-identifiers";
import {
  normalizeStatus,
  quotaBarColor,
  quotaBarTrack,
} from "@/utils/account-status";
import {
  formatCurrency,
  formatDateTimeInline,
  formatPercentNullable,
  formatQuotaResetLabel,
  formatSingleUnitRemaining,
  formatSlug,
} from "@/utils/formatters";

export type AccountAction = "details" | "pause" | "resume" | "reauth" | "warmup-toggle" | "reset-credit";

export type AccountCardProps = {
  account: AccountSummary;
  showAccountId?: boolean;
  readOnly?: boolean;
  onAction?: (account: AccountSummary, action: AccountAction) => void;
};

function formatWarmupWindow(window: string): string {
  return window === "primary" || window === "primary_idle" ? "5h" : "weekly";
}

function QuotaBar({
  label,
  percent,
  resetLabel,
}: {
  label: string;
  percent: number | null;
  resetLabel: string;
}) {
  const clamped = percent === null ? 0 : Math.max(0, Math.min(100, percent));
  const hasPercent = percent !== null;
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span
          className={cn(
            "tabular-nums font-medium",
            !hasPercent
              ? "text-muted-foreground"
              : clamped >= 70
                ? "text-emerald-600 dark:text-emerald-400"
                : clamped >= 30
                  ? "text-amber-600 dark:text-amber-400"
                  : "text-red-600 dark:text-red-400",
          )}
        >
          {formatPercentNullable(percent)}
        </span>
      </div>
      <div className={cn("h-1.5 w-full overflow-hidden rounded-full", quotaBarTrack(clamped))}>
        <div
          className={cn("h-full rounded-full transition-all duration-500 ease-out", quotaBarColor(clamped))}
          style={{ width: `${clamped}%` }}
        />
      </div>
      <div className="flex items-center gap-1 text-[11px] text-muted-foreground">
        <Clock className="h-3 w-3 shrink-0" />
        <span>{resetLabel}</span>
      </div>
    </div>
  );
}

export function AccountCard({ account, showAccountId = false, readOnly = false, onAction }: AccountCardProps) {
  if (account.synthetic) {
    return <SyntheticAccountCard account={account} onAction={onAction} />;
  }
  return <NativeAccountCard account={account} showAccountId={showAccountId} readOnly={readOnly} onAction={onAction} />;
}

function NativeAccountCard({ account, showAccountId = false, readOnly = false, onAction }: AccountCardProps) {
  const { t } = useTranslation();
  const blurred = usePrivacyStore((s) => s.blurred);
  const status = normalizeStatus(account.status);
  const primaryRemaining = account.usage?.primaryRemainingPercent ?? null;
  const secondaryRemaining = account.usage?.secondaryRemainingPercent ?? null;
  const monthlyRemaining = account.usage?.monthlyRemainingPercent ?? null;
  const weeklyOnly = account.windowMinutesPrimary == null && account.windowMinutesSecondary != null;
  const monthlyOnly =
    account.windowMinutesMonthly != null &&
    account.windowMinutesPrimary == null &&
    account.windowMinutesSecondary == null;
  const displayCredits = account.creditsBalance ?? (
    monthlyOnly
      ? account.remainingCreditsMonthly
      : weeklyOnly
        ? account.remainingCreditsSecondary
        : (account.remainingCreditsSecondary ?? account.remainingCreditsPrimary)
  );
  const creditsLabel = account.creditsUnlimited ? t("common.states.unlimited") : (
    displayCredits === null || displayCredits === undefined ? "-" : displayCredits.toFixed(2)
  );

  const primaryReset = formatQuotaResetLabel(account.resetAtPrimary ?? null);
  const secondaryReset = formatQuotaResetLabel(account.resetAtSecondary ?? null);
  const monthlyReset = formatQuotaResetLabel(account.resetAtMonthly ?? null);

  const title = account.displayName || account.email;
  const compactId = formatCompactAccountId(account.accountId);
  const planLabel = formatSlug(account.planType);
  const emailSubtitle =
    account.displayName && account.displayName !== account.email
      ? account.email
      : null;
  const idSuffix = showAccountId ? ` | ID ${compactId}` : "";
  const warmupStatus = account.limitWarmupEnabled ? t("accounts.listItem.warmupOn") : t("accounts.listItem.warmupOff");
  const warmupToggleLabel = account.limitWarmupEnabled
    ? t("dashboard.accounts.disableWarmupFor", { account: title })
    : t("dashboard.accounts.enableWarmupFor", { account: title });
  const warmupDetail = account.limitWarmup
    ? `${formatSlug(account.limitWarmup.status)} | ${formatWarmupWindow(account.limitWarmup.window)} | ${formatSlug(account.limitWarmup.model)} | ${formatDateTimeInline(account.limitWarmup.completedAt ?? account.limitWarmup.attemptedAt)}`
    : t("accounts.listItem.noAttempts");
  const availableResetCredits = account.availableResetCredits ?? 0;
  const hasResetCredits = availableResetCredits > 0;
  const resetCreditDisabled =
    readOnly || status === "paused" || status === "reauth" || status === "deactivated";
  const resetCountdown = account.resetCreditNearestExpiresAt
    ? formatSingleUnitRemaining(account.resetCreditNearestExpiresAt)
    : null;
  const resetButtonTitle = resetCreditDisabled
    ? status === "paused"
      ? t("dashboard.accounts.resetCreditTitles.resumeRequired")
      : status === "reauth" || status === "deactivated"
        ? t("dashboard.accounts.resetCreditTitles.reauthRequired")
        : t("dashboard.accounts.resetCreditTitles.unavailable")
    : resetCountdown
      ? t("dashboard.accounts.resetCreditTitles.withCountdown", { count: availableResetCredits, countdown: resetCountdown.label })
      : t("dashboard.accounts.resetWithCount", { count: availableResetCredits });

  return (
    <div className="card-hover rounded-xl border bg-card p-4">
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold leading-tight">
            {blurred
              ? <span className="privacy-blur">{title}</span>
              : title}
          </p>
          <p className="mt-0.5 truncate text-xs text-muted-foreground">
            {planLabel}
            {!emailSubtitle ? idSuffix : ""}
          </p>
          {emailSubtitle ? (
            <p
              className="mt-0.5 truncate text-xs text-muted-foreground"
              title={showAccountId ? t("accounts.detail.accountIdTitle", { accountId: account.accountId }) : undefined}
            >
              <span className={blurred ? "privacy-blur" : undefined}>{emailSubtitle}</span>{showAccountId ? ` | ID ${compactId}` : ""}
            </p>
          ) : null}
        </div>
        <StatusBadge status={status} />
      </div>

      {/* Quota bars */}
      <div className={cn("mt-3.5 grid gap-3", weeklyOnly || monthlyOnly ? "grid-cols-1" : "grid-cols-2")}>
        {monthlyOnly ? (
          <QuotaBar label={t("common.time.monthly")} percent={monthlyRemaining} resetLabel={monthlyReset} />
        ) : (
          <>
            {!weeklyOnly && <QuotaBar label="5h" percent={primaryRemaining} resetLabel={primaryReset} />}
            <QuotaBar label={t("common.time.weekly")} percent={secondaryRemaining} resetLabel={secondaryReset} />
          </>
        )}
      </div>

      <div className="mt-3 flex items-center justify-between gap-2 rounded-lg bg-muted/40 px-2.5 py-2 text-xs">
        <div className="min-w-0">
          <p className="font-medium">{warmupStatus}</p>
          <p className="truncate text-[11px] text-muted-foreground">{warmupDetail}</p>
        </div>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className={cn(
            "h-7 gap-1.5 rounded-lg text-xs",
            account.limitWarmupEnabled
              ? "text-primary hover:bg-primary/10 hover:text-primary"
              : "text-muted-foreground hover:text-foreground",
          )}
          aria-label={warmupToggleLabel}
          disabled={readOnly}
          onClick={() => onAction?.(account, "warmup-toggle")}
        >
          <Zap className="h-3 w-3" aria-hidden="true" />
          {account.limitWarmupEnabled ? t("common.states.on") : t("common.states.off")}
        </Button>
      </div>

      <div className="mt-3 text-xs text-muted-foreground">
        {t("components.donut.credits")}:{" "}
        <span className="font-medium tabular-nums text-foreground">
          {creditsLabel}
        </span>
      </div>

      {/* Actions */}
      <div className="mt-3 flex items-center gap-1.5 border-t pt-3">
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className="h-7 gap-1.5 rounded-lg text-xs text-muted-foreground hover:text-foreground"
          onClick={() => onAction?.(account, "details")}
        >
          <ExternalLink className="h-3 w-3" />
          {t("common.actions.details")}
        </Button>
        {hasResetCredits ? (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="relative h-7 gap-1.5 rounded-lg pr-8 text-xs text-muted-foreground hover:text-foreground"
            title={resetButtonTitle}
            disabled={resetCreditDisabled}
            onClick={() => onAction?.(account, "reset-credit")}
          >
            <RotateCcw className="h-3 w-3" />
            {t("dashboard.accounts.resetWithCount", { count: availableResetCredits })}
            {resetCountdown ? (
              <span
                aria-hidden="true"
                className={cn(
                  "pointer-events-none absolute -top-1 right-1 text-[10px] tabular-nums",
                  resetCountdown.expiringSoon ? "text-destructive" : "text-muted-foreground",
                )}
              >
                {resetCountdown.label}
              </span>
            ) : null}
          </Button>
        ) : null}
        {status === "paused" ? (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="h-7 gap-1.5 rounded-lg text-xs text-emerald-600 hover:bg-emerald-500/10 hover:text-emerald-700 dark:text-emerald-400 dark:hover:text-emerald-300"
            disabled={readOnly}
            onClick={() => onAction?.(account, "resume")}
          >
            <Play className="h-3 w-3" />
            {t("common.actions.resume")}
          </Button>
        ) : status === "reauth" || status === "deactivated" ? null : (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="h-7 gap-1.5 rounded-lg text-xs text-amber-600 hover:bg-amber-500/10 hover:text-amber-700 dark:text-amber-400 dark:hover:text-amber-300"
            onClick={() => onAction?.(account, "pause")}
          >
            <Pause className="h-3 w-3" />
            Pause
          </Button>
        )}
        {(status === "reauth" || status === "deactivated") && (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="h-7 gap-1.5 rounded-lg text-xs text-amber-600 hover:bg-amber-500/10 hover:text-amber-700 dark:text-amber-400 dark:hover:text-amber-300"
            disabled={readOnly}
            onClick={() => onAction?.(account, "reauth")}
          >
            <RotateCcw className="h-3 w-3" />
            {t("common.actions.reauthenticateShort")}
          </Button>
        )}
      </div>
    </div>
  );
}

export function ClaudeAuthCard({
  account,
  auth,
  onAction,
}: {
  account: AccountSummary;
  auth: SidecarAuthAccount;
  onAction?: (account: AccountSummary, action: AccountAction) => void;
}) {
  const blurred = usePrivacyStore((s) => s.blurred);
  const pauseMutation = useClaudeSidecarAccountPause();
  const title = auth.email ?? auth.name;
  const status = auth.paused ? "paused" : normalizeStatus(auth.status ?? account.status);
  const planLabel = auth.planType ? formatSlug(auth.planType) : "Claude";
  const providerLabel = auth.provider === "claude"
    ? "Claude"
    : auth.provider
      ? formatSlug(auth.provider)
      : "CLIProxyAPI";

  return (
    <div className="card-hover rounded-xl border bg-card p-4">
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold leading-tight">
            {blurred ? <span className="privacy-blur">{title}</span> : title}
          </p>
          <p className="mt-0.5 truncate text-xs text-muted-foreground">
            {planLabel} | {providerLabel}
          </p>
        </div>
        <StatusBadge status={status} />
      </div>

      {/* Quota bars */}
      <div className="mt-3.5 grid grid-cols-2 gap-3">
        <QuotaBar
          label="5h"
          percent={auth.primaryRemainingPercent ?? null}
          resetLabel={formatQuotaResetLabel(auth.resetAtPrimary ?? null)}
        />
        <QuotaBar
          label="Weekly"
          percent={auth.secondaryRemainingPercent ?? null}
          resetLabel={formatQuotaResetLabel(auth.resetAtSecondary ?? null)}
        />
      </div>

      {/* Reasoning effort override occupies the warm-up slot */}
      <div className="mt-3">
        <SidecarEffortSelect provider={account.provider} />
      </div>

      {/* Actions */}
      <div className="mt-3 flex items-center gap-1.5 border-t pt-3">
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className="h-7 gap-1.5 rounded-lg text-xs text-muted-foreground hover:text-foreground"
          onClick={() => onAction?.(account, "details")}
        >
          <ExternalLink className="h-3 w-3" />
          Details
        </Button>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className={cn(
            "h-7 gap-1.5 rounded-lg text-xs",
            auth.paused
              ? "text-emerald-600 hover:bg-emerald-500/10 hover:text-emerald-700 dark:text-emerald-400 dark:hover:text-emerald-300"
              : "text-amber-600 hover:bg-amber-500/10 hover:text-amber-700 dark:text-amber-400 dark:hover:text-amber-300",
          )}
          disabled={pauseMutation.isPending}
          aria-label={`${auth.paused ? "Resume" : "Pause"} ${title}`}
          onClick={() => pauseMutation.mutate({ name: auth.name, paused: !auth.paused })}
        >
          {auth.paused ? <Play className="h-3 w-3" /> : <Pause className="h-3 w-3" />}
          {auth.paused ? "Resume" : "Pause"}
        </Button>
      </div>
    </div>
  );
}

function SyntheticAccountCard({
  account,
  onAction,
}: {
  account: AccountSummary;
  onAction?: (account: AccountSummary, action: AccountAction) => void;
}) {
  const blurred = usePrivacyStore((s) => s.blurred);
  const pauseMutation = useClaudeSidecarAccountPause();
  const isOpenRouter = account.provider === "openrouter";
  const isOrcaRouter = account.provider === "orcarouter";
  const isOmniRoute = account.provider === "omniroute";
  const isOllama = account.provider === "ollama";
  const sidecarLabel = isOpenRouter
    ? "OpenRouter"
    : isOrcaRouter
      ? "OrcaRouter"
      : isOmniRoute
        ? "OmniRoute"
        : isOllama
          ? "Ollama"
          : "CLI Proxy API";
  const isClaude = !isOpenRouter && !isOrcaRouter && !isOmniRoute && !isOllama;
  const status = normalizeStatus(account.status);
  const requestCount = account.requestUsage?.requestCount ?? null;
  const totalTokens = account.requestUsage?.totalTokens ?? null;
  const totalSavings = account.requestUsage?.totalSavingsUsd ?? 0;
  const primaryRemaining = account.usage?.primaryRemainingPercent ?? null;
  const secondaryRemaining = account.usage?.secondaryRemainingPercent ?? null;
  const sidecarAuths = account.sidecarAuths ?? [];
  const usageSourceLabel = (oauthSource: boolean, hasPercent: boolean): string =>
    oauthSource ? "OAuth" : hasPercent ? "Estimated" : "Unavailable";
  const aggregateUsageSourceLabel = usageSourceLabel(
    sidecarAuths.some((auth) => auth.usageSource === "oauth_usage"),
    primaryRemaining !== null || secondaryRemaining !== null,
  );
  const hasAggregateUsage = primaryRemaining !== null || secondaryRemaining !== null;
  return (
    <div className="card-hover rounded-xl border bg-card p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold leading-tight">
            {account.displayName}
          </p>
          <p className="mt-0.5 truncate text-xs text-muted-foreground">
            {formatSlug(account.provider ?? "claude")} | {account.baseUrl ?? sidecarLabel}
          </p>
        </div>
        <StatusBadge status={status} />
      </div>

      {isClaude ? (
        sidecarAuths.length > 0 ? (
          <div className="mt-3 space-y-3">
            {sidecarAuths.map((auth, idx) => {
              const authLabel = auth.email ?? auth.name;
              const authUsageSource = usageSourceLabel(
                auth.usageSource === "oauth_usage",
                auth.primaryRemainingPercent !== null || auth.secondaryRemainingPercent !== null,
              );
              return (
                <div key={`${auth.name}-${idx}`} className="space-y-2 rounded-lg border bg-muted/20 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className={cn("min-w-0 truncate text-xs font-medium", auth.paused && "text-muted-foreground line-through")}>
                      <span className={blurred ? "privacy-blur" : undefined}>{authLabel}</span> Usage
                    </span>
                    <div className="flex shrink-0 items-center gap-1.5">
                      {auth.paused ? (
                        <Badge variant="outline" className="text-[11px] text-amber-600">Paused</Badge>
                      ) : null}
                      <Badge variant="outline" className="text-[11px]">{authUsageSource}</Badge>
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        className={cn(
                          "h-6 gap-1 px-1.5 text-[11px]",
                          auth.paused
                            ? "text-emerald-600 hover:text-emerald-700"
                            : "text-amber-600 hover:text-amber-700",
                        )}
                        disabled={pauseMutation.isPending}
                        aria-label={`${auth.paused ? "Resume" : "Pause"} ${authLabel}`}
                        onClick={() => pauseMutation.mutate({ name: auth.name, paused: !auth.paused })}
                      >
                        {auth.paused ? <Play className="h-3 w-3" /> : <Pause className="h-3 w-3" />}
                        {auth.paused ? "Resume" : "Pause"}
                      </Button>
                    </div>
                  </div>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <QuotaBar
                      label="5h"
                      percent={auth.primaryRemainingPercent ?? null}
                      resetLabel={formatQuotaResetLabel(auth.resetAtPrimary ?? null)}
                    />
                    <QuotaBar
                      label="Weekly"
                      percent={auth.secondaryRemainingPercent ?? null}
                      resetLabel={formatQuotaResetLabel(auth.resetAtSecondary ?? null)}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        ) : hasAggregateUsage ? (
          <div className="mt-3 space-y-2 rounded-lg border bg-muted/20 p-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium">Claude Usage</span>
              <Badge variant="outline" className="text-[11px]">{aggregateUsageSourceLabel}</Badge>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <QuotaBar
                label="5h"
                percent={primaryRemaining}
                resetLabel={formatQuotaResetLabel(account.resetAtPrimary ?? null)}
              />
              <QuotaBar
                label="Weekly"
                percent={secondaryRemaining}
                resetLabel={formatQuotaResetLabel(account.resetAtSecondary ?? null)}
              />
            </div>
          </div>
        ) : null
      ) : (
        <div className="mt-3 grid gap-2 text-xs text-muted-foreground">
          <div className="flex items-center justify-between gap-2">
            <span>Health</span>
            <span className="truncate font-medium text-foreground">
              {formatSlug(account.healthStatus ?? account.status)}
            </span>
          </div>
          {requestCount !== null ? (
            <div className="flex items-center justify-between gap-2">
              <span>Requests</span>
              <span className="font-medium tabular-nums text-foreground">
                {requestCount}
                {totalTokens != null && totalTokens > 0 ? ` | ${totalTokens.toLocaleString()} tok` : ""}
              </span>
            </div>
          ) : null}
          {totalSavings > 0 ? (
            <div className="flex items-center justify-between gap-2">
              <span>Saved</span>
              <span className="font-medium tabular-nums text-emerald-600 dark:text-emerald-400">
                {formatCurrency(totalSavings)}
              </span>
            </div>
          ) : null}
        </div>
      )}

      <div className="mt-3">
        <SidecarEffortSelect provider={account.provider} />
      </div>

      <div className="mt-3 flex items-center gap-1.5 border-t pt-3">
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className="h-7 gap-1.5 rounded-lg text-xs text-muted-foreground hover:text-foreground"
          onClick={() => onAction?.(account, "details")}
        >
          <ExternalLink className="h-3 w-3" />
          Details
        </Button>
      </div>
    </div>
  );
}
