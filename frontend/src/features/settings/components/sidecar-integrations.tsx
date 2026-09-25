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
import { FreeModelDiscoveryPanel } from "@/features/settings/components/free-model-discovery-panel";
import { OllamaSidecarSettings } from "@/features/settings/components/ollama-sidecar-settings";
import { OmniRouteSidecarSettings } from "@/features/settings/components/omniroute-sidecar-settings";
import { OpenCodeGoSidecarSettings } from "@/features/settings/components/opencode-go-sidecar-settings";
import { OpenAICompatEndpointSettings } from "@/features/settings/components/openai-compat-endpoint-settings";
import { OpenRouterSidecarSettings } from "@/features/settings/components/openrouter-sidecar-settings";
import { OrcaRouterSidecarSettings } from "@/features/settings/components/orcarouter-sidecar-settings";
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
          <div className="flex min-w-0 items-center gap-1">
            <TabsList className="min-w-0 flex-1 justify-start overflow-x-auto">
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
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="size-8 shrink-0"
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
              <Plus className="h-4 w-4" aria-hidden="true" />
            </Button>
          </div>
          {tabs.map((tab) => (
            <TabsContent key={tab.value} value={tab.value} className="pt-2">
              {tab.render()}
            </TabsContent>
          ))}
        </Tabs>
      </div>

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
    </section>
  );
}
