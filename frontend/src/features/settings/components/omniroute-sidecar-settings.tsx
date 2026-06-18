import { Route } from "lucide-react";

import { SidecarIntegrationCard } from "@/features/settings/components/sidecar-integration-card";
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

export function OmniRouteSidecarSettings({ settings, busy, onSave }: OmniRouteSidecarSettingsProps) {
  const sidecarEnabled = settings.omnirouteSidecarEnabled ?? false;
  const sidecarApiKeyConfigured = settings.omnirouteSidecarApiKeyConfigured ?? false;
  const { modelsQuery, testMutation } = useOmniRouteSidecar({
    modelsEnabled: sidecarEnabled && sidecarApiKeyConfigured,
  });

  return (
    <SidecarIntegrationCard.Provider
      settings={settings}
      busy={busy}
      meta={{
        id: "omniroute",
        title: "OmniRoute Integration",
        conflictName: "OmniRoute",
        description: "Route exact model IDs and optional prefixes to OmniRoute.",
        icon: Route,
        sectionId: "omniroute-sidecar",
        enableLabel: "Enable OmniRoute Integration",
        enableDescription: "When enabled, matching model requests route to OmniRoute.",
        callout: (
          <>
            OmniRoute uses an OpenAI-compatible API key and handles its own cooling. Full model names route before
            prefixes and are forwarded unchanged.
          </>
        ),
        baseUrlPlaceholder: DEFAULT_BASE_URL,
        apiKeyPlaceholder: "OmniRoute API key",
        apiKeyConfigured: sidecarApiKeyConfigured,
        externalLink: { href: "/omni", label: "Open OmniRoute" },
      }}
      initial={{
        enabled: sidecarEnabled,
        baseUrl: settings.omnirouteSidecarBaseUrl ?? DEFAULT_BASE_URL,
        prefixes: settings.omnirouteSidecarModelPrefixes ?? [],
        fullModels: settings.omnirouteSidecarFullModels ?? settings.omnirouteSidecarSelectedModels ?? [],
        connectTimeout: settings.omnirouteSidecarConnectTimeoutSeconds ?? DEFAULT_CONNECT_TIMEOUT_SECONDS,
        requestTimeout: settings.omnirouteSidecarRequestTimeoutSeconds ?? DEFAULT_REQUEST_TIMEOUT_SECONDS,
        cacheTtl: settings.omnirouteSidecarModelsCacheTtlSeconds ?? DEFAULT_MODELS_CACHE_TTL_SECONDS,
      }}
      models={{ rows: modelsQuery.data?.models ?? [], isLoading: modelsQuery.isLoading }}
      onSave={onSave}
      onTestConnection={() => testMutation.mutateAsync()}
      buildEnablePatch={(enabled) => ({ omnirouteSidecarEnabled: enabled })}
      buildClearApiKeyPatch={() => ({ omnirouteSidecarClearApiKey: true })}
      buildPatch={(state) => ({
        omnirouteSidecarBaseUrl: state.baseUrl,
        omnirouteSidecarModelPrefixes: state.prefixes,
        omnirouteSidecarFullModels: state.fullModels,
        omnirouteSidecarSelectedModels: state.fullModels,
        omnirouteSidecarConnectTimeoutSeconds: state.connectTimeout,
        omnirouteSidecarRequestTimeoutSeconds: state.requestTimeout,
        omnirouteSidecarModelsCacheTtlSeconds: state.cacheTtl,
        ...(state.apiKey ? { omnirouteSidecarApiKey: state.apiKey } : {}),
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
          <SidecarIntegrationCard.Actions />
        </SidecarIntegrationCard.Fields>
      </SidecarIntegrationCard.Frame>
    </SidecarIntegrationCard.Provider>
  );
}
