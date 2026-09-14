import { type ReactNode, useEffect, useState } from "react";
import { Boxes } from "lucide-react";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ClaudeSidecarSettings } from "@/features/settings/components/claude-sidecar-settings";
import { FreeModelDiscoveryPanel } from "@/features/settings/components/free-model-discovery-panel";
import { OllamaSidecarSettings } from "@/features/settings/components/ollama-sidecar-settings";
import { OmniRouteSidecarSettings } from "@/features/settings/components/omniroute-sidecar-settings";
import { OpenCodeGoSidecarSettings } from "@/features/settings/components/opencode-go-sidecar-settings";
import { OpenRouterSidecarSettings } from "@/features/settings/components/openrouter-sidecar-settings";
import { OrcaRouterSidecarSettings } from "@/features/settings/components/orcarouter-sidecar-settings";
import type { DashboardSettings, SettingsUpdateRequest } from "@/features/settings/schemas";
import { OMNIROUTE_ENABLED } from "@/lib/product-capabilities";
import { cn } from "@/lib/utils";

export type SidecarIntegrationsCardProps = {
  settings: DashboardSettings;
  busy: boolean;
  onSave: (patch: Partial<SettingsUpdateRequest>) => Promise<DashboardSettings | void>;
  /**
   * Location hash from the owning page, e.g. `#opencode-go-sidecar`.
   *
   * Supplied by the page rather than read from router context here, so this
   * card stays usable outside a Router.
   */
  locationHash?: string;
};

type IntegrationTab = {
  value: string;
  label: string;
  /** Anchor id this integration's card renders, used for deep links. */
  sectionId: string;
  enabled: boolean;
  render: () => ReactNode;
};

/**
 * Resolves a `/settings#<section-id>` hash to the tab that owns it.
 *
 * Inactive tab panels are unmounted, so an integration's anchor does not exist
 * in the DOM until its tab is selected. Without this, the Accounts page's
 * "Configure" link lands on the Settings page with nothing revealed.
 */
function tabValueForHash(hash: string, tabs: IntegrationTab[]): string | null {
  const sectionId = hash.replace(/^#/, "");
  if (!sectionId) {
    return null;
  }
  return tabs.find((tab) => tab.sectionId === sectionId)?.value ?? null;
}

export function SidecarIntegrationsCard({
  settings,
  busy,
  onSave,
  locationHash = "",
}: SidecarIntegrationsCardProps) {
  const tabs: IntegrationTab[] = [
    {
      value: "claude",
      label: "CLIProxyAPI",
      sectionId: "claude-sidecar",
      enabled: settings.claudeSidecarEnabled ?? false,
      render: () => <ClaudeSidecarSettings settings={settings} busy={busy} onSave={onSave} bare />,
    },
    {
      value: "openrouter",
      label: "OpenRouter",
      sectionId: "openrouter-sidecar",
      enabled: settings.openrouterSidecarEnabled ?? false,
      render: () => <OpenRouterSidecarSettings settings={settings} busy={busy} onSave={onSave} bare />,
    },
    {
      value: "orcarouter",
      label: "OrcaRouter",
      sectionId: "orcarouter-sidecar",
      enabled: settings.orcarouterSidecarEnabled ?? false,
      render: () => <OrcaRouterSidecarSettings settings={settings} busy={busy} onSave={onSave} bare />,
    },
    ...(OMNIROUTE_ENABLED
      ? [
          {
            value: "omniroute",
            label: "OmniRoute",
            sectionId: "omniroute-sidecar",
            enabled: settings.omnirouteSidecarEnabled ?? false,
            render: () => <OmniRouteSidecarSettings settings={settings} busy={busy} onSave={onSave} bare />,
          },
        ]
      : []),
    {
      value: "ollama",
      label: "Ollama",
      sectionId: "ollama-sidecar",
      enabled: settings.ollamaSidecarEnabled ?? false,
      render: () => <OllamaSidecarSettings settings={settings} busy={busy} onSave={onSave} bare />,
    },
    {
      value: "opencode-go",
      label: "OpenCode Go",
      sectionId: "opencode-go-sidecar",
      enabled: settings.opencodeGoSidecarEnabled ?? false,
      render: () => <OpenCodeGoSidecarSettings settings={settings} busy={busy} onSave={onSave} bare />,
    },
  ];

  const hashTab = tabValueForHash(locationHash, tabs);
  // A manual click wins, but only until the hash changes again - otherwise
  // clicking a tab would permanently deafen the page to later Configure links.
  // Recording the hash the click happened under keeps this derived, with no
  // state-syncing effect.
  const [selection, setSelection] = useState<{ tab: string; hash: string } | null>(null);
  const activeTab =
    (selection?.hash === locationHash ? selection.tab : null) ??
    hashTab ??
    (tabs.find((tab) => tab.enabled) ?? tabs[0]).value;

  // The anchor only exists once its panel is mounted, so scroll after selection
  // rather than relying on the browser's initial hash jump.
  useEffect(() => {
    if (!hashTab) {
      return;
    }
    const frame = window.requestAnimationFrame(() => {
      document.getElementById(hashTab === activeTab ? locationHash.replace(/^#/, "") : "")
        ?.scrollIntoView({ block: "start" });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [activeTab, locationHash, hashTab]);

  return (
    <section id="external-integrations" className="rounded-xl border bg-card p-5">
      <div className="space-y-4">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10">
            <Boxes className="h-4 w-4 text-primary" aria-hidden="true" />
          </div>
          <div>
            <h2 className="text-sm font-semibold">External Integrations</h2>
            <p className="text-xs text-muted-foreground">
              Route model requests to external providers running alongside codex-lb.
            </p>
          </div>
        </div>

        <FreeModelDiscoveryPanel settings={settings} />

        <Tabs
          value={activeTab}
          onValueChange={(tab) => setSelection({ tab, hash: locationHash })}
        >
          {/*
            Tab labels never wrap, so past a handful of integrations the row is
            wider than a phone viewport. Scrolling the row keeps every label
            readable and stops the card from forcing a horizontal page scroll.
          */}
          <TabsList className="w-full justify-start overflow-x-auto">
            {tabs.map((tab) => (
              <TabsTrigger
                key={tab.value}
                value={tab.value}
                aria-label={tab.enabled ? `${tab.label} (enabled)` : tab.label}
              >
                {tab.label}
                <span
                  aria-hidden="true"
                  className={cn(
                    "ml-1 inline-block size-1.5 rounded-full",
                    tab.enabled ? "bg-emerald-500" : "bg-transparent",
                  )}
                />
              </TabsTrigger>
            ))}
          </TabsList>
          {tabs.map((tab) => (
            <TabsContent key={tab.value} value={tab.value} className="pt-2">
              {tab.render()}
            </TabsContent>
          ))}
        </Tabs>
      </div>
    </section>
  );
}
