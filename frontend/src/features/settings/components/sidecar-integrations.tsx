import { type ReactNode, useEffect, useState } from "react";
import { Boxes, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ClaudeSidecarSettings } from "@/features/settings/components/claude-sidecar-settings";
import { OllamaSidecarSettings } from "@/features/settings/components/ollama-sidecar-settings";
import { OmniRouteSidecarSettings } from "@/features/settings/components/omniroute-sidecar-settings";
import { OpenCodeGoSidecarSettings } from "@/features/settings/components/opencode-go-sidecar-settings";
import { NvidiaSidecarSettings } from "@/features/settings/components/nvidia-sidecar-settings";
import { OpenAICompatEndpointSettings } from "@/features/settings/components/openai-compat-endpoint-settings";
import { OpenRouterSidecarSettings } from "@/features/settings/components/openrouter-sidecar-settings";
import { OrcaRouterSidecarSettings } from "@/features/settings/components/orcarouter-sidecar-settings";
import { SettingsSection, SettingsSectionHeader } from "@/features/settings/components/settings-section";
import {
  DEFAULT_OPENAI_COMPAT_CONNECT_TIMEOUT_SECONDS,
  DEFAULT_OPENAI_COMPAT_MODELS_CACHE_TTL_SECONDS,
  DEFAULT_OPENAI_COMPAT_REQUEST_TIMEOUT_SECONDS,
  OPENAI_COMPAT_MAX_ENDPOINTS,
  openaiCompatIntegrationId,
  openaiCompatSectionId,
  storedOpenAICompatEndpointUpdates,
} from "@/features/settings/openai-compat-endpoints";
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

