import { useMemo, useState } from "react";
import { Bot } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { buildSettingsUpdateRequest } from "@/features/settings/payload";
import { useClaudeSidecar } from "@/features/settings/hooks/use-settings";
import type { DashboardSettings, SettingsUpdateRequest } from "@/features/settings/schemas";
import { formatDateTimeInline, formatSlug } from "@/utils/formatters";

export type ClaudeSidecarSettingsProps = {
  settings: DashboardSettings;
  busy: boolean;
  onSave: (payload: SettingsUpdateRequest) => Promise<void>;
};

const DEFAULT_BASE_URL = "http://127.0.0.1:8317";
const DEFAULT_PREFIXES = ["claude"];
const DEFAULT_CONNECT_TIMEOUT_SECONDS = 8;
const DEFAULT_REQUEST_TIMEOUT_SECONDS = 600;
const DEFAULT_MODELS_CACHE_TTL_SECONDS = 60;

function parsePrefixes(value: string): string[] {
  return Array.from(new Set(value.split(",").map((part) => part.trim().toLowerCase()).filter(Boolean)));
}

export function ClaudeSidecarSettings({ settings, busy, onSave }: ClaudeSidecarSettingsProps) {
  const { statusQuery, modelsQuery, testMutation } = useClaudeSidecar();
  const sidecarEnabled = settings.claudeSidecarEnabled ?? false;
  const sidecarBaseUrl = settings.claudeSidecarBaseUrl ?? DEFAULT_BASE_URL;
  const sidecarApiKeyConfigured = settings.claudeSidecarApiKeyConfigured ?? false;
  const sidecarPrefixes = settings.claudeSidecarModelPrefixes ?? DEFAULT_PREFIXES;
  const sidecarConnectTimeout = settings.claudeSidecarConnectTimeoutSeconds ?? DEFAULT_CONNECT_TIMEOUT_SECONDS;
  const sidecarRequestTimeout = settings.claudeSidecarRequestTimeoutSeconds ?? DEFAULT_REQUEST_TIMEOUT_SECONDS;
  const sidecarCacheTtl = settings.claudeSidecarModelsCacheTtlSeconds ?? DEFAULT_MODELS_CACHE_TTL_SECONDS;
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
    parsedPrefixes.length > 0 &&
    Number.isFinite(parsedConnectTimeout) &&
    parsedConnectTimeout > 0 &&
    Number.isFinite(parsedRequestTimeout) &&
    parsedRequestTimeout > 0 &&
    Number.isFinite(parsedCacheTtl) &&
    parsedCacheTtl >= 0;
  const currentStatus = statusQuery.data?.status ?? settings.claudeSidecarLastHealthStatus ?? "disabled";
  const currentMessage = statusQuery.data?.message ?? settings.claudeSidecarLastHealthMessage;
  const lastChecked = statusQuery.data?.lastCheckedAt ?? settings.claudeSidecarLastCheckedAt;
  const modelCount = statusQuery.data?.modelCount ?? settings.claudeSidecarLastModelCount;
  const modelRows = modelsQuery.data?.models ?? [];

  const save = (patch: Partial<SettingsUpdateRequest>) =>
    onSave(buildSettingsUpdateRequest(settings, patch));
  const saveConfig = async () => {
    const payload: Partial<SettingsUpdateRequest> = {
      claudeSidecarBaseUrl: baseUrl.trim(),
      claudeSidecarModelPrefixes: parsedPrefixes,
      claudeSidecarConnectTimeoutSeconds: parsedConnectTimeout,
      claudeSidecarRequestTimeoutSeconds: parsedRequestTimeout,
      claudeSidecarModelsCacheTtlSeconds: parsedCacheTtl,
    };
    if (apiKey.trim()) {
      payload.claudeSidecarApiKey = apiKey.trim();
    }
    await save(payload);
    setApiKey("");
  };

  return (
    <section id="claude-sidecar" className="rounded-xl border bg-card p-5">
      <div className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10">
              <Bot className="h-4 w-4 text-primary" aria-hidden="true" />
            </div>
            <div>
              <h3 className="text-sm font-semibold">Claude Sidecar</h3>
              <p className="text-xs text-muted-foreground">Configure CLIProxyAPI for Claude chat-completions routing.</p>
            </div>
          </div>
          <Badge variant="outline">{formatSlug(currentStatus)}</Badge>
        </div>

        <div className="rounded-lg border bg-muted/20 p-3 text-xs text-muted-foreground">
          Run CLIProxyAPI separately, log in with `cli-proxy-api --claude-login`, then point codex-lb at its local base URL.
          Cursor should use a Claude custom model ID that starts with one of the configured prefixes.
        </div>

        <div className="divide-y rounded-lg border">
          <div className="flex items-center justify-between gap-4 p-3">
            <div>
              <p className="text-sm font-medium">Enable Claude sidecar</p>
              <p className="text-xs text-muted-foreground">When enabled, matching Claude model requests route to CLIProxyAPI.</p>
            </div>
            <Switch
              aria-label="Enable Claude sidecar"
              checked={sidecarEnabled}
              disabled={busy}
              onCheckedChange={(checked) => void save({ claudeSidecarEnabled: checked })}
            />
          </div>

          <div className="space-y-3 p-3">
            <div className="grid gap-2 sm:grid-cols-[1fr_14rem]">
              <label className="space-y-1 text-xs font-medium" htmlFor="claude-sidecar-base-url">
                Base URL
                <Input id="claude-sidecar-base-url" value={baseUrl} disabled={busy} onChange={(event) => setBaseUrl(event.target.value)} placeholder="http://127.0.0.1:8317" className="h-8 text-xs" />
                <span className="block font-normal text-muted-foreground">Example: http://127.0.0.1:8317</span>
              </label>
              <label className="space-y-1 text-xs font-medium" htmlFor="claude-sidecar-api-key">
                API key
                <Input id="claude-sidecar-api-key" value={apiKey} disabled={busy} type="password" onChange={(event) => setApiKey(event.target.value)} placeholder={sidecarApiKeyConfigured ? "Configured" : "Not configured"} className="h-8 text-xs" />
                <span className="block font-normal text-muted-foreground">Saved keys are encrypted and never shown again.</span>
              </label>
            </div>
            <label className="space-y-1 text-xs font-medium" htmlFor="claude-sidecar-prefixes">
              Model prefixes
              <Input id="claude-sidecar-prefixes" value={prefixes} disabled={busy} onChange={(event) => setPrefixes(event.target.value)} placeholder="claude" className="h-8 text-xs" />
              <span className="block font-normal text-muted-foreground">Comma-separated prefixes, for example: claude, anthropic</span>
            </label>
            <div className="grid gap-2 sm:grid-cols-3">
              <label className="space-y-1 text-xs font-medium" htmlFor="claude-sidecar-connect-timeout">
                Connect timeout
                <Input id="claude-sidecar-connect-timeout" type="number" min={0.1} step={0.1} value={connectTimeout} disabled={busy} onChange={(event) => setConnectTimeout(event.target.value)} className="h-8 text-xs" />
              </label>
              <label className="space-y-1 text-xs font-medium" htmlFor="claude-sidecar-request-timeout">
                Request timeout
                <Input id="claude-sidecar-request-timeout" type="number" min={1} step={1} value={requestTimeout} disabled={busy} onChange={(event) => setRequestTimeout(event.target.value)} className="h-8 text-xs" />
              </label>
              <label className="space-y-1 text-xs font-medium" htmlFor="claude-sidecar-cache-ttl">
                Model cache TTL
                <Input id="claude-sidecar-cache-ttl" type="number" min={0} step={1} value={cacheTtl} disabled={busy} onChange={(event) => setCacheTtl(event.target.value)} className="h-8 text-xs" />
              </label>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button type="button" size="sm" className="h-8 text-xs" disabled={busy || !formValid} onClick={() => void saveConfig()}>
                Save sidecar
              </Button>
              <Button type="button" size="sm" variant="outline" className="h-8 text-xs" disabled={busy || testMutation.isPending} onClick={() => testMutation.mutate()}>
                Test connection
              </Button>
              <Button type="button" size="sm" variant="outline" className="h-8 text-xs" disabled={busy || !sidecarApiKeyConfigured} onClick={() => void save({ claudeSidecarClearApiKey: true })}>
                Clear API key
              </Button>
            </div>
          </div>
        </div>

        <div className="grid gap-3 rounded-lg border bg-muted/20 p-3 text-xs sm:grid-cols-3">
          <div><span className="text-muted-foreground">Configured:</span> {sidecarApiKeyConfigured ? "yes" : "no"}</div>
          <div><span className="text-muted-foreground">Models:</span> {modelCount ?? "--"}</div>
          <div><span className="text-muted-foreground">Last check:</span> {lastChecked ? formatDateTimeInline(lastChecked) : "never"}</div>
        </div>
        {currentMessage ? <p className="text-xs text-muted-foreground">{currentMessage}</p> : null}
        {modelRows.length > 0 ? (
          <div className="space-y-2">
            <p className="text-xs font-medium">Discovered models</p>
            <div className="flex flex-wrap gap-1.5">
              {modelRows.map((model) => <Badge key={model.id} variant="secondary" className="font-mono text-[11px]">{model.id}</Badge>)}
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
}
