import { useMemo, useState } from "react";
import { Globe } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { buildSettingsUpdateRequest } from "@/features/settings/payload";
import { useOpenRouterSidecar } from "@/features/settings/hooks/use-settings";
import type { DashboardSettings, SettingsUpdateRequest } from "@/features/settings/schemas";
import { formatDateTimeInline, formatSlug } from "@/utils/formatters";

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
  const { statusQuery, modelsQuery, testMutation } = useOpenRouterSidecar();
  const sidecarEnabled = settings.openrouterSidecarEnabled ?? false;
  const sidecarBaseUrl = settings.openrouterSidecarBaseUrl ?? DEFAULT_BASE_URL;
  const sidecarApiKeyConfigured = settings.openrouterSidecarApiKeyConfigured ?? false;
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
  const currentStatus = statusQuery.data?.status ?? settings.openrouterSidecarLastHealthStatus ?? "disabled";
  const currentMessage = statusQuery.data?.message ?? settings.openrouterSidecarLastHealthMessage;
  const lastChecked = statusQuery.data?.lastCheckedAt ?? settings.openrouterSidecarLastCheckedAt;
  const modelCount = statusQuery.data?.modelCount ?? settings.openrouterSidecarLastModelCount;
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

  return (
    <section id="openrouter-sidecar" className="rounded-xl border bg-card p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-base font-semibold">
            <Globe className="h-4 w-4 text-primary" aria-hidden="true" />
            OpenRouter sidecar
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Route configured OpenRouter models through codex-lb. Use explicit prefixes such as{" "}
            <code className="rounded bg-muted px-1">deepseek/</code> to avoid overlapping native Codex models.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">Enabled</span>
          <Switch
            checked={sidecarEnabled}
            disabled={busy}
            onCheckedChange={(checked) => void save({ openrouterSidecarEnabled: checked })}
          />
        </div>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <label className="space-y-1 text-sm">
          <span className="text-xs font-medium text-muted-foreground">Base URL</span>
          <Input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} disabled={busy} />
        </label>
        <label className="space-y-1 text-sm">
          <span className="text-xs font-medium text-muted-foreground">API key</span>
          <Input
            type="password"
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
            placeholder={sidecarApiKeyConfigured ? "Configured — enter to replace" : "OpenRouter API key"}
            disabled={busy}
          />
        </label>
        <label className="space-y-1 text-sm sm:col-span-2">
          <span className="text-xs font-medium text-muted-foreground">Model prefixes (comma-separated)</span>
          <Input
            value={prefixes}
            onChange={(event) => setPrefixes(event.target.value)}
            placeholder="deepseek/, google/, meta-llama/"
            disabled={busy}
          />
        </label>
        <label className="space-y-1 text-sm">
          <span className="text-xs font-medium text-muted-foreground">Connect timeout (s)</span>
          <Input value={connectTimeout} onChange={(event) => setConnectTimeout(event.target.value)} disabled={busy} />
        </label>
        <label className="space-y-1 text-sm">
          <span className="text-xs font-medium text-muted-foreground">Request timeout (s)</span>
          <Input value={requestTimeout} onChange={(event) => setRequestTimeout(event.target.value)} disabled={busy} />
        </label>
        <label className="space-y-1 text-sm">
          <span className="text-xs font-medium text-muted-foreground">Models cache TTL (s)</span>
          <Input value={cacheTtl} onChange={(event) => setCacheTtl(event.target.value)} disabled={busy} />
        </label>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <Button type="button" size="sm" disabled={busy || !formValid} onClick={() => void saveConfig()}>
          Save OpenRouter settings
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={busy || testMutation.isPending}
          onClick={() => void testMutation.mutateAsync()}
        >
          Test connection
        </Button>
        {sidecarApiKeyConfigured ? (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            disabled={busy}
            onClick={() => void save({ openrouterSidecarClearApiKey: true })}
          >
            Clear API key
          </Button>
        ) : null}
      </div>

      <div className="mt-4 grid gap-2 rounded-lg border bg-muted/20 p-3 text-sm sm:grid-cols-2">
        <div>
          <div className="text-xs text-muted-foreground">Health</div>
          <div className="font-medium">{formatSlug(currentStatus)}</div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground">Models</div>
          <div className="font-medium">{modelCount ?? "--"}</div>
        </div>
        <div className="sm:col-span-2">
          <div className="text-xs text-muted-foreground">Last check</div>
          <div className="font-medium">{lastChecked ? formatDateTimeInline(lastChecked) : "Never"}</div>
        </div>
        {currentMessage ? (
          <div className="sm:col-span-2 text-xs text-muted-foreground">{currentMessage}</div>
        ) : null}
      </div>

      {modelRows.length > 0 ? (
        <div className="mt-4 space-y-2">
          <div className="text-xs font-medium uppercase tracking-wider text-muted-foreground">Cached models</div>
          <div className="flex flex-wrap gap-2">
            {modelRows.slice(0, 12).map((model) => (
              <Badge key={model.id} variant="outline" className="font-mono text-[11px]">
                {model.id}
              </Badge>
            ))}
            {modelRows.length > 12 ? (
              <Badge variant="secondary" className="text-[11px]">
                +{modelRows.length - 12} more
              </Badge>
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  );
}
