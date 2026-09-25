import { Suspense, lazy, useEffect, useState, type ReactNode } from "react";
import {
  Activity,
  Boxes,
  KeySquare,
  Palette,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { useLocation } from "react-router-dom";

import { AlertMessage } from "@/components/alert-message";
import { LoadingOverlay } from "@/components/layout/loading-overlay";
import { ApiKeysSection } from "@/features/api-keys/components/api-keys-section";
import { useAccounts } from "@/features/accounts/hooks/use-accounts";
import { FirewallSection } from "@/features/firewall/components/firewall-section";
import { ModelSourcesSettings } from "@/features/model-sources/components/model-sources-settings";
import { QuotaPlannerSection } from "@/features/quota-planner/components/quota-planner-section";
import { shouldExpandAdvancedSettings } from "@/features/settings/advanced-settings-deeplink";
import { AdvancedSettingsGroup } from "@/features/settings/components/advanced-settings-group";
import { AppearanceSettings } from "@/features/settings/components/appearance-settings";
import { DataRetentionSettings } from "@/features/settings/components/data-retention-settings";
import { FreeModelDiscoveryPanel } from "@/features/settings/components/free-model-discovery-panel";
import { SidecarIntegrationsCard } from "@/features/settings/components/sidecar-integrations";
import { GuestAccessSettings } from "@/features/settings/components/guest-access-settings";
import { ImportSettings } from "@/features/settings/components/import-settings";
import { PasswordSettings } from "@/features/settings/components/password-settings";
import { ResetCreditSettings } from "@/features/settings/components/reset-credit-settings";
import { RoutingSettings } from "@/features/settings/components/routing-settings";
import { SessionSettings } from "@/features/settings/components/session-settings";
import { SettingsSkeleton } from "@/features/settings/components/settings-skeleton";
import { TelemetrySettings } from "@/features/settings/components/telemetry-settings";
import { UpstreamProxySettings } from "@/features/settings/components/upstream-proxy-settings";
import { StickySessionsSection } from "@/features/sticky-sessions/components/sticky-sessions-section";
import { useAuthStore } from "@/features/auth/hooks/use-auth";
import { useSettings, useUpstreamProxyAdmin } from "@/features/settings/hooks/use-settings";
import type { SettingsUpdateRequest } from "@/features/settings/schemas";
import { getErrorMessageOrNull } from "@/utils/errors";

const TotpSettings = lazy(() =>
  import("@/features/settings/components/totp-settings").then((m) => ({ default: m.TotpSettings })),
);

const FIREWALL_LAYOUT_QUERY_KEYS = [
  ["accounts", "list"],
  ["settings", "upstream-proxy"],
  ["model-sources", "list"],
] as const;

type SectionNavItem = {
  id: string;
  label: string;
  icon: LucideIcon;
};

const SECTION_NAV: SectionNavItem[] = [
  { id: "external-integrations-group", label: "Integrations", icon: Boxes },
  { id: "appearance-settings", label: "Appearance", icon: Palette },
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
  const { accountsQuery } = useAccounts();
  const {
    upstreamProxyQuery,
    createEndpointMutation,
    createPoolMutation,
    addPoolMemberMutation,
    testEndpointMutation,
  } = useUpstreamProxyAdmin();
  const authMode = useAuthStore((state) => state.authMode);
  const passwordManagementEnabled = useAuthStore((state) => state.passwordManagementEnabled);
  const passwordSessionActive = useAuthStore((state) => state.passwordSessionActive);
  const canWrite = useAuthStore((state) => state.canWrite);

  const settings = settingsQuery.data;
  const busy =
    updateSettingsMutation.isPending ||
    createEndpointMutation.isPending ||
    createPoolMutation.isPending ||
    addPoolMemberMutation.isPending ||
    testEndpointMutation.isPending;
  const controlsDisabled = busy || !canWrite;
  const error =
    getErrorMessageOrNull(settingsQuery.error) ||
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

      {!settings ? (
        <SettingsSkeleton />
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

            <SectionGroup id="external-integrations-group" title="Integrations">
              <SidecarIntegrationsCard
                settings={settings}
                busy={busy}
                onSave={handleSave}
                locationHash={location.hash}
              />
              <FreeModelDiscoveryPanel settings={settings} />
            </SectionGroup>

            <SectionGroup id="appearance-settings" title="Appearance">
              <AppearanceSettings />
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
                />
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
              />
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
          </div>

          <LoadingOverlay visible={!!settings && busy} label={t("settings.page.savingLabel")} />
        </div>
      )}
    </div>
  );
}
