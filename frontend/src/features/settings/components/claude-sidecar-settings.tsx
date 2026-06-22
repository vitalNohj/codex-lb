import { Bot } from "lucide-react";

import { SidecarIntegrationCard } from "@/features/settings/components/sidecar-integration-card";
import { useClaudeSidecar } from "@/features/settings/hooks/use-settings";
import type {
  DashboardSettings,
  SettingsUpdateRequest,
} from "@/features/settings/schemas";

export type ClaudeSidecarSettingsProps = {
  settings: DashboardSettings;
  busy: boolean;
  onSave: (payload: SettingsUpdateRequest) => Promise<void>;
  bare?: boolean;
};

const DEFAULT_BASE_URL = "http://127.0.0.1:8317";
const DEFAULT_PREFIXES = [
  { prefix: "claude", strip: false },
  { prefix: "cp-", strip: true },
  { prefix: "cp_", strip: true },
];
const DEFAULT_CONNECT_TIMEOUT_SECONDS = 8;
const DEFAULT_REQUEST_TIMEOUT_SECONDS = 600;
const DEFAULT_MODELS_CACHE_TTL_SECONDS = 60;
const DEFAULT_QUOTA_POLL_INTERVAL_SECONDS = 60;

export function ClaudeSidecarSettings({ settings, busy, onSave, bare = false }: ClaudeSidecarSettingsProps) {
  const { modelsQuery, testMutation } = useClaudeSidecar();

  return (
    <SidecarIntegrationCard.Provider
      settings={settings}
      busy={busy}
      meta={{
        id: "claude",
        title: "CLIProxyAPI Integration",
        conflictName: "CLIProxyAPI",
        description: "Configure CLIProxyAPI for Claude chat-completions routing.",
        icon: Bot,
        sectionId: "claude-sidecar",
        enableLabel: "Enable CLI Proxy integration",
        enableDescription: "When enabled, matching Claude model requests route to CLIProxyAPI.",
        callout: (
          <>
            Run CLIProxyAPI separately, log in with `cli-proxy-api --claude-login`, then point codex-lb at its
            local base URL.
          </>
        ),
        baseUrlPlaceholder: DEFAULT_BASE_URL,
        apiKeyPlaceholder: "Not configured",
        apiKeyConfigured: settings.claudeSidecarApiKeyConfigured ?? false,
        managementKeyConfigured: settings.claudeSidecarManagementKeyConfigured ?? false,
      }}
      initial={{
        enabled: settings.claudeSidecarEnabled ?? false,
        baseUrl: settings.claudeSidecarBaseUrl ?? DEFAULT_BASE_URL,
        prefixes: settings.claudeSidecarModelPrefixes ?? DEFAULT_PREFIXES,
        fullModels: settings.claudeSidecarFullModels ?? [],
        connectTimeout: settings.claudeSidecarConnectTimeoutSeconds ?? DEFAULT_CONNECT_TIMEOUT_SECONDS,
        requestTimeout: settings.claudeSidecarRequestTimeoutSeconds ?? DEFAULT_REQUEST_TIMEOUT_SECONDS,
        cacheTtl: settings.claudeSidecarModelsCacheTtlSeconds ?? DEFAULT_MODELS_CACHE_TTL_SECONDS,
        pollInterval: settings.claudeSidecarQuotaPollIntervalSeconds ?? DEFAULT_QUOTA_POLL_INTERVAL_SECONDS,
        defaultReasoningEffort: settings.claudeSidecarDefaultReasoningEffort ?? null,
      }}
      models={{ rows: modelsQuery.data?.models ?? [], isLoading: modelsQuery.isLoading }}
      onSave={onSave}
      onTestConnection={() => testMutation.mutateAsync()}
      buildEnablePatch={(enabled) => ({ claudeSidecarEnabled: enabled })}
      buildEffortPatch={(effort) => ({ claudeSidecarDefaultReasoningEffort: effort })}
      buildPatch={(state) => ({
        claudeSidecarBaseUrl: state.baseUrl,
        claudeSidecarModelPrefixes: state.prefixes,
        claudeSidecarFullModels: state.fullModels,
        claudeSidecarConnectTimeoutSeconds: state.connectTimeout,
        claudeSidecarRequestTimeoutSeconds: state.requestTimeout,
        claudeSidecarModelsCacheTtlSeconds: state.cacheTtl,
        claudeSidecarQuotaPollIntervalSeconds: state.pollInterval ?? DEFAULT_QUOTA_POLL_INTERVAL_SECONDS,
        ...(state.apiKey ? { claudeSidecarApiKey: state.apiKey } : {}),
        ...(state.managementKey ? { claudeSidecarManagementKey: state.managementKey } : {}),
      })}
    >
      <SidecarIntegrationCard.Frame bare={bare}>
        <SidecarIntegrationCard.Header />
        <SidecarIntegrationCard.Callout />
        <SidecarIntegrationCard.Fields>
          <SidecarIntegrationCard.BaseUrl />
          <SidecarIntegrationCard.Secrets showManagementKey />
          <SidecarIntegrationCard.Prefixes />
          <SidecarIntegrationCard.FullModels />
          <SidecarIntegrationCard.DiscoveredModels />
          <SidecarIntegrationCard.ReasoningEffort />
          <SidecarIntegrationCard.Timeouts showPollInterval />
          <SidecarIntegrationCard.Status />
        </SidecarIntegrationCard.Fields>
      </SidecarIntegrationCard.Frame>
    </SidecarIntegrationCard.Provider>
  );
}
