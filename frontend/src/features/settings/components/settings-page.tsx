<<<<<<< 22625a07e
import { Suspense, lazy, useEffect, useState, type ReactNode } from "react";
import {
  Activity,
  ArrowRightLeft,
  Boxes,
  KeySquare,
  LayoutDashboard,
  Palette,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  type LucideIcon,
} from "lucide-react";
||||||| 84fde5a1e
import { Suspense, lazy } from "react";
import { Settings } from "lucide-react";
=======
import { useState } from "react";
import { Settings } from "lucide-react";
>>>>>>> 72630bbfe
import { useTranslation } from "react-i18next";
import { useLocation } from "react-router-dom";

import { AlertMessage } from "@/components/alert-message";
import { LoadingOverlay } from "@/components/layout/loading-overlay";
import { Button } from "@/components/ui/button";
import { ApiKeysSection } from "@/features/api-keys/components/api-keys-section";
import { useAccounts } from "@/features/accounts/hooks/use-accounts";
import { FirewallSection } from "@/features/firewall/components/firewall-section";
import { ModelSourcesSettings } from "@/features/model-sources/components/model-sources-settings";
import { QuotaPlannerSection } from "@/features/quota-planner/components/quota-planner-section";
import { shouldExpandAdvancedSettings } from "@/features/settings/advanced-settings-deeplink";
import { AccessCard } from "@/features/settings/components/access/access-card";
import { AdvancedSettingsGroup } from "@/features/settings/components/advanced-settings-group";
<<<<<<< 22625a07e
import { AliasSettings } from "@/features/settings/components/alias-settings";
||||||| 84fde5a1e
=======
import { OrganisationSettingsGroup } from "@/features/settings/components/organisation/organisation-group";
>>>>>>> 72630bbfe
import { AppearanceSettings } from "@/features/settings/components/appearance-settings";
<<<<<<< 22625a07e
import { DashboardLayoutSettings } from "@/features/settings/components/dashboard-layout-settings";
||||||| 84fde5a1e
=======
import { ConversationArchiveSettings } from "@/features/settings/components/conversation-archive-settings";
>>>>>>> 72630bbfe
import { DataRetentionSettings } from "@/features/settings/components/data-retention-settings";
<<<<<<< 22625a07e
import { FreeModelDiscoveryPanel } from "@/features/settings/components/free-model-discovery-panel";
import { SidecarIntegrationsCard } from "@/features/settings/components/sidecar-integrations";
import { GuestAccessSettings } from "@/features/settings/components/guest-access-settings";
||||||| 84fde5a1e
import { GuestAccessSettings } from "@/features/settings/components/guest-access-settings";
=======
>>>>>>> 72630bbfe
import { ImportSettings } from "@/features/settings/components/import-settings";
import { ModelCatalogueSettings } from "@/features/settings/components/model-catalogue-settings";
import { ResetCreditSettings } from "@/features/settings/components/reset-credit-settings";
import { ResilienceSettings } from "@/features/settings/components/resilience-settings";
import { SessionBridgeSettings } from "@/features/settings/components/session-bridge-settings";
import { BackgroundJobsSettings } from "@/features/settings/components/background-jobs-settings";
import { RoutingSettings } from "@/features/settings/components/routing-settings";
import { UpstreamTimeoutSettings } from "@/features/settings/components/upstream-timeout-settings";
import { SettingsSkeleton } from "@/features/settings/components/settings-skeleton";
import { TelemetrySettings } from "@/features/settings/components/telemetry-settings";
import { UpstreamProxySettings } from "@/features/settings/components/upstream-proxy-settings";
import { CacheIsolationProbeSection } from "@/features/cache-probe/components/cache-isolation-probe-section";
import { StickySessionsSection } from "@/features/sticky-sessions/components/sticky-sessions-section";
import { useAuthStore, usePermission } from "@/features/auth/hooks/use-auth";
import { useSettings, useUpstreamProxyAdmin } from "@/features/settings/hooks/use-settings";
import type { SettingsUpdateRequest } from "@/features/settings/schemas";
import { getErrorMessageOrNull } from "@/utils/errors";

