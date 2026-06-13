import { Bot, Clock, ExternalLink, Play, RotateCcw, Zap } from "lucide-react";

import { usePrivacyStore } from "@/hooks/use-privacy";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/status-badge";
import { cn } from "@/lib/utils";
import type { AccountSummary } from "@/features/dashboard/schemas";
import { formatCompactAccountId } from "@/utils/account-identifiers";
import {
  normalizeStatus,
  quotaBarColor,
  quotaBarTrack,
} from "@/utils/account-status";
import { formatDateTimeInline, formatPercentNullable, formatQuotaResetLabel, formatSlug } from "@/utils/formatters";

type AccountAction = "details" | "resume" | "reauth" | "warmup-toggle";

export type AccountCardProps = {
  account: AccountSummary;
  showAccountId?: boolean;
  onAction?: (account: AccountSummary, action: AccountAction) => void;
};

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

export function AccountCard({ account, showAccountId = false, onAction }: AccountCardProps) {
  if (account.synthetic) {
    return <SyntheticAccountCard account={account} onAction={onAction} />;
  }
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
  const creditsLabel = account.creditsUnlimited ? "Unlimited" : (
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
  const warmupStatus = account.limitWarmupEnabled ? "Warm-up on" : "Warm-up off";
  const warmupToggleLabel = `${account.limitWarmupEnabled ? "Disable" : "Enable"} limit warm-up for ${title}`;
  const warmupDetail = account.limitWarmup
    ? `${formatSlug(account.limitWarmup.status)} | ${account.limitWarmup.window === "primary" ? "5h" : "weekly"} | ${formatSlug(account.limitWarmup.model)} | ${formatDateTimeInline(account.limitWarmup.completedAt ?? account.limitWarmup.attemptedAt)}`
    : "No attempts";

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
            <p className="mt-0.5 truncate text-xs text-muted-foreground" title={showAccountId ? `Account ID ${account.accountId}` : undefined}>
              <span className={blurred ? "privacy-blur" : undefined}>{emailSubtitle}</span>{showAccountId ? ` | ID ${compactId}` : ""}
            </p>
          ) : null}
        </div>
        <StatusBadge status={status} />
      </div>

      {/* Quota bars */}
      <div className={cn("mt-3.5 grid gap-3", weeklyOnly || monthlyOnly ? "grid-cols-1" : "grid-cols-2")}>
        {monthlyOnly ? (
          <QuotaBar label="Monthly" percent={monthlyRemaining} resetLabel={monthlyReset} />
        ) : (
          <>
            {!weeklyOnly && <QuotaBar label="5h" percent={primaryRemaining} resetLabel={primaryReset} />}
            <QuotaBar label="Weekly" percent={secondaryRemaining} resetLabel={secondaryReset} />
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
          onClick={() => onAction?.(account, "warmup-toggle")}
        >
          <Zap className="h-3 w-3" aria-hidden="true" />
          {account.limitWarmupEnabled ? "On" : "Off"}
        </Button>
      </div>

      <div className="mt-3 text-xs text-muted-foreground">
        Credits:{" "}
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
          Details
        </Button>
        {status === "paused" && (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="h-7 gap-1.5 rounded-lg text-xs text-emerald-600 hover:bg-emerald-500/10 hover:text-emerald-700 dark:text-emerald-400 dark:hover:text-emerald-300"
            onClick={() => onAction?.(account, "resume")}
          >
            <Play className="h-3 w-3" />
            Resume
          </Button>
        )}
        {(status === "reauth" || status === "deactivated") && (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="h-7 gap-1.5 rounded-lg text-xs text-amber-600 hover:bg-amber-500/10 hover:text-amber-700 dark:text-amber-400 dark:hover:text-amber-300"
            onClick={() => onAction?.(account, "reauth")}
          >
            <RotateCcw className="h-3 w-3" />
            Re-auth
          </Button>
        )}
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
  const isOpenRouter = account.provider === "openrouter";
  const isOmniRoute = account.provider === "omniroute";
  const sidecarLabel = isOpenRouter ? "OpenRouter" : isOmniRoute ? "OmniRoute" : "CLI Proxy API";
  const isClaude = !isOpenRouter && !isOmniRoute;
  const status = normalizeStatus(account.status);
  const requestCount = account.requestUsage?.requestCount ?? null;
  const totalTokens = account.requestUsage?.totalTokens ?? null;
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
        <div className="flex shrink-0 items-center gap-2">
          <Badge
            variant="outline"
            className="gap-1 border-violet-300 bg-violet-50 px-1.5 text-[11px] text-violet-700"
          >
            <Bot className="h-3 w-3" aria-hidden="true" />
            {sidecarLabel}
          </Badge>
          <StatusBadge status={status} />
        </div>
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
                    <span className="min-w-0 truncate text-xs font-medium">
                      <span className={blurred ? "privacy-blur" : undefined}>{authLabel}</span> Usage
                    </span>
                    <Badge variant="outline" className="shrink-0 text-[11px]">{authUsageSource}</Badge>
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
          <div className="flex items-center justify-between gap-2">
            <span>Models</span>
            <span className="font-medium text-foreground">{account.modelCount ?? "--"}</span>
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
        </div>
      )}

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
