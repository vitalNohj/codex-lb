import { useMemo, useState } from "react";
import { ExternalLink, Route } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { buildSettingsUpdateRequest } from "@/features/settings/payload";
import { OmniRouteModelBrowser } from "@/features/settings/components/omniroute-model-browser";
import { useOmniRouteSidecar } from "@/features/settings/hooks/use-settings";
import type { DashboardSettings, SettingsUpdateRequest } from "@/features/settings/schemas";

export type OmniRouteSidecarSettingsProps = {
  settings: DashboardSettings;
  busy: boolean;
  onSave: (payload: SettingsUpdateRequest) => Promise<void>;
};

const DEFAULT_BASE_URL = "http://127.0.0.1:20128/v1";
const DEFAULT_CONNECT_TIMEOUT_SECONDS = 8;
const DEFAULT_REQUEST_TIMEOUT_SECONDS = 600;
const DEFAULT_MODELS_CACHE_TTL_SECONDS = 60;

function normalizeModelIds(models: string[]): string[] {
  return Array.from(new Set(models.map((model) => model.trim()).filter(Boolean)));
}

export function OmniRouteSidecarSettings({ settings, busy, onSave }: OmniRouteSidecarSettingsProps) {
  const sidecarEnabled = settings.omnirouteSidecarEnabled ?? false;
  const sidecarBaseUrl = settings.omnirouteSidecarBaseUrl ?? DEFAULT_BASE_URL;
  const sidecarApiKeyConfigured = settings.omnirouteSidecarApiKeyConfigured ?? false;
  const sidecarSelectedModels = settings.omnirouteSidecarSelectedModels ?? [];
  const sidecarConnectTimeout = settings.omnirouteSidecarConnectTimeoutSeconds ?? DEFAULT_CONNECT_TIMEOUT_SECONDS;
  const sidecarRequestTimeout = settings.omnirouteSidecarRequestTimeoutSeconds ?? DEFAULT_REQUEST_TIMEOUT_SECONDS;
  const sidecarCacheTtl = settings.omnirouteSidecarModelsCacheTtlSeconds ?? DEFAULT_MODELS_CACHE_TTL_SECONDS;
  const { modelsQuery, testMutation } = useOmniRouteSidecar({
    modelsEnabled: sidecarEnabled && sidecarApiKeyConfigured,
  });
  const [baseUrl, setBaseUrl] = useState(sidecarBaseUrl);
  const [apiKey, setApiKey] = useState("");
  const [selectedModels, setSelectedModels] = useState(sidecarSelectedModels);
  const [manualModelId, setManualModelId] = useState("");
  const [connectTimeout, setConnectTimeout] = useState(String(sidecarConnectTimeout));
  const [requestTimeout, setRequestTimeout] = useState(String(sidecarRequestTimeout));
  const [cacheTtl, setCacheTtl] = useState(String(sidecarCacheTtl));

  const parsedConnectTimeout = Number(connectTimeout);
  const parsedRequestTimeout = Number(requestTimeout);
  const parsedCacheTtl = Number(cacheTtl);
  const normalizedSelectedModels = useMemo(() => normalizeModelIds(selectedModels), [selectedModels]);
  const formValid =
    baseUrl.trim().length > 0 &&
    Number.isFinite(parsedConnectTimeout) &&
    parsedConnectTimeout > 0 &&
    Number.isFinite(parsedRequestTimeout) &&
    parsedRequestTimeout > 0 &&
    Number.isFinite(parsedCacheTtl) &&
    parsedCacheTtl >= 0;
  const modelRows = modelsQuery.data?.models ?? [];

  const save = (patch: Partial<SettingsUpdateRequest>) => onSave(buildSettingsUpdateRequest(settings, patch));

  const saveConfig = async () => {
    const payload: Partial<SettingsUpdateRequest> = {
      omnirouteSidecarBaseUrl: baseUrl.trim(),
      omnirouteSidecarSelectedModels: normalizedSelectedModels,
      omnirouteSidecarConnectTimeoutSeconds: parsedConnectTimeout,
      omnirouteSidecarRequestTimeoutSeconds: parsedRequestTimeout,
      omnirouteSidecarModelsCacheTtlSeconds: parsedCacheTtl,
    };
    if (apiKey.trim()) {
      payload.omnirouteSidecarApiKey = apiKey.trim();
    }
    await save(payload);
    setApiKey("");
    await testMutation.mutateAsync().catch(() => null);
  };

  const addModel = (modelId: string) => {
    setSelectedModels((current) => normalizeModelIds([...current, modelId]));
  };

  const removeModel = (modelId: string) => {
    setSelectedModels((current) => current.filter((candidate) => candidate !== modelId));
  };

  const addManualModel = () => {
    const modelId = manualModelId.trim();
    if (!modelId) {
      return;
    }
    addModel(modelId);
    setManualModelId("");
  };

  return (
    <section id="omniroute-sidecar" className="rounded-xl border bg-card p-5">
      <div className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10">
              <Route className="h-4 w-4 text-primary" aria-hidden="true" />
            </div>
            <div>
              <h3 className="text-sm font-semibold">OmniRoute Integration</h3>
              <p className="text-xs text-muted-foreground">Route exact model IDs to OmniRoute.</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button asChild type="button" size="sm" variant="outline" className="h-8 gap-1.5 text-xs">
              <a href="/omni" target="_blank" rel="noopener noreferrer">
                Open OmniRoute
                <ExternalLink className="size-3" aria-hidden="true" />
              </a>
            </Button>
          </div>
        </div>

        <div className="flex items-center justify-between gap-4 rounded-lg border p-3">
          <div>
            <p className="text-sm font-medium">Enable OmniRoute Integration</p>
            <p className="text-xs text-muted-foreground">
              When enabled, selected model IDs route to OmniRoute after Claude and OpenRouter checks.
            </p>
          </div>
          <Switch
            aria-label="Enable OmniRoute Integration"
            checked={sidecarEnabled}
            disabled={busy}
            onCheckedChange={(checked) => void save({ omnirouteSidecarEnabled: checked })}
          />
        </div>

        <div className="rounded-lg border bg-muted/20 p-3 text-xs text-muted-foreground">
          OmniRoute uses an OpenAI-compatible API key and handles its own cooling. Add exact model IDs below;
          codex-lb only routes requests whose effective model exactly matches one of those IDs.
        </div>

        <div className="rounded-lg border">
          <div className="space-y-3 p-3">
            <label className="space-y-1 text-xs font-medium" htmlFor="omniroute-sidecar-base-url">
              Base URL
              <Input
                id="omniroute-sidecar-base-url"
                value={baseUrl}
                onChange={(event) => setBaseUrl(event.target.value)}
                placeholder={DEFAULT_BASE_URL}
                disabled={busy}
                className="h-8 text-xs"
              />
            </label>

            <div className="grid gap-2 sm:grid-cols-2">
              <label className="space-y-1 text-xs font-medium" htmlFor="omniroute-sidecar-api-key">
                API key
                <Input
                  id="omniroute-sidecar-api-key"
                  type="password"
                  value={apiKey}
                  onChange={(event) => setApiKey(event.target.value)}
                  placeholder={sidecarApiKeyConfigured ? "Configured" : "OmniRoute API key"}
                  disabled={busy}
                  className="h-8 text-xs"
                />
                <span className="block font-normal text-muted-foreground">
                  Saved keys are encrypted and never shown again.
                </span>
              </label>
              <label className="space-y-1 text-xs font-medium" htmlFor="omniroute-manual-model">
                Add model ID manually
                <div className="flex gap-2">
                  <Input
                    id="omniroute-manual-model"
                    value={manualModelId}
                    onChange={(event) => setManualModelId(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        event.preventDefault();
                        addManualModel();
                      }
                    }}
                    placeholder="provider/model-id"
                    disabled={busy}
                    className="h-8 text-xs"
                  />
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-8 text-xs"
                    disabled={busy || !manualModelId.trim()}
                    onClick={addManualModel}
                  >
                    Add
                  </Button>
                </div>
                <span className="block font-normal text-muted-foreground">
                  Use exact IDs. Prefixes are intentionally not supported.
                </span>
              </label>
            </div>

            <OmniRouteModelBrowser
              models={modelRows}
              selectedModels={normalizedSelectedModels}
              isLoading={modelsQuery.isLoading}
              onAddModel={addModel}
              onRemoveModel={removeModel}
            />

            <div className="grid gap-2 sm:grid-cols-3">
              <label className="space-y-1 text-xs font-medium" htmlFor="omniroute-sidecar-connect-timeout">
                Connect timeout (s)
                <Input
                  id="omniroute-sidecar-connect-timeout"
                  type="number"
                  value={connectTimeout}
                  onChange={(event) => setConnectTimeout(event.target.value)}
                  disabled={busy}
                  className="h-8 text-xs"
                />
              </label>
              <label className="space-y-1 text-xs font-medium" htmlFor="omniroute-sidecar-request-timeout">
                Request timeout (s)
                <Input
                  id="omniroute-sidecar-request-timeout"
                  type="number"
                  value={requestTimeout}
                  onChange={(event) => setRequestTimeout(event.target.value)}
                  disabled={busy}
                  className="h-8 text-xs"
                />
              </label>
              <label className="space-y-1 text-xs font-medium" htmlFor="omniroute-sidecar-cache-ttl">
                Model cache TTL (s)
                <Input
                  id="omniroute-sidecar-cache-ttl"
                  type="number"
                  value={cacheTtl}
                  onChange={(event) => setCacheTtl(event.target.value)}
                  disabled={busy}
                  className="h-8 text-xs"
                />
              </label>
            </div>

            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                size="sm"
                className="h-8 text-xs"
                disabled={busy || !formValid || testMutation.isPending}
                onClick={() => void saveConfig()}
              >
                Save
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="h-8 text-xs"
                disabled={busy || !sidecarApiKeyConfigured}
                onClick={() => void save({ omnirouteSidecarClearApiKey: true })}
              >
                Clear API key
              </Button>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