// C2-2 routing/overload: a layer move (dashboard <-> inherited) without a
// value change must still reset the routing form's drafts.
const ROUTING_OVERLOAD_PROVENANCE_KEYS = [
  "proxy_overload_isolation_seconds",
  "proxy_account_error_rate_weighting_enabled",
  "proxy_account_inflight_penalty_pct",
  "proxy_account_lease_token_weight",
  "proxy_account_lease_ttl_seconds",
] as const;

const FIREWALL_LAYOUT_QUERY_KEYS = [
  ["accounts", "list"],
  ["settings", "upstream-proxy"],
  ["model-sources", "list"],
  // M4 model catalogue: the card sits above Firewall and grows by a table row
  // per override, so a late response would push a #firewall scroll out of view.
  ["settings", "model-context-window-overrides"],
] as const;

type SectionNavItem = {
  id: string;
  label: string;
  icon: LucideIcon;
};

const SECTION_NAV: SectionNavItem[] = [
  { id: "external-integrations-group", label: "Integrations", icon: Boxes },
  { id: "alias-settings", label: "Model aliasing", icon: ArrowRightLeft },
  { id: "appearance-settings", label: "Appearance", icon: Palette },
  { id: "dashboard-settings", label: "Dashboard", icon: LayoutDashboard },
  { id: "account-settings", label: "Accounts", icon: Activity },
  { id: "security-settings", label: "Security", icon: ShieldCheck },
  { id: "api-keys-settings", label: "API keys", icon: KeySquare },
];

const NAV_ITEM_CLASS =
  "flex shrink-0 items-center gap-2 rounded-lg border px-3 py-2 text-left text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60";
const NAV_ITEM_IDLE = "border-transparent text-muted-foreground hover:bg-accent hover:text-foreground";
const NAV_ITEM_ACTIVE = "border-border bg-accent text-foreground";

/**
 * Tracks which navigable section currently sits nearest the top of the
 * viewport, so the rail can highlight it while the operator scrolls.
 */
function useActiveSection(ids: readonly string[], advancedOpen: boolean): string | null {
  const [active, setActive] = useState<string | null>(null);
  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") {
      return;
    }
    const visible = new Map<string, number>();
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            visible.set(entry.target.id, entry.boundingClientRect.top);
          } else {
            visible.delete(entry.target.id);
          }
        }
        let best: string | null = null;
        let bestTop = Number.POSITIVE_INFINITY;
        for (const [id, top] of visible) {
          if (top < bestTop) {
            best = id;
            bestTop = top;
          }
        }
        if (best) {
          setActive(best);
        }
      },
      // Top band of the viewport, so the section under the sticky header wins.
      { rootMargin: "-88px 0px -60% 0px" },
    );
    for (const id of ids) {
      const element = document.getElementById(id);
      if (element) {
        observer.observe(element);
      }
    }
    return () => observer.disconnect();
    // Re-observe when Advanced mounts/unmounts so its anchor is tracked.
  }, [ids, advancedOpen]);
  return active;
}

const NAV_IDS = [...SECTION_NAV.map((item) => item.id), "advanced-settings"] as const;

function scrollToSection(id: string) {
  document.getElementById(id)?.scrollIntoView({ block: "start" });
}

