import { Bot, Settings as SettingsIcon } from "lucide-react";
import { Link } from "react-router-dom";

import { isEmailLabel } from "@/components/blur-email";
import { usePrivacyStore } from "@/hooks/use-privacy";
import { AccountAliasForm } from "@/features/accounts/components/account-alias-form";
import { AccountActions } from "@/features/accounts/components/account-actions";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { AccountProxyBinding } from "@/features/accounts/components/account-proxy-binding";
import { AccountTokenInfo } from "@/features/accounts/components/account-token-info";
import { AccountUsagePanel } from "@/features/accounts/components/account-usage-panel";
import type {
  AccountRoutingPolicy,
  AccountSummary,
} from "@/features/accounts/schemas";
import { useAccountTrends } from "@/features/accounts/hooks/use-accounts";
import type { AccountProxyBindingRequest, UpstreamProxyAdmin } from "@/features/settings/schemas";
import { formatCompactAccountId } from "@/utils/account-identifiers";
import { formatDateTimeInline, formatPercentNullable, formatQuotaResetLabel, formatSlug } from "@/utils/formatters";

export type AccountDetailProps = {
  account: AccountSummary | null;
  showAccountId?: boolean;
  busy: boolean;
  onPause: (accountId: string) => void;
  onResume: (accountId: string) => void;
  onProbe: (accountId: string) => void;
  onSetAlias: (accountId: string, alias: string | null) => Promise<unknown>;
  onDelete: (accountId: string) => void;
  onReauth: () => void;
  onExportAuth: (accountId: string) => void;
  onLimitWarmupChange: (accountId: string, enabled: boolean) => void;
  onRoutingPolicyChange: (
    accountId: string,
    routingPolicy: AccountRoutingPolicy,
  ) => void;
  onSecurityWorkAuthorizedChange: (accountId: string, enabled: boolean) => void;
  upstreamProxyAdmin?: UpstreamProxyAdmin | null;
  onProxyBindingSave?: (accountId: string, payload: AccountProxyBindingRequest) => Promise<unknown>;
};

export function AccountDetail({
  account,
  showAccountId = false,
  busy,
  onPause,
  onResume,
  onProbe,
  onSetAlias,
  onDelete,
  onReauth,
  onExportAuth,
  onLimitWarmupChange,
  onRoutingPolicyChange,
  onSecurityWorkAuthorizedChange,
  upstreamProxyAdmin = null,
  onProxyBindingSave,
}: AccountDetailProps) {
  const { data: trends } = useAccountTrends(account?.accountId ?? null);
  const blurred = usePrivacyStore((s) => s.blurred);

  if (!account) {
    return (
      <div className="flex flex-col items-center justify-center rounded-xl border border-dashed p-12">
        <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-muted">
          <Bot className="h-5 w-5 text-muted-foreground" />
        </div>
        <p className="mt-3 text-sm font-medium text-muted-foreground">
          Select an account
        </p>
        <p className="mt-1 text-xs text-muted-foreground/70">
          Choose an account from the list to view details.
        </p>
      </div>
    );
  }

  if (account.synthetic) {
    return <SyntheticAccountDetail account={account} busy={busy} />;
  }

  const title = account.displayName || account.email;
  const titleIsEmail = isEmailLabel(title, account.email);
  const compactId = formatCompactAccountId(account.accountId);
  const emailSubtitle =
    account.displayName && account.displayName !== account.email
      ? account.email
      : null;
  const idSuffix = showAccountId ? ` (${compactId})` : "";
  const workspaceLabel = account.workspaceLabel || account.workspaceId || "Personal / unknown workspace";
  const seatLabel = account.seatType ? ` | ${formatSlug(account.seatType)}` : "";

  return (
    <div
      key={account.accountId}
      className="animate-fade-in-up space-y-4 rounded-xl border bg-card p-5"
    >
      {/* Account header */}
      <div>
        <h2 className="text-base font-semibold">
          {titleIsEmail ? (
            <>
              <span className={blurred ? "privacy-blur" : ""}>{title}</span>
              {idSuffix}
            </>
          ) : (
            <>
              {title}
              {!emailSubtitle ? idSuffix : ""}
            </>
          )}
        </h2>
        {emailSubtitle ? (
          <p
            className="mt-0.5 text-xs text-muted-foreground"
            title={
              showAccountId ? `Account ID ${account.accountId}` : undefined
            }
          >
            <span className={blurred ? "privacy-blur" : ""}>
              {emailSubtitle}
            </span>
            {showAccountId ? ` | ID ${compactId}` : ""}
          </p>
        ) : null}
        <p className="mt-0.5 text-xs text-muted-foreground">
          {workspaceLabel} | {formatSlug(account.planType)}{seatLabel}
        </p>
      </div>

      <AccountAliasForm account={account} busy={busy} onSetAlias={onSetAlias} />
      {onProxyBindingSave ? (
        <AccountProxyBinding
          account={account}
          admin={upstreamProxyAdmin}
          busy={busy}
          onSave={onProxyBindingSave}
        />
      ) : null}
      <AccountUsagePanel account={account} trends={trends} />
      <AccountTokenInfo account={account} />
      <AccountActions
        account={account}
        busy={busy}
        onPause={onPause}
        onResume={onResume}
        onProbe={onProbe}
        onDelete={onDelete}
        onReauth={onReauth}
        onExportAuth={onExportAuth}
        onLimitWarmupChange={onLimitWarmupChange}
        onRoutingPolicyChange={onRoutingPolicyChange}
        onSecurityWorkAuthorizedChange={onSecurityWorkAuthorizedChange}
      />
    </div>
  );
}