function isHttpUrl(value: string): boolean {
  try {
    const parsed = new URL(value);
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
}

export function SidecarIntegrationsCard({
  settings,
  busy,
  onSave,
  locationHash = "",
}: SidecarIntegrationsCardProps) {
  const openaiCompatEndpoints = settings.openaiCompatEndpoints ?? [];
  const atEndpointCap = openaiCompatEndpoints.length >= OPENAI_COMPAT_MAX_ENDPOINTS;
  const [addOpen, setAddOpen] = useState(false);
  const [addName, setAddName] = useState("");
  const [addBaseUrl, setAddBaseUrl] = useState("");
  const [addError, setAddError] = useState<string | null>(null);
  const [addPending, setAddPending] = useState(false);

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
      value: "nvidia",
      label: "NVIDIA",
      sectionId: "nvidia-sidecar",
      enabled: settings.nvidiaSidecarEnabled ?? false,
      render: () => <NvidiaSidecarSettings settings={settings} busy={busy} onSave={onSave} bare />,
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
    ...openaiCompatEndpoints.map((endpoint) => ({
      value: openaiCompatIntegrationId(endpoint.id),
      label: endpoint.name,
      sectionId: openaiCompatSectionId(endpoint.id),
      enabled: endpoint.enabled ?? false,
      render: () => (
        <OpenAICompatEndpointSettings
          endpoint={endpoint}
          settings={settings}
          busy={busy}
          onSave={onSave}
          onRemoved={() => setSelection({ tab: "claude", hash: locationHash })}
          bare
        />
      ),
    })),
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

  const closeAddDialog = () => {
    setAddOpen(false);
    setAddName("");
    setAddBaseUrl("");
    setAddError(null);
  };

  const handleAddEndpoint = async () => {
    const name = addName.trim();
    const baseUrl = addBaseUrl.trim().replace(/\/+$/, "");
    if (!name) {
      setAddError("Name is required.");
      return;
    }
    if (!baseUrl || !isHttpUrl(baseUrl)) {
      setAddError("Base URL must be an http(s) URL.");
      return;
    }
    const nameKey = name.toLowerCase();
    const duplicate = openaiCompatEndpoints.some(
      (endpoint) => endpoint.name.trim().toLowerCase() === nameKey,
    );
    if (duplicate) {
      setAddError("That name is already used.");
      return;
    }
    if (atEndpointCap) {
      setAddError(`Maximum ${OPENAI_COMPAT_MAX_ENDPOINTS} OpenAI-compat endpoints.`);
      return;
    }
    const id = crypto.randomUUID();
    setAddPending(true);
    setAddError(null);
    try {
      await onSave({
        openaiCompatEndpoints: [
          ...storedOpenAICompatEndpointUpdates(settings),
          {
            id,
            name,
            enabled: false,
            baseUrl,
            modelPrefixes: [],
            fullModels: [],
            connectTimeoutSeconds: DEFAULT_OPENAI_COMPAT_CONNECT_TIMEOUT_SECONDS,
            requestTimeoutSeconds: DEFAULT_OPENAI_COMPAT_REQUEST_TIMEOUT_SECONDS,
            modelsCacheTtlSeconds: DEFAULT_OPENAI_COMPAT_MODELS_CACHE_TTL_SECONDS,
            defaultReasoningEffort: null,
          },
        ],
      });
      closeAddDialog();
      setSelection({ tab: openaiCompatIntegrationId(id), hash: locationHash });
    } catch (error) {
      setAddError(error instanceof Error ? error.message : "Failed to add endpoint.");
    } finally {
      setAddPending(false);
    }
  };

  const enabledCount = tabs.filter((tab) => tab.enabled).length;

  return (
    <SettingsSection id="external-integrations" className="space-y-6">
      <SettingsSectionHeader
        icon={Boxes}
        title="External Integrations"
        description="Route model requests to external providers running alongside codex-lb."
        actions={
          <>
            <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-xs font-medium text-emerald-700 dark:text-emerald-300">
              {enabledCount} enabled
            </span>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-8 gap-1.5 text-xs"
              aria-label="Add OpenAI-compatible endpoint"
              title={
                atEndpointCap
                  ? `Maximum ${OPENAI_COMPAT_MAX_ENDPOINTS} OpenAI-compat endpoints`
                  : "Add OpenAI-compatible endpoint"
              }
              disabled={busy || atEndpointCap}
              onClick={() => {
                setAddError(null);
                setAddOpen(true);
              }}
            >
              <Plus className="h-3.5 w-3.5" aria-hidden="true" />
              Add endpoint
            </Button>
          </>
        }
      />

      <Tabs
        value={activeTab}
        onValueChange={(tab) => setSelection({ tab, hash: locationHash })}
        className="gap-5"
      >
        {/* Provider tiles wrap into rows, so every integration is one click away. */}
        <TabsList
          aria-label="Integration providers"
          className="grid h-auto w-full grid-cols-2 gap-2 rounded-none bg-transparent p-0 sm:grid-cols-3 lg:grid-cols-4"
        >
          {tabs.map((tab) => (
            <TabsTrigger
              key={tab.value}
              value={tab.value}
              aria-label={tab.enabled ? `${tab.label} (enabled)` : tab.label}
              className={cn(
                "h-auto min-w-0 flex-none justify-start gap-2.5 rounded-lg border bg-background/40 px-3 py-2.5 text-sm text-muted-foreground",
                "hover:border-border hover:bg-accent/70 hover:text-foreground",
                "data-[state=active]:border-primary/50 data-[state=active]:bg-primary/10 data-[state=active]:text-foreground data-[state=active]:shadow-none data-[state=active]:ring-1 data-[state=active]:ring-primary/30",
                "dark:data-[state=active]:border-primary/50 dark:data-[state=active]:bg-primary/10",
              )}
            >
              <span
                aria-hidden="true"
                className={cn(
                  "inline-block size-2 shrink-0 rounded-full ring-2",
                  tab.enabled ? "bg-emerald-500 ring-emerald-500/25" : "bg-muted-foreground/30 ring-transparent",
                )}
              />
              <span className="truncate">{tab.label}</span>
            </TabsTrigger>
          ))}
        </TabsList>
        {tabs.map((tab) => (
          <TabsContent key={tab.value} value={tab.value} className="min-w-0 border-t pt-5">
            {tab.render()}
          </TabsContent>
        ))}
      </Tabs>


      <Dialog open={addOpen} onOpenChange={(open) => (open ? setAddOpen(true) : closeAddDialog())}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add OpenAI-compatible endpoint</DialogTitle>
            <DialogDescription>
              Creates a named tab for any Chat Completions server. Vast.ai example:{" "}
              <code>https://openai.vast.ai/&lt;ENDPOINT_NAME&gt;/v1</code>.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="openai-compat-name">Name</Label>
              <Input
                id="openai-compat-name"
                value={addName}
                maxLength={64}
                placeholder="Vast"
                onChange={(event) => setAddName(event.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="openai-compat-base-url">Base URL</Label>
              <Input
                id="openai-compat-base-url"
                value={addBaseUrl}
                placeholder="https://openai.vast.ai/<ENDPOINT_NAME>/v1"
                onChange={(event) => setAddBaseUrl(event.target.value)}
              />
            </div>
            {addError ? <p className="text-xs text-destructive">{addError}</p> : null}
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={closeAddDialog} disabled={addPending}>
              Cancel
            </Button>
            <Button type="button" onClick={() => void handleAddEndpoint()} disabled={addPending || busy}>
              Add
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </SettingsSection>
  );
}