function SectionNav({ advancedOpen, onOpenAdvanced }: { advancedOpen: boolean; onOpenAdvanced: () => void }) {
  const { t } = useTranslation();
  const active = useActiveSection(NAV_IDS, advancedOpen);
  return (
    <nav
      aria-label="Settings sections"
      className="-mx-4 flex gap-1 overflow-x-auto px-4 pb-1 lg:sticky lg:top-20 lg:mx-0 lg:flex-col lg:self-start lg:overflow-visible lg:px-0 lg:pb-0"
    >
      {SECTION_NAV.map(({ id, label, icon: Icon }) => (
        <a
          key={id}
          href={`#${id}`}
          // Scroll without writing the hash: `location.hash` is a deep-link
          // channel (integration Configure links, `#firewall`), and the
          // integrations card discards a manual tab selection whenever it
          // changes. The href stays for middle-click and screen readers.
          onClick={(event) => {
            // Modifier clicks keep native behaviour (open in a new tab).
            if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) {
              return;
            }
            event.preventDefault();
            scrollToSection(id);
          }}
          aria-current={active === id ? "location" : undefined}
          className={`${NAV_ITEM_CLASS} ${active === id ? NAV_ITEM_ACTIVE : NAV_ITEM_IDLE}`}
        >
          <Icon className="h-4 w-4 shrink-0 text-primary/80" aria-hidden="true" />
          {label}
        </a>
      ))}
      <button
        type="button"
        onClick={onOpenAdvanced}
        aria-current={active === "advanced-settings" ? "location" : undefined}
        className={`${NAV_ITEM_CLASS} ${active === "advanced-settings" ? NAV_ITEM_ACTIVE : NAV_ITEM_IDLE} lg:mt-2`}
      >
        <SlidersHorizontal className="h-4 w-4 shrink-0 text-primary/80" aria-hidden="true" />
        {t("settings.advanced.title")}
      </button>
    </nav>
  );
}

function SectionGroup({
  id,
  title,
  description,
  children,
}: {
  id: string;
  title: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <div id={id} className="scroll-mt-24 space-y-4">
      <div className="px-1">
        <h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">{title}</h2>
        {description ? <p className="mt-1 text-sm text-muted-foreground/80">{description}</p> : null}
      </div>
      {children}
    </div>
  );
}

function Notice({ tone, children }: { tone: "info" | "warning"; children: ReactNode }) {
  const toneClass =
    tone === "warning"
      ? "border-amber-500/30 bg-amber-500/10 text-amber-900 dark:text-amber-200"
      : "border-primary/25 bg-primary/8 text-foreground";
  return <div className={`rounded-lg border px-4 py-3 text-sm font-medium ${toneClass}`}>{children}</div>;
}