function SyntheticAccountDetail({ account, busy }: { account: AccountSummary; busy: boolean }) {
  const lastChecked = account.lastCheckedAt ? formatDateTimeInline(account.lastCheckedAt) : null;
  const lastQuotaCheck = account.lastRefreshAt ? formatDateTimeInline(account.lastRefreshAt) : null;
  const primaryRemaining = account.usage?.primaryRemainingPercent ?? null;
  const secondaryRemaining = account.usage?.secondaryRemainingPercent ?? null;
  const usageSourceLabel = account.sidecarAuths?.some((auth) => auth.usageSource === "oauth_usage")
    ? "OAuth"
    : primaryRemaining !== null || secondaryRemaining !== null
      ? "Estimated"
      : "Unavailable";
  return (
    <div
      key={account.accountId}
      className="animate-fade-in-up space-y-4 rounded-xl border bg-card p-5"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-base font-semibold">
            <Bot className="h-4 w-4 text-primary" aria-hidden="true" />
            {account.displayName}
          </h2>
          <p className="mt-0.5 text-xs text-muted-foreground">Read-only Claude sidecar account</p>
        </div>
        <Badge variant="outline" className="border-violet-300 bg-violet-50 text-violet-700">
          CLIProxyAPI
        </Badge>
      </div>

      <div className="grid gap-3 rounded-lg border bg-muted/20 p-4 text-sm sm:grid-cols-2">
        <SyntheticField label="Status" value={formatSlug(account.healthStatus ?? account.status)} />
        <SyntheticField label="Quota" value={formatSidecarQuotaLabel(account)} />
        <SyntheticField label="Models" value={account.modelCount == null ? "--" : String(account.modelCount)} />
        <SyntheticField label="Base URL" value={account.baseUrl ?? "--"} mono />
        <SyntheticField label="Last check" value={lastChecked ?? "Never"} />
        <SyntheticField label="Last quota check" value={lastQuotaCheck ?? "Never"} />
      </div>

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
                      auth.quotaExceeded ? "bg-amber-500" : "bg-emerald-500"
                    }`}
                  />
                  <div className="min-w-0 leading-tight">
                    <div className="truncate text-sm font-medium">{auth.email ?? auth.name}</div>
                    <div className="truncate text-[11px] text-muted-foreground">
                      {auth.authIndex ? `auth_index ${auth.authIndex} | ` : ""}
                      {auth.quotaExceeded
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
                <div className="shrink-0 text-right text-[11px] text-muted-foreground">
                  <div>OK {auth.success}</div>
                  <div>Failed {auth.failed}</div>
                </div>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {account.healthMessage ? (
        <div className="rounded-md border bg-muted/30 p-3 text-xs text-muted-foreground">
          {account.healthMessage}
        </div>
      ) : null}

      <div className="flex flex-wrap gap-2 border-t pt-4">
        <Button asChild type="button" size="sm" variant="outline" className="h-8 gap-1.5 text-xs" disabled={busy}>
          <Link to="/settings#claude-sidecar">
            <SettingsIcon className="h-3.5 w-3.5" />
            Configure
          </Link>
        </Button>
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

function formatSidecarQuotaLabel(account: AccountSummary): string {
  const status = account.status;
  if (status === "quota_exceeded") {
    return `Exhausted — resets ${formatQuotaResetLabel(account.resetAtPrimary ?? null)}`;
  }
  if (status === "rate_limited") {
    return `Limited — resets ${formatQuotaResetLabel(account.resetAtPrimary ?? null)}`;
  }
  if (status === "active") {
    return "OK";
  }
  return "--";
}
