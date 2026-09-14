import { Rocket } from "lucide-react";

import { AlertMessage } from "@/components/alert-message";
import { OpenCodeGoModelsBrowser } from "@/features/settings/components/opencode-go-models-browser";
import { SidecarIntegrationCard } from "@/features/settings/components/sidecar-integration-card";
import { useOpenCodeGoSidecar } from "@/features/settings/hooks/use-settings";
import type { DashboardSettings, SettingsUpdateRequest } from "@/features/settings/schemas";

export type OpenCodeGoSidecarSettingsProps = {
  settings: DashboardSettings;
  busy: boolean;
  onSave: (patch: Partial<SettingsUpdateRequest>) => Promise<DashboardSettings | void>;
  bare?: boolean;
};

const DEFAULT_BASE_URL = "https://opencode.ai/zen/go/v1";
const DEFAULT_CONNECT_TIMEOUT_SECONDS = 8;
const DEFAULT_REQUEST_TIMEOUT_SECONDS = 600;
const DEFAULT_MODELS_CACHE_TTL_SECONDS = 60;

export function OpenCodeGoSidecarSettings({
  settings,
  busy,
  onSave,
  bare = false,
}: OpenCodeGoSidecarSettingsProps) {
  const sidecarEnabled = settings.opencodeGoSidecarEnabled ?? false;
  const sidecarApiKeyConfigured = settings.opencodeGoSidecarApiKeyConfigured ?? false;
  const { statusQuery, modelsQuery, testMutation } = useOpenCodeGoSidecar({
    modelsEnabled: sidecarEnabled && sidecarApiKeyConfigured,
  });

  const status = statusQuery.data;
  const models = modelsQuery.data?.models ?? [];

  return (
    <SidecarIntegrationCard.Provider
      settings={settings}
      busy={busy}
      meta={{
        id: "opencodeGo",
        title: "OpenCode Go Integration",
        conflictName: "OpenCode Go",
        description: "Route OpenCode Go subscription models through codex-lb.",
        icon: Rocket,
        sectionId: "opencode-go-sidecar",
        enableLabel: "Enable OpenCode Go Integration",
        enableDescription:
          "When enabled, matching model requests route to your OpenCode Go subscription.",
        callout: (
          <>
            Subscribe to Go and copy your API key from the{" "}
            <a
              href="https://opencode.ai/auth"
              target="_blank"
              rel="noopener noreferrer"
              className="font-medium underline underline-offset-2"
            >
              OpenCode console
            </a>
            . Seeded prefix <code>opencode-go/</code> is stripped before forwarding, so{" "}
            <code>opencode-go/kimi-k3</code> reaches the provider as <code>kimi-k3</code>. Go is a
            separate base path from OpenCode Zen; a Go key on a Zen URL bills Zen credits instead.
          </>
        ),
        baseUrlPlaceholder: DEFAULT_BASE_URL,
        apiKeyPlaceholder: "OpenCode Go API key",
        apiKeyConfigured: sidecarApiKeyConfigured,
        clearApiKeyDescription:
          "The stored OpenCode Go key is deleted immediately. Model discovery and routing fail until a new key is added. The key is never displayed, so it cannot be recovered from this page.",
        externalLink: { href: "https://opencode.ai/docs/go", label: "OpenCode Go docs" },
      }}
      initial={{
        enabled: sidecarEnabled,
        baseUrl: settings.opencodeGoSidecarBaseUrl ?? DEFAULT_BASE_URL,
        prefixes: settings.opencodeGoSidecarModelPrefixes ?? [],
        fullModels: settings.opencodeGoSidecarFullModels ?? [],
        connectTimeout:
          settings.opencodeGoSidecarConnectTimeoutSeconds ?? DEFAULT_CONNECT_TIMEOUT_SECONDS,
        requestTimeout:
          settings.opencodeGoSidecarRequestTimeoutSeconds ?? DEFAULT_REQUEST_TIMEOUT_SECONDS,
        cacheTtl: settings.opencodeGoSidecarModelsCacheTtlSeconds ?? DEFAULT_MODELS_CACHE_TTL_SECONDS,
        defaultReasoningEffort: settings.opencodeGoSidecarDefaultReasoningEffort ?? null,
      }}
      models={{
        rows: models,
        isLoading: modelsQuery.isLoading,
        render: ({ selectedModels, isLoading, onAddModel }) => (
          <OpenCodeGoModelsBrowser
            models={models}
            selectedModels={selectedModels}
            isLoading={isLoading}
            configured={sidecarApiKeyConfigured}
            onAddModel={onAddModel}
          />
        ),
      }}
      onSave={onSave}
      onTestConnection={() => testMutation.mutateAsync()}
      buildEnablePatch={(enabled) => ({ opencodeGoSidecarEnabled: enabled })}
      buildClearApiKeyPatch={() => ({ opencodeGoSidecarClearApiKey: true })}
      buildEffortPatch={(effort) => ({ opencodeGoSidecarDefaultReasoningEffort: effort })}
      buildPatch={(state) => ({
        opencodeGoSidecarBaseUrl: state.baseUrl,
        opencodeGoSidecarModelPrefixes: state.prefixes,
        opencodeGoSidecarFullModels: state.fullModels,
        opencodeGoSidecarConnectTimeoutSeconds: state.connectTimeout,
        opencodeGoSidecarRequestTimeoutSeconds: state.requestTimeout,
        opencodeGoSidecarModelsCacheTtlSeconds: state.cacheTtl,
        // An empty key field means "unchanged". Clearing is a separate,
        // confirmed action so an ordinary save can never wipe a stored key.
        ...(state.apiKey ? { opencodeGoSidecarApiKey: state.apiKey } : {}),
      })}
    >
      <SidecarIntegrationCard.Frame bare={bare}>
        <SidecarIntegrationCard.Header />
        <SidecarIntegrationCard.Callout />
        <OpenCodeGoConnectionStatus
          enabled={sidecarEnabled}
          configured={sidecarApiKeyConfigured}
          isLoading={statusQuery.isLoading}
          isError={statusQuery.isError}
          status={status?.status ?? null}
          message={status?.message ?? null}
        />
        <SidecarIntegrationCard.Fields>
          <SidecarIntegrationCard.BaseUrl />
          <SidecarIntegrationCard.Secrets />
          <SidecarIntegrationCard.ClearApiKey />
          <SidecarIntegrationCard.Prefixes />
          <SidecarIntegrationCard.FullModels />
          <SidecarIntegrationCard.DiscoveredModels />
          <SidecarIntegrationCard.ReasoningEffort />
          <SidecarIntegrationCard.Timeouts />
          <OpenCodeGoBalanceNote />
          <SidecarIntegrationCard.Status />
        </SidecarIntegrationCard.Fields>
      </SidecarIntegrationCard.Frame>
    </SidecarIntegrationCard.Provider>
  );
}

