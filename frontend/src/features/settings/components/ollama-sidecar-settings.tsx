import { Cloud } from "lucide-react";

import { SidecarIntegrationCard } from "@/features/settings/components/sidecar-integration-card";
import { useOllamaSidecar } from "@/features/settings/hooks/use-settings";
import type { DashboardSettings, SettingsUpdateRequest } from "@/features/settings/schemas";

export type OllamaSidecarSettingsProps = {
  settings: DashboardSettings;
  busy: boolean;
  onSave: (payload: SettingsUpdateRequest) => Promise<void>;
  bare?: boolean;
};

const DEFAULT_BASE_URL = "https://ollama.com";
const DEFAULT_CONNECT_TIMEOUT_SECONDS = 8;
const DEFAULT_REQUEST_TIMEOUT_SECONDS = 600;
const DEFAULT_MODELS_CACHE_TTL_SECONDS = 60;

export function OllamaSidecarSettings({ settings, busy, onSave, bare = false }: OllamaSidecarSettingsProps) {
  const sidecarEnabled = settings.ollamaSidecarEnabled ?? false;
  const sidecarApiKeyConfigured = settings.ollamaSidecarApiKeyConfigured ?? false;
  const { modelsQuery, testMutation } = useOllamaSidecar({
    modelsEnabled: sidecarEnabled && sidecarApiKeyConfigured,
  });

  return (
    <SidecarIntegrationCard.Provider
      settings={settings}
      busy={busy}
      meta={{
        id: "ollama",
        title: "Ollama Integration",
        conflictName: "Ollama",
        description: "Route configured Ollama Cloud models through codex-lb.",
        icon: Cloud,
        sectionId: "ollama-sidecar",
        enableLabel: "Enable Ollama Integration",
        enableDescription: "When enabled, matching model requests route to Ollama Cloud.",
        callout: (
          <>
            Create an API key at{" "}
            <a
              href="https://ollama.com/settings/keys"
              target="_blank"
              rel="noopener noreferrer"
              className="font-medium underline underline-offset-2"
            >
              https://ollama.com/settings/keys
            </a>
            , then configure prefixes or full cloud model IDs.
          </>
        ),
        baseUrlPlaceholder: DEFAULT_BASE_URL,
        apiKeyPlaceholder: "Ollama API key",
        apiKeyConfigured: sidecarApiKeyConfigured,
      }}
      initial={{
        enabled: sidecarEnabled,
        baseUrl: settings.ollamaSidecarBaseUrl ?? DEFAULT_BASE_URL,
        prefixes: settings.ollamaSidecarModelPrefixes ?? [],
        fullModels: settings.ollamaSidecarFullModels ?? [],
        connectTimeout: settings.ollamaSidecarConnectTimeoutSeconds ?? DEFAULT_CONNECT_TIMEOUT_SECONDS,
        requestTimeout: settings.ollamaSidecarRequestTimeoutSeconds ?? DEFAULT_REQUEST_TIMEOUT_SECONDS,
        cacheTtl: settings.ollamaSidecarModelsCacheTtlSeconds ?? DEFAULT_MODELS_CACHE_TTL_SECONDS,
        defaultReasoningEffort: settings.ollamaSidecarDefaultReasoningEffort ?? null,
      }}
      models={{ rows: modelsQuery.data?.models ?? [], isLoading: modelsQuery.isLoading }}
      onSave={onSave}
      onTestConnection={() => testMutation.mutateAsync()}
      buildEnablePatch={(enabled) => ({ ollamaSidecarEnabled: enabled })}
      buildEffortPatch={(effort) => ({ ollamaSidecarDefaultReasoningEffort: effort })}
      buildPatch={(state) => ({
        ollamaSidecarBaseUrl: state.baseUrl,
        ollamaSidecarModelPrefixes: state.prefixes,
        ollamaSidecarFullModels: state.fullModels,
        ollamaSidecarConnectTimeoutSeconds: state.connectTimeout,
        ollamaSidecarRequestTimeoutSeconds: state.requestTimeout,
        ollamaSidecarModelsCacheTtlSeconds: state.cacheTtl,
        ...(state.apiKey ? { ollamaSidecarApiKey: state.apiKey } : {}),
      })}
    >
      <SidecarIntegrationCard.Frame bare={bare}>
        <SidecarIntegrationCard.Header />
        <SidecarIntegrationCard.Callout />
        <SidecarIntegrationCard.Fields>
          <SidecarIntegrationCard.BaseUrl />
          <SidecarIntegrationCard.Secrets />
          <SidecarIntegrationCard.Prefixes />
          <SidecarIntegrationCard.FullModels />
          <SidecarIntegrationCard.DiscoveredModels />
          <SidecarIntegrationCard.ReasoningEffort />
          <SidecarIntegrationCard.Timeouts />
          <SidecarIntegrationCard.Status />
        </SidecarIntegrationCard.Fields>
      </SidecarIntegrationCard.Frame>
    </SidecarIntegrationCard.Provider>
  );
}
