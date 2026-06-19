import { Globe } from "lucide-react";

import { SidecarIntegrationCard } from "@/features/settings/components/sidecar-integration-card";
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

export function OpenRouterSidecarSettings({ settings, busy, onSave }: OpenRouterSidecarSettingsProps) {
  const sidecarEnabled = settings.openrouterSidecarEnabled ?? false;
  const sidecarApiKeyConfigured = settings.openrouterSidecarApiKeyConfigured ?? false;
  const { modelsQuery, testMutation } = useOpenRouterSidecar({
    modelsEnabled: sidecarEnabled && sidecarApiKeyConfigured,
  });

  return (
    <SidecarIntegrationCard.Provider
      settings={settings}
      busy={busy}
      meta={{
        id: "openrouter",
        title: "OpenRouter Integration",
        conflictName: "OpenRouter",
        description: "Route configured OpenRouter models through codex-lb.",
        icon: Globe,
        sectionId: "openrouter-sidecar",
        enableLabel: "Enable OpenRouter Integration",
        enableDescription: "When enabled, matching model requests route to OpenRouter.",
        callout: (
          <>
            Create an API key at https://openrouter.ai/settings/keys, then configure prefixes or full model IDs.
          </>
        ),
        baseUrlPlaceholder: DEFAULT_BASE_URL,
        apiKeyPlaceholder: "OpenRouter API key",
        apiKeyConfigured: sidecarApiKeyConfigured,
      }}
      initial={{
        enabled: sidecarEnabled,
        baseUrl: settings.openrouterSidecarBaseUrl ?? DEFAULT_BASE_URL,
        prefixes: settings.openrouterSidecarModelPrefixes ?? [],
        fullModels: settings.openrouterSidecarFullModels ?? [],
        connectTimeout: settings.openrouterSidecarConnectTimeoutSeconds ?? DEFAULT_CONNECT_TIMEOUT_SECONDS,
        requestTimeout: settings.openrouterSidecarRequestTimeoutSeconds ?? DEFAULT_REQUEST_TIMEOUT_SECONDS,
        cacheTtl: settings.openrouterSidecarModelsCacheTtlSeconds ?? DEFAULT_MODELS_CACHE_TTL_SECONDS,
      }}
      models={{ rows: modelsQuery.data?.models ?? [], isLoading: modelsQuery.isLoading }}
      onSave={onSave}
      onTestConnection={() => testMutation.mutateAsync()}
      buildEnablePatch={(enabled) => ({ openrouterSidecarEnabled: enabled })}
      buildPatch={(state) => ({
        openrouterSidecarBaseUrl: state.baseUrl,
        openrouterSidecarModelPrefixes: state.prefixes,
        openrouterSidecarFullModels: state.fullModels,
        openrouterSidecarConnectTimeoutSeconds: state.connectTimeout,
        openrouterSidecarRequestTimeoutSeconds: state.requestTimeout,
        openrouterSidecarModelsCacheTtlSeconds: state.cacheTtl,
        ...(state.apiKey ? { openrouterSidecarApiKey: state.apiKey } : {}),
      })}
    >
      <SidecarIntegrationCard.Frame>
        <SidecarIntegrationCard.Header />
        <SidecarIntegrationCard.EnableToggle />
        <SidecarIntegrationCard.Callout />
        <SidecarIntegrationCard.Fields>
          <SidecarIntegrationCard.BaseUrl />
          <SidecarIntegrationCard.Secrets />
          <SidecarIntegrationCard.Prefixes />
          <SidecarIntegrationCard.FullModels />
          <SidecarIntegrationCard.DiscoveredModels />
          <SidecarIntegrationCard.Timeouts />
          <SidecarIntegrationCard.Status />
        </SidecarIntegrationCard.Fields>
      </SidecarIntegrationCard.Frame>
    </SidecarIntegrationCard.Provider>
  );
}
