import { useMemo, useState } from "react";
import { Globe, Plus } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { buildSettingsUpdateRequest } from "@/features/settings/payload";
import { OpenRouterModelBrowser } from "@/features/settings/components/openrouter-model-browser";
import {
  POPULAR_OPENROUTER_MODELS,
  prefixFromModelId,
} from "@/features/settings/components/openrouter-popular-models";
import { useOpenRouterSidecar } from "@/features/settings/hooks/use-settings";
import type { DashboardSettings, SettingsUpdateRequest } from "@/features/settings/schemas";

export type OpenRouterSidecarSettingsProps = {
  settings: DashboardSettings;
  busy: boolean;
  onSave: (payload: SettingsUpdateRequest) => Promise<void>;
};

const DEFAULT_BASE_URL = "https://openrouter.ai/api/v1";
const DEFAULT_CONNECT_TIMEOUT_SECONDS = 8;
const DEFAULT_REQUEST_TIMEOUT_SECONDS = 600;
const DEFAULT_MODELS_CACHE_TTL_SECONDS = 60;

function parsePrefixes(value: string): string[] {
  return Array.from(new Set(value.split(",").map((part) => part.trim().toLowerCase()).filter(Boolean)));
}

export function OpenRouterSidecarSettings({ settings, busy, onSave }: OpenRouterSidecarSettingsProps) {
  const sidecarEnabled = settings.openrouterSidecarEnabled ?? false;
  const sidecarBaseUrl = settings.openrouterSidecarBaseUrl ?? DEFAULT_BASE_URL;
  const sidecarApiKeyConfigured = settings.openrouterSidecarApiKeyConfigured ?? false;
  const { modelsQuery, testMutation } = useOpenRouterSidecar({
    modelsEnabled: sidecarEnabled && sidecarApiKeyConfigured,
  });
  const sidecarPrefixes = settings.openrouterSidecarModelPrefixes ?? [];
  const sidecarConnectTimeout = settings.openrouterSidecarConnectTimeoutSeconds ?? DEFAULT_CONNECT_TIMEOUT_SECONDS;
  const sidecarRequestTimeout = settings.openrouterSidecarRequestTimeoutSeconds ?? DEFAULT_REQUEST_TIMEOUT_SECONDS;
  const sidecarCacheTtl = settings.openrouterSidecarModelsCacheTtlSeconds ?? DEFAULT_MODELS_CACHE_TTL_SECONDS;
  const [baseUrl, setBaseUrl] = useState(sidecarBaseUrl);
  const [apiKey, setApiKey] = useState("");
  const [prefixes, setPrefixes] = useState(sidecarPrefixes.join(", "));
  const [connectTimeout, setConnectTimeout] = useState(String(sidecarConnectTimeout));
  const [requestTimeout, setRequestTimeout] = useState(String(sidecarRequestTimeout));
  const [cacheTtl, setCacheTtl] = useState(String(sidecarCacheTtl));

  const parsedPrefixes = useMemo(() => parsePrefixes(prefixes), [prefixes]);
  const parsedConnectTimeout = Number(connectTimeout);
  const parsedRequestTimeout = Number(requestTimeout);
  const parsedCacheTtl = Number(cacheTtl);
  const formValid =
    baseUrl.trim().length > 0 &&
    Number.isFinite(parsedConnectTimeout) &&
    parsedConnectTimeout > 0 &&
    Number.isFinite(parsedRequestTimeout) &&
    parsedRequestTimeout > 0 &&
    Number.isFinite(parsedCacheTtl) &&
    parsedCacheTtl >= 0;
  const modelRows = modelsQuery.data?.models ?? [];

  const save = (patch: Partial<SettingsUpdateRequest>) =>
    onSave(buildSettingsUpdateRequest(settings, patch));

  const saveConfig = async () => {
    const payload: Partial<SettingsUpdateRequest> = {
      openrouterSidecarBaseUrl: baseUrl.trim(),
      openrouterSidecarModelPrefixes: parsedPrefixes,
      openrouterSidecarConnectTimeoutSeconds: parsedConnectTimeout,
      openrouterSidecarRequestTimeoutSeconds: parsedRequestTimeout,
      openrouterSidecarModelsCacheTtlSeconds: parsedCacheTtl,
    };
    if (apiKey.trim()) {
      payload.openrouterSidecarApiKey = apiKey.trim();
    }
    await save(payload);
    setApiKey("");
  };

  const addPrefix = (prefix: string) => {
    const next = parsePrefixes(`${prefixes}, ${prefix}`);
    setPrefixes(next.join(", "));
  };

  const discoveredIds = useMemo(() => new Set(modelRows.map((model) => model.id)), [modelRows]);

  return (
    <section id="openrouter-sidecar" className="rounded-xl border bg-card p-5">
      <div className="space-y-3">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10">
            <Globe className="h-4 w-4 text-primary" aria-hidden="true" />
          </div>
          <div>
            <h3 className="text-sm font-semibold">OpenRouter Integration</h3>
            <p className="text-xs text-muted-foreground">Route configured OpenRouter models through codex-lb.</p>
          </div>
        </div>

        <div className="flex items-center justify-between gap-4 rounded-lg border p-3">
          <div>
            <p className="text-sm font-medium">Enable OpenRouter Integration</p>
            <p className="text-xs text-muted-foreground">
              When enabled, matching model requests route to OpenRouter.
            </p>
          </div>
          <Switch
            aria-label="Enable OpenRouter Integration"
            checked={sidecarEnabled}
            disabled={busy}
            onCheckedChange={(checked) => void save({ openrouterSidecarEnabled: checked })}
          />
        </div>

        <div className="rounded-lg border bg-muted/20 p-3 text-xs text-muted-foreground">
          Create an API key at https://openrouter.ai/settings/keys, then configure provider prefixes such as{" "}
          <code className="rounded bg-muted px-1">deepseek/</code> so OpenRouter models do not overlap native Codex{" "}
          <code className="rounded bg-muted px-1">gpt-*</code> models.
        </div>

        <div className="rounded-lg border">
          <div className="space-y-3 p-3">
            <label className="space-y-1 text-xs font-medium" htmlFor="openrouter-sidecar-base-url">
              Base URL
              <Input
                id="openrouter-sidecar-base-url"
                value={baseUrl}
                onChange={(event) => setBaseUrl(event.target.value)}
                placeholder={DEFAULT_BASE_URL}
                disabled={busy}
                className="h-8 text-xs"
              />
            </label>

            <div className="grid gap-2 sm:grid-cols-2">
              <label className="space-y-1 text-xs font-medium" htmlFor="openrouter-sidecar-api-key">
                API key
                <Input
                  id="openrouter-sidecar-api-key"
                  type="password"
                  value={apiKey}
                  onChange={(event) => setApiKey(event.target.value)}
                  placeholder={sidecarApiKeyConfigured ? "Configured" : "OpenRouter API key"}
                  disabled={busy}
                  className="h-8 text-xs"
                />
                <span className="block font-normal text-muted-foreground">
                  Saved keys are encrypted and never shown again.
                </span>
              </label>
              <label className="space-y-1 text-xs font-medium" htmlFor="openrouter-sidecar-prefixes">
                Model prefixes
                <Input
                  id="openrouter-sidecar-prefixes"
                  value={prefixes}
                  onChange={(event) => setPrefixes(event.target.value)}
                  placeholder="deepseek/, google/, meta-llama/"
                  disabled={busy}
                  className="h-8 text-xs"
                />
                <span className="block font-normal text-muted-foreground">
                  Comma-separated provider prefixes, e.g. deepseek/, google/
                </span>
              </label>
            </div>

            <div className="grid gap-2 sm:grid-cols-3">
              <label className="space-y-1 text-xs font-medium" htmlFor="openrouter-sidecar-connect-timeout">
                Connect timeout (s)
                <Input
                  id="openrouter-sidecar-connect-timeout"
                  type="number"
                  value={connectTimeout}
                  onChange={(event) => setConnectTimeout(event.target.value)}
                  disabled={busy}
                  className="h-8 text-xs"
                />
              </label>
              <label className="space-y-1 text-xs font-medium" htmlFor="openrouter-sidecar-request-timeout">
                Request timeout (s)
                <Input
                  id="openrouter-sidecar-request-timeout"
                  type="number"
                  value={requestTimeout}
                  onChange={(event) => setRequestTimeout(event.target.value)}
                  disabled={busy}
                  className="h-8 text-xs"
                />
              </label>
              <label className="space-y-1 text-xs font-medium" htmlFor="openrouter-sidecar-cache-ttl">
                Model cache TTL (s)
                <Input
                  id="openrouter-sidecar-cache-ttl"
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
                disabled={busy || !formValid}
                onClick={() => void saveConfig()}
              >
                Save
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="h-8 text-xs"
                disabled={busy || testMutation.isPending}
                onClick={() => void testMutation.mutateAsync()}
              >
                Test connection
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="h-8 text-xs"
                disabled={busy || !sidecarApiKeyConfigured}
                onClick={() => void save({ openrouterSidecarClearApiKey: true })}
              >
                Clear API key
              </Button>
            </div>
          </div>
        </div>

        <div className="space-y-2">
          <p className="text-xs font-medium">Popular models</p>
          {modelRows.length === 0 ? (
            <p className="text-xs text-muted-foreground">
              Save API key and test connection to verify availability
            </p>
          ) : null}
          <div className="flex flex-wrap gap-1.5">
            {POPULAR_OPENROUTER_MODELS.filter(
              (id) => modelRows.length === 0 || discoveredIds.has(id),
            ).map((id) => (
              <Badge key={id} variant="secondary" className="gap-1 font-mono text-[11px]">
                {id}
                <button
                  type="button"
                  className="ml-0.5 hover:text-foreground"
                  aria-label={`Add prefix ${prefixFromModelId(id)}`}
                  disabled={busy}
                  onClick={() => addPrefix(prefixFromModelId(id))}
                >
                  <Plus className="size-3" aria-hidden="true" />
                </button>
              </Badge>
            ))}
          </div>
        </div>

        <OpenRouterModelBrowser models={modelRows} isLoading={modelsQuery.isLoading} onAddPrefix={addPrefix} />
      </div>
    </section>
  );
}