type OpenCodeGoConnectionStatusProps = {
  enabled: boolean;
  configured: boolean;
  isLoading: boolean;
  isError: boolean;
  status: string | null;
  message: string | null;
};

/**
 * Honest connection state for the integration.
 *
 * Every state the backend can report is designed explicitly: not configured,
 * still loading, unreachable status endpoint, provider auth failure, and
 * healthy. A key that has never been tested is not claimed to be working.
 */
function OpenCodeGoConnectionStatus({
  enabled,
  configured,
  isLoading,
  isError,
  status,
  message,
}: OpenCodeGoConnectionStatusProps) {
  if (!configured) {
    return (
      <AlertMessage variant="warning">
        No API key stored. Add a key to test the connection and discover models. The integration
        stays off until you enable it deliberately.
      </AlertMessage>
    );
  }
  if (isLoading) {
    return (
      <p className="text-xs text-muted-foreground" role="status">
        Checking OpenCode Go connection...
      </p>
    );
  }
  if (isError) {
    return (
      <AlertMessage variant="error">
        Could not read the OpenCode Go connection status from codex-lb. Routing state is unknown.
      </AlertMessage>
    );
  }
  if (status === "unauthorized") {
    return (
      <AlertMessage variant="error">
        OpenCode Go rejected the stored key{message ? ` (${message})` : ""}. Replace the key, or
        remove it if the subscription ended.
      </AlertMessage>
    );
  }
  if (status === "unreachable" || status === "error") {
    return (
      <AlertMessage variant="error">
        {message ?? "codex-lb could not reach OpenCode Go."}
      </AlertMessage>
    );
  }
  if (status === "healthy") {
    return (
      <AlertMessage variant="success">
        {enabled
          ? (message ?? "OpenCode Go reachable.")
          : `${message ?? "OpenCode Go reachable"} - the integration is still disabled, so nothing routes yet.`}
      </AlertMessage>
    );
  }
  return (
    <p className="text-xs text-muted-foreground" role="status">
      Connection not tested yet. Saving a key runs a test automatically.
    </p>
  );
}

/**
 * Explains the provider-side "Use balance" setting.
 *
 * codex-lb cannot read or change that setting - it lives in the OpenCode
 * console - so this is deliberately a description and a link, not a toggle we
 * cannot honour.
 */
function OpenCodeGoBalanceNote() {
  return (
    <div className="space-y-1 rounded-md border bg-muted/10 p-3">
      <p className="text-sm font-medium">Spending beyond the Go limits</p>
      <p className="text-xs text-muted-foreground">
        OpenCode Go limits are per-model dollar caps (5-hour, weekly, and monthly). If the{" "}
        <strong>Use balance</strong> option is enabled in the{" "}
        <a
          href="https://opencode.ai/auth"
          target="_blank"
          rel="noopener noreferrer"
          className="font-medium underline underline-offset-2"
        >
          OpenCode console
        </a>
        , requests past those caps fall back to your Zen credit balance instead of being refused.
        That setting belongs to OpenCode, not codex-lb: this page cannot read it or change it.
      </p>
    </div>
  );
}
