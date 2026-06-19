import { type ReactNode, useState } from "react";
import { Boxes } from "lucide-react";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ClaudeSidecarSettings } from "@/features/settings/components/claude-sidecar-settings";
import { OmniRouteSidecarSettings } from "@/features/settings/components/omniroute-sidecar-settings";
import { OpenRouterSidecarSettings } from "@/features/settings/components/openrouter-sidecar-settings";
import type { DashboardSettings, SettingsUpdateRequest } from "@/features/settings/schemas";
import { cn } from "@/lib/utils";

export type SidecarIntegrationsCardProps = {
  settings: DashboardSettings;
  busy: boolean;
  onSave: (payload: SettingsUpdateRequest) => Promise<void>;
};

type IntegrationTab = {
  value: string;
  label: string;
  enabled: boolean;
  render: () => ReactNode;
};

export function SidecarIntegrationsCard({ settings, busy, onSave }: SidecarIntegrationsCardProps) {
  const tabs: IntegrationTab[] = [
    {
      value: "claude",
      label: "CLIProxyAPI",
      enabled: settings.claudeSidecarEnabled ?? false,
      render: () => <ClaudeSidecarSettings settings={settings} busy={busy} onSave={onSave} bare />,
    },
    {
      value: "openrouter",
      label: "OpenRouter",
      enabled: settings.openrouterSidecarEnabled ?? false,
      render: () => <OpenRouterSidecarSettings settings={settings} busy={busy} onSave={onSave} bare />,
    },
    {
      value: "omniroute",
      label: "OmniRoute",
      enabled: settings.omnirouteSidecarEnabled ?? false,
      render: () => <OmniRouteSidecarSettings settings={settings} busy={busy} onSave={onSave} bare />,
    },
  ];

  const [activeTab] = useState(() => (tabs.find((tab) => tab.enabled) ?? tabs[0]).value);

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

        <Tabs defaultValue={activeTab}>
          <TabsList className="w-full">
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