export function SettingsPage() {
  const { t } = useTranslation();
  const location = useLocation();
  const expandAdvanced = shouldExpandAdvancedSettings(location.search, location.hash);
  const advancedScrollToId = location.hash.replace(/^#/, "") || undefined;
  const [advancedOpen, setAdvancedOpen] = useState(expandAdvanced);
  // A later in-app navigation to a deep link (e.g. /firewall redirect) must
  // still open the group; reset during render keyed on the link, not in an
  // effect, so the collapsed state never reaches the DOM first.
  const deeplinkKey = expandAdvanced ? `open:${advancedScrollToId ?? ""}` : "closed";
  const [seenDeeplinkKey, setSeenDeeplinkKey] = useState(deeplinkKey);
  if (seenDeeplinkKey !== deeplinkKey) {
    setSeenDeeplinkKey(deeplinkKey);
    if (expandAdvanced) {
      setAdvancedOpen(true);
    }
  }
  const { settingsQuery, updateSettingsMutation } = useSettings();
  const [initialRetryError, setInitialRetryError] = useState<string | null>(null);
  const { accountsQuery } = useAccounts();
  const authMode = useAuthStore((state) => state.authMode);
  const canWrite = useAuthStore((state) => state.canWrite);
  // Security-bearing controls (API-key auth policy, firewall, proxy endpoints)
  // need `security:write`; an Operator sees them read-only instead of a 403.
  const canWriteSecurity = usePermission("security:write");
  // The probe spends account quota, so it mirrors its backend `ops:write` gate
  // rather than the coarse write alias.
  const canWriteOps = usePermission("ops:write");
  // A fully signed-in account without `write` (a Viewer) still owns its password and two-factor.
  // Any signed-in account reaches its own password/two-factor controls: a
  // reverse-proxy account has no password session and still needs to enrol a
  // second factor, which is how it confirms sensitive changes.
  const personalSignIn = useAuthStore(
    (state) => state.passwordManagementEnabled && (state.passwordSessionActive || state.user !== null),
  );
  // API keys, upstream-proxy administration, and sticky sessions are write-only
  // reads on the backend (403 for guests), so they are not mounted or fetched
  // without write access. `enabled: false` only stops fetching; cached data from
  // an earlier admin session is still returned, so rendering is gated on
  // `canWrite` as well.
  const {
    upstreamProxyQuery,
    createEndpointMutation,
    createPoolMutation,
    addPoolMemberMutation,
    testEndpointMutation,
  } = useUpstreamProxyAdmin({ enabled: canWrite });

  const settings = settingsQuery.data;
  const busy =
    updateSettingsMutation.isPending ||
    createEndpointMutation.isPending ||
    createPoolMutation.isPending ||
    addPoolMemberMutation.isPending ||
    testEndpointMutation.isPending;
  const controlsDisabled = busy || !canWrite;
  const settingsLoadError = getErrorMessageOrNull(
    settingsQuery.error,
    t("settings.toasts.loadFailed"),
  );
  const displayedSettingsLoadError = settingsLoadError || initialRetryError;
  // With no settings loaded the failed-load branch below owns this message, so
  // the page-level alert would otherwise render it a second time.
  const error =
    (settings ? settingsLoadError : null) ||
    getErrorMessageOrNull(upstreamProxyQuery.error) ||
    getErrorMessageOrNull(updateSettingsMutation.error) ||
    getErrorMessageOrNull(createEndpointMutation.error) ||
    getErrorMessageOrNull(createPoolMutation.error) ||
    getErrorMessageOrNull(addPoolMemberMutation.error) ||
    getErrorMessageOrNull(testEndpointMutation.error);

  const handleSave = (patch: Partial<SettingsUpdateRequest>) =>
    updateSettingsMutation.mutateAsync(patch);

  const openAdvanced = () => {
    setAdvancedOpen(true);
    window.requestAnimationFrame(() => scrollToSection("advanced-settings"));
  };

  return (
    <div className="animate-fade-in-up space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2.5 text-2xl font-semibold tracking-tight">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/12 text-primary ring-1 ring-primary/20">
              <Settings className="h-4.5 w-4.5" aria-hidden="true" />
            </span>
            {t("settings.page.title")}
          </h1>
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted-foreground">{t("settings.page.subtitle")}</p>
        </div>
      </div>

      {settingsQuery.isPending && !settings && initialRetryError === null ? (
        <SettingsSkeleton />
      ) : !settings ? (
        <div className="space-y-3 rounded-xl border bg-card p-4">
          <div role="alert">
            <AlertMessage variant="error">
              {displayedSettingsLoadError || t("settings.toasts.loadFailed")}
            </AlertMessage>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              setInitialRetryError(displayedSettingsLoadError || t("settings.toasts.loadFailed"));
              void settingsQuery.refetch().finally(() => {
                setInitialRetryError(null);
              });
            }}
            disabled={settingsQuery.isFetching || initialRetryError !== null}
          >
            {t("common.actions.retry")}
          </Button>
        </div>
      ) : (
        <div className="grid gap-6 lg:grid-cols-[200px_minmax(0,1fr)] lg:gap-10">
          <SectionNav advancedOpen={advancedOpen} onOpenAdvanced={openAdvanced} />

          <div className="min-w-0 space-y-10">
            {error || !canWrite || authMode === "trusted_header" || authMode === "disabled" ? (
              <div className="space-y-3">
                {error ? <AlertMessage variant="error">{error}</AlertMessage> : null}
                {!canWrite ? <Notice tone="info">{t("settings.page.readOnlyNotice")}</Notice> : null}
                {authMode === "trusted_header" ? (
                  <Notice tone="info">{t("settings.page.trustedHeaderNotice")}</Notice>
                ) : null}
                {authMode === "disabled" ? <Notice tone="warning">{t("settings.page.disabledNotice")}</Notice> : null}
              </div>
            ) : null}

<<<<<<< 22625a07e
            <SectionGroup id="external-integrations-group" title="Integrations">
              <SidecarIntegrationsCard
||||||| 84fde5a1e
          {authMode === "disabled" ? (
            <div className="rounded-lg border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-xs font-medium text-foreground">
              {t("settings.page.disabledNotice")}
            </div>
          ) : null}

          <div className="space-y-4">
            <AppearanceSettings />
            <ImportSettings settings={settings} busy={controlsDisabled} onSave={handleSave} />
            <ResetCreditSettings settings={settings} busy={controlsDisabled} onSave={handleSave} />
            {canWrite ? (
              <GuestAccessSettings
=======
          {authMode === "disabled" ? (
            <div className="rounded-lg border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-xs font-medium text-foreground">
              {t("settings.page.disabledNotice")}
            </div>
          ) : null}

          <div className="space-y-4">
            <AppearanceSettings />
            <ImportSettings settings={settings} busy={controlsDisabled} onSave={handleSave} />
            <ResetCreditSettings settings={settings} busy={controlsDisabled} onSave={handleSave} />
            {/* Guest access, password, session and TOTP live inside the Access
                card. It mounts for `write` holders and for any fully signed-in
                account (its own password/TOTP); guests never saw it and still do not. */}
            {canWrite || personalSignIn ? (
              <AccessCard
>>>>>>> 72630bbfe
                settings={settings}
                busy={busy}
                onSave={handleSave}
                locationHash={location.hash}
              />
<<<<<<< 22625a07e
              <FreeModelDiscoveryPanel settings={settings} />
            </SectionGroup>
||||||| 84fde5a1e
            ) : null}
            {canWrite ? <PasswordSettings disabled={busy} /> : null}
            {canWrite && passwordManagementEnabled ? (
              <SessionSettings settings={settings} busy={busy} onSave={handleSave} />
            ) : null}
            {canWrite && passwordManagementEnabled && passwordSessionActive ? (
              <Suspense fallback={null}>
                <TotpSettings settings={settings} disabled={busy} onSave={handleSave} />
              </Suspense>
            ) : null}
=======
            ) : null}
>>>>>>> 72630bbfe

<<<<<<< 22625a07e
            <SectionGroup id="alias-settings" title="Model aliasing">
              <AliasSettings settings={settings} busy={controlsDisabled} onSave={handleSave} />
            </SectionGroup>
||||||| 84fde5a1e
            <ApiKeysSection
              apiKeyAuthEnabled={settings.apiKeyAuthEnabled}
              hideUpstreamQuotaFromApiKeys={settings.hideUpstreamQuotaFromApiKeys}
              disabled={controlsDisabled}
              onApiKeyAuthEnabledChange={(enabled) =>
                void handleSave(buildSettingsUpdateRequest(settings, { apiKeyAuthEnabled: enabled }))
              }
              onHideUpstreamQuotaFromApiKeysChange={(enabled) =>
                void handleSave(buildSettingsUpdateRequest(settings, { hideUpstreamQuotaFromApiKeys: enabled }))
              }
            />
=======
            {canWrite ? (
              <ApiKeysSection
                apiKeyAuthEnabled={settings.apiKeyAuthEnabled}
                hideUpstreamQuotaFromApiKeys={settings.hideUpstreamQuotaFromApiKeys}
                disabled={controlsDisabled}
                policyControlsDisabled={controlsDisabled || !canWriteSecurity}
                onApiKeyAuthEnabledChange={(enabled) =>
                  void handleSave(buildSettingsUpdateRequest(settings, { apiKeyAuthEnabled: enabled }))
                }
                onHideUpstreamQuotaFromApiKeysChange={(enabled) =>
                  void handleSave(buildSettingsUpdateRequest(settings, { hideUpstreamQuotaFromApiKeys: enabled }))
                }
              />
            ) : null}
>>>>>>> 72630bbfe

            <SectionGroup id="appearance-settings" title="Appearance">
              <AppearanceSettings />
            </SectionGroup>

<<<<<<< 22625a07e
            <SectionGroup id="dashboard-settings" title="Dashboard">
              <DashboardLayoutSettings settings={settings} busy={controlsDisabled} onSave={handleSave} />
            </SectionGroup>

            <SectionGroup id="account-settings" title="Accounts">
              <ImportSettings settings={settings} busy={controlsDisabled} onSave={handleSave} />
              <ResetCreditSettings settings={settings} busy={controlsDisabled} onSave={handleSave} />
            </SectionGroup>

            {canWrite ? (
              <SectionGroup id="security-settings" title="Security">
                <GuestAccessSettings
                  settings={settings}
                  busy={busy}
                  onSave={handleSave}
                  onRefresh={() => settingsQuery.refetch()}
||||||| 84fde5a1e
            <AdvancedSettingsGroup
              key={expandAdvanced ? `open:${advancedScrollToId ?? ""}` : "closed"}
              defaultOpen={expandAdvanced}
              scrollToId={advancedScrollToId}
              waitForQueryKeys={FIREWALL_LAYOUT_QUERY_KEYS}
            >
              <RoutingSettings
                key={[
                  settings.openaiCacheAffinityMaxAgeSeconds,
                  settings.warmupModel,
                  settings.limitWarmupModel,
                  settings.limitWarmupPrompt,
                  settings.limitWarmupExhaustedThresholdPercent,
                  settings.limitWarmupIdleThresholdPercent,
                  settings.limitWarmupCooldownSeconds,
                  settings.limitWarmupStaggeredIdleEnabled,
                  settings.proxyAccountResponseCreateLimit,
                  settings.proxyAccountStreamLimit,
                  settings.proxyAccountStreamRecoveryReserve,
                  settings.proxyApiKeyFairShareCongestionThresholdPct,
                ].join(":")}
                settings={settings}
                accounts={accountsQuery.data ?? []}
                accountsLoading={accountsQuery.isLoading}
                busy={controlsDisabled}
                onSave={handleSave}
              />
              {upstreamProxyQuery.data ? (
                <UpstreamProxySettings
                  admin={upstreamProxyQuery.data}
                  busy={controlsDisabled}
                  onSaveSettings={handleSave}
                  onCreateEndpoint={(payload) => createEndpointMutation.mutateAsync(payload)}
                  onTestEndpoint={(endpointId) => testEndpointMutation.mutateAsync(endpointId)}
                  onCreatePool={(payload) => createPoolMutation.mutateAsync(payload)}
                  onAddPoolMember={(poolId, payload) =>
                    addPoolMemberMutation.mutateAsync({ poolId, payload })
                  }
=======
            <AdvancedSettingsGroup
              key={expandAdvanced ? `open:${advancedScrollToId ?? ""}` : "closed"}
              defaultOpen={expandAdvanced}
              scrollToId={advancedScrollToId}
              waitForQueryKeys={FIREWALL_LAYOUT_QUERY_KEYS}
            >
              <RoutingSettings
                key={[
                  settings.openaiCacheAffinityMaxAgeSeconds,
                  settings.warmupModel,
                  settings.limitWarmupModel,
                  settings.limitWarmupPrompt,
                  settings.limitWarmupExhaustedThresholdPercent,
                  settings.limitWarmupIdleThresholdPercent,
                  settings.limitWarmupCooldownSeconds,
                  settings.limitWarmupStaggeredIdleEnabled,
                   settings.proxyAccountResponseCreateLimit,
                   settings.proxyAccountResponseCreateLimitOverride,
                   settings.proxyAccountStreamLimit,
                   settings.proxyAccountStreamLimitOverride,
                   settings.proxyAccountStreamRecoveryReserve,
                   settings.proxyAccountStreamRecoveryReserveOverride,
                   settings.proxyApiKeyFairShareCongestionThresholdPct,
                   settings.proxyApiKeyFairShareCongestionThresholdPctOverride,
                   settings.proxyOverloadIsolationSeconds,
                   settings.proxyAccountErrorRateWeightingEnabled,
                   settings.proxyAccountInflightPenaltyPct,
                   settings.proxyAccountLeaseTokenWeight,
                   settings.proxyAccountLeaseTtlSeconds,
                   ...ROUTING_OVERLOAD_PROVENANCE_KEYS.map((name) => settings.provenance?.[name]?.source ?? ""),
                ].join(":")}
                settings={settings}
                accounts={accountsQuery.data ?? []}
                accountsLoading={accountsQuery.isLoading}
                busy={controlsDisabled}
                onSave={handleSave}
              />
              <ResilienceSettings settings={settings} busy={controlsDisabled} onSave={handleSave} />
              <SessionBridgeSettings settings={settings} busy={controlsDisabled} onSave={handleSave} />
              <BackgroundJobsSettings settings={settings} busy={controlsDisabled} onSave={handleSave} />
              {canWrite && upstreamProxyQuery.data ? (
                <UpstreamProxySettings
                  admin={upstreamProxyQuery.data}
                  busy={controlsDisabled}
                  canCreateEndpoint={canWriteSecurity}
                  onSaveSettings={handleSave}
                  onCreateEndpoint={(payload) => createEndpointMutation.mutateAsync(payload)}
                  onTestEndpoint={(endpointId) => testEndpointMutation.mutateAsync(endpointId)}
                  onCreatePool={(payload) => createPoolMutation.mutateAsync(payload)}
                  onAddPoolMember={(poolId, payload) =>
                    addPoolMemberMutation.mutateAsync({ poolId, payload })
                  }
>>>>>>> 72630bbfe
                />
<<<<<<< 22625a07e
                <PasswordSettings disabled={busy} />
                {passwordManagementEnabled ? (
                  <SessionSettings settings={settings} busy={busy} onSave={handleSave} />
                ) : null}
                {passwordManagementEnabled && passwordSessionActive ? (
                  <Suspense fallback={null}>
                    <TotpSettings settings={settings} disabled={busy} onSave={handleSave} />
                  </Suspense>
                ) : null}
              </SectionGroup>
            ) : null}

            <SectionGroup id="api-keys-settings" title="API keys & telemetry">
              <ApiKeysSection
                apiKeyAuthEnabled={settings.apiKeyAuthEnabled}
                hideUpstreamQuotaFromApiKeys={settings.hideUpstreamQuotaFromApiKeys}
                disabled={controlsDisabled}
                onApiKeyAuthEnabledChange={(enabled) =>
                  void handleSave({ apiKeyAuthEnabled: enabled })
                }
                onHideUpstreamQuotaFromApiKeysChange={(enabled) =>
                  void handleSave({ hideUpstreamQuotaFromApiKeys: enabled })
                }
||||||| 84fde5a1e
              ) : null}
              <ModelSourcesSettings disabled={controlsDisabled} />
              <FirewallSection disabled={controlsDisabled} />
              <QuotaPlannerSection disabled={controlsDisabled} />
              <StickySessionsSection disabled={controlsDisabled} />
              <DataRetentionSettings
                key={[
                  settings.requestLogRetentionOverrideDays,
                  settings.usageHistoryRetentionOverrideDays,
                  settings.requestLogRetentionDays,
                  settings.usageHistoryRetentionDays,
                ].join(":")}
                settings={settings}
                busy={controlsDisabled}
                onSave={handleSave}
=======
              ) : null}
              <ModelSourcesSettings disabled={controlsDisabled} />
              <ModelCatalogueSettings disabled={controlsDisabled} />
              <FirewallSection disabled={controlsDisabled || !canWriteSecurity} />
              <QuotaPlannerSection disabled={controlsDisabled} />
              {canWrite ? <StickySessionsSection disabled={controlsDisabled} /> : null}
              {/* Next to sticky sessions: both answer "which account served this, and what did it reuse?" */}
              {canWriteOps ? <CacheIsolationProbeSection disabled={controlsDisabled} /> : null}
              <DataRetentionSettings
                key={[
                  settings.requestLogRetentionOverrideDays,
                  settings.usageHistoryRetentionOverrideDays,
                  settings.requestLogRetentionDays,
                  settings.usageHistoryRetentionDays,
                  // R2 spool retention: a saved value (or a layer move back to
                  // inherited) must re-seed the card's draft.
                  settings.httpResponsesSessionBridgeOperationSpoolRetentionSeconds,
                  settings.provenance?.http_responses_session_bridge_operation_spool_retention_seconds?.source ?? "",
                ].join(":")}
                settings={settings}
                busy={controlsDisabled}
                onSave={handleSave}
              />
              {/* M5 conversation archive: next to Data retention (same "what we keep" family). */}
              <ConversationArchiveSettings settings={settings} busy={controlsDisabled} onSave={handleSave} />
              <UpstreamTimeoutSettings
                key={[
                  settings.version,
                  settings.upstreamConnectTimeoutSeconds,
                  settings.proxyRequestBudgetSeconds,
                  settings.compactRequestBudgetSeconds,
                  settings.transcriptionRequestBudgetSeconds,
                  settings.httpResponsesStreamRequestBudgetSeconds,
                  settings.httpResponsesSessionBridgeRequestBudgetSeconds,
                  settings.streamIdleTimeoutSeconds,
                  settings.proxyDownstreamWebsocketIdleTimeoutSeconds,
                  settings.sseKeepaliveIntervalSeconds,
                ].join(":")}
                settings={settings}
                busy={controlsDisabled}
                onSave={handleSave}
>>>>>>> 72630bbfe
              />
<<<<<<< 22625a07e
              <TelemetrySettings disabled={controlsDisabled} />
            </SectionGroup>

            <div id="advanced-settings" className="scroll-mt-24">
              <AdvancedSettingsGroup
                open={advancedOpen}
                onOpenChange={setAdvancedOpen}
                // Only an advanced deep link may drive the group's scroll. An
                // integration hash (e.g. `#claude-sidecar`) must not pull the
                // page back up after the nav's Advanced button opens the group.
                scrollToId={expandAdvanced ? advancedScrollToId : undefined}
                waitForQueryKeys={FIREWALL_LAYOUT_QUERY_KEYS}
              >
                <RoutingSettings
                  key={[
                    settings.openaiCacheAffinityMaxAgeSeconds,
                    settings.warmupModel,
                    settings.limitWarmupModel,
                    settings.limitWarmupPrompt,
                    settings.limitWarmupExhaustedThresholdPercent,
                    settings.limitWarmupIdleThresholdPercent,
                    settings.limitWarmupCooldownSeconds,
                    settings.limitWarmupStaggeredIdleEnabled,
                    settings.proxyAccountResponseCreateLimit,
                    settings.proxyAccountStreamLimit,
                    settings.proxyAccountStreamRecoveryReserve,
                    settings.proxyApiKeyFairShareCongestionThresholdPct,
                  ].join(":")}
                  settings={settings}
                  accounts={accountsQuery.data ?? []}
                  accountsLoading={accountsQuery.isLoading}
                  busy={controlsDisabled}
                  onSave={handleSave}
                />
                {upstreamProxyQuery.data ? (
                  <UpstreamProxySettings
                    admin={upstreamProxyQuery.data}
                    busy={controlsDisabled}
                    onSaveSettings={handleSave}
                    onCreateEndpoint={(payload) => createEndpointMutation.mutateAsync(payload)}
                    onTestEndpoint={(endpointId) => testEndpointMutation.mutateAsync(endpointId)}
                    onCreatePool={(payload) => createPoolMutation.mutateAsync(payload)}
                    onAddPoolMember={(poolId, payload) =>
                      addPoolMemberMutation.mutateAsync({ poolId, payload })
                    }
                  />
                ) : null}
                <ModelSourcesSettings disabled={controlsDisabled} />
                <FirewallSection disabled={controlsDisabled} />
                <QuotaPlannerSection disabled={controlsDisabled} />
                <StickySessionsSection disabled={controlsDisabled} />
                <DataRetentionSettings
                  key={[
                    settings.requestLogRetentionOverrideDays,
                    settings.usageHistoryRetentionOverrideDays,
                    settings.requestLogRetentionDays,
                    settings.usageHistoryRetentionDays,
                  ].join(":")}
                  settings={settings}
                  busy={controlsDisabled}
                  onSave={handleSave}
                />
              </AdvancedSettingsGroup>
            </div>
||||||| 84fde5a1e
            </AdvancedSettingsGroup>
=======
            </AdvancedSettingsGroup>

            {/* PR-2c-2: the second collapsed group, last on the page. It draws
                one line until a company install configures something, and its
                children (and their requests) only exist while it is open. */}
            <OrganisationSettingsGroup disabled={controlsDisabled} />
>>>>>>> 72630bbfe
          </div>

          <LoadingOverlay visible={!!settings && busy} label={t("settings.page.savingLabel")} />
        </div>
      )}
    </div>
  );
}
