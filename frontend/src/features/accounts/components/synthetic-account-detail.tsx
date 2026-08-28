import { Bot, ExternalLink, Pause, Play, PlugZap, Settings as SettingsIcon } from "lucide-react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { ClaudeSidecarQuotaEstimation } from "@/features/accounts/components/claude-sidecar-quota-estimation";
import { SidecarEffortSelect } from "@/features/accounts/components/sidecar-effort-select";
import type { AccountSummary } from "@/features/accounts/schemas";
import {
  useClaudeSidecarAccountPause,
  useSidecarConnectionTest,
  type SidecarConnectionProvider,
} from "@/features/settings/hooks/use-settings";
import { formatDateTimeInline, formatPercentNullable, formatQuotaResetLabel, formatSlug } from "@/utils/formatters";

function testProviderFor(provider: string | null | undefined): SidecarConnectionProvider {
  if (provider === "openrouter") {
    return "openrouter";
  }
  if (provider === "orcarouter") {
    return "orcarouter";
  }
  if (provider === "omniroute") {
    return "omniroute";
  }
  if (provider === "ollama") {
    return "ollama";
  }
  return "claude";
}

export function SyntheticAccountDetail({ account, busy }: { account: AccountSummary; busy: boolean }) {
  const isOpenRouter = account.provider === "openrouter";
  const isOrcaRouter = account.provider === "orcarouter";
  const isOmniRoute = account.provider === "omniroute";
  const isOllama = account.provider === "ollama";
  // Allowlisted, not "everything that is not one of the HTTP sidecars": a new
  // integration must never inherit Claude pause and quota controls by default.
  // An absent provider still means Claude, matching testProviderFor's default
  // and the schema, which declares provider as nullable/optional.
  const isClaude = (account.provider ?? "claude") === "claude";
  const testProvider = testProviderFor(account.provider);
  const testMutation = useSidecarConnectionTest(testProvider);
  const pauseMutation = useClaudeSidecarAccountPause();
  const settingsAnchor = isOpenRouter
    ? "/settings#openrouter-sidecar"
    : isOrcaRouter
      ? "/settings#orcarouter-sidecar"
      : isOmniRoute
        ? "/settings#omniroute-sidecar"
        : isOllama
          ? "/settings#ollama-sidecar"
          : "/settings#claude-sidecar";
  const lastChecked = account.lastCheckedAt ? formatDateTimeInline(account.lastCheckedAt) : null;
  const lastQuotaCheck = account.lastRefreshAt ? formatDateTimeInline(account.lastRefreshAt) : null;
  const primaryRemaining = account.usage?.primaryRemainingPercent ?? null;
  const secondaryRemaining = account.usage?.secondaryRemainingPercent ?? null;
  const usageSourceLabel = account.sidecarAuths?.some((auth) => auth.usageSource === "oauth_usage")
    ? "OAuth"
    : primaryRemaining !== null || secondaryRemaining !== null
      ? "Estimated"
      : "Unavailable";
  const showQuotaUsage = isClaude;
  const testDisabled = busy || testMutation.isPending;
  return (
    <div
      key={account.accountId}
      className="animate-fade-in-up space-y-4 rounded-xl border bg-card p-5"
    >
      <div>
        <h2 className="flex items-center gap-2 text-base font-semibold">
          <Bot className="h-4 w-4 text-primary" aria-hidden="true" />
          {account.displayName}
        </h2>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {isOpenRouter
            ? "Read-only OpenRouter sidecar account"
            : isOrcaRouter
              ? "Read-only OrcaRouter account"
              : isOmniRoute
                ? "Read-only OmniRoute sidecar account"
                : isOllama
                  ? "Read-only Ollama account"
                  : "Read-only Claude sidecar account"}
        </p>
      </div>

      <div className="grid gap-3 rounded-lg border bg-muted/20 p-4 text-sm sm:grid-cols-2">
        <SyntheticField label="Connection" value={formatSlug(account.healthStatus ?? account.status)} />
        <SyntheticField label="Base URL" value={account.baseUrl ?? "--"} mono />
        <SyntheticField label="Last checked" value={lastChecked ?? "Never"} />
        {showQuotaUsage ? (
          <SyntheticField label="Last quota check" value={lastQuotaCheck ?? "Never"} />
        ) : null}
      </div>

      {showQuotaUsage ? (
      <div className="grid gap-3 rounded-lg border bg-muted/10 p-4 text-sm sm:grid-cols-2">
        <SyntheticField
          label={`${usageSourceLabel} 5h remaining`}
          value={`${formatPercentNullable(primaryRemaining)} | resets ${formatQuotaResetLabel(account.resetAtPrimary ?? null)}`}
        />
        <SyntheticField
          label={`${usageSourceLabel} weekly remaining`}
          value={`${formatPercentNullable(secondaryRemaining)} | resets ${formatQuotaResetLabel(account.resetAtSecondary ?? null)}`}
        />
      </div>
      ) : null}

      {account.sidecarAuths && account.sidecarAuths.length > 0 ? (
        <div className="space-y-1 rounded-lg border bg-card/40 p-3 text-sm">
          <div className="px-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground/80">
            Sidecar accounts
          </div>
          <ul className="divide-y">
            {account.sidecarAuths.map((auth, idx) => (
              <li key={`${auth.name}-${idx}`} className="flex items-center justify-between gap-3 py-2">
                <div className="flex min-w-0 items-center gap-2">
                  <span
                    aria-hidden="true"
                    className={`inline-block h-2 w-2 rounded-full ${
                      auth.paused ? "bg-zinc-400" : auth.quotaExceeded ? "bg-amber-500" : "bg-emerald-500"
                    }`}
                  />
                  <div className="min-w-0 leading-tight">
                    <div className={`truncate text-sm font-medium ${auth.paused ? "text-muted-foreground line-through" : ""}`}>
                      {auth.email ?? auth.name}
                    </div>
                    <div className="truncate text-[11px] text-muted-foreground">
                      {auth.authIndex ? `auth_index ${auth.authIndex} | ` : ""}
                      {auth.paused
                        ? "Paused"
                        : auth.quotaExceeded
                          ? `Exhausted — recovers ${formatQuotaResetLabel(auth.nextRecoverAt ?? null)}`
                          : "Ready"}
                      {auth.modelsExceeded && auth.modelsExceeded.length > 0
                        ? ` | models exceeded: ${auth.modelsExceeded.join(", ")}`
                        : ""}
                    </div>
                    <div className="truncate text-[11px] text-muted-foreground">
                      {auth.planType ? `${formatSlug(auth.planType)} | ` : "Plan required | "}
                      5h {formatPercentNullable(auth.primaryRemainingPercent ?? null)}
                      {auth.primaryUsedTokens != null && auth.primaryTokenBudget != null
                        ? ` (${auth.primaryUsedTokens.toLocaleString()} / ${auth.primaryTokenBudget.toLocaleString()} tok)`
                        : ""}
                      {" | "}
                      weekly {formatPercentNullable(auth.secondaryRemainingPercent ?? null)}
                      {auth.secondaryUsedTokens != null && auth.secondaryTokenBudget != null
                        ? ` (${auth.secondaryUsedTokens.toLocaleString()} / ${auth.secondaryTokenBudget.toLocaleString()} tok)`
                        : ""}
                    </div>
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <div className="text-right text-[11px] text-muted-foreground">
                    <div>OK {auth.success}</div>
                    <div>Failed {auth.failed}</div>
                  </div>
                  {isClaude ? (
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      className={`h-7 gap-1 text-xs ${auth.paused ? "text-emerald-600 hover:text-emerald-700" : "text-amber-600 hover:text-amber-700"}`}
                      disabled={busy || pauseMutation.isPending}
                      aria-label={`${auth.paused ? "Resume" : "Pause"} ${auth.email ?? auth.name}`}
                      onClick={() => pauseMutation.mutate({ name: auth.name, paused: !auth.paused })}
                    >
                      {auth.paused ? <Play className="h-3 w-3" /> : <Pause className="h-3 w-3" />}
                      {auth.paused ? "Resume" : "Pause"}
                    </Button>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {isClaude ? <ClaudeSidecarQuotaEstimation /> : null}

      <SidecarEffortSelect provider={account.provider} />

      {account.healthMessage ? (
        <div className="rounded-md border bg-muted/30 p-3 text-xs text-muted-foreground">
          {account.healthMessage}
        </div>
      ) : null}

      <div className="flex flex-wrap gap-2 border-t pt-4">
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="h-8 gap-1.5 text-xs"
          disabled={testDisabled}
          onClick={() => void testMutation.mutateAsync().catch(() => null)}
        >
          <PlugZap className="h-3.5 w-3.5" />
          Test connection
        </Button>
        <Button asChild type="button" size="sm" variant="outline" className="h-8 gap-1.5 text-xs" disabled={busy}>
          <Link to={settingsAnchor}>
            <SettingsIcon className="h-3.5 w-3.5" />
            Configure
          </Link>
        </Button>
        {isOmniRoute ? (
          <Button asChild type="button" size="sm" variant="outline" className="h-8 gap-1.5 text-xs" disabled={busy}>
            <a href="/omni" target="_blank" rel="noopener noreferrer">
              Open OmniRoute
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
          </Button>
        ) : null}
      </div>
    </div>
  );
}

function SyntheticField({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="space-y-1">
      <div className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground/80">{label}</div>
      <div className={`break-all text-sm ${mono ? "font-mono" : ""}`}>{value}</div>
    </div>
  );
}
