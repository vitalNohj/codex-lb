import { Globe } from "lucide-react";

import * as SidecarIntegrationCard from "@/features/settings/components/sidecar-integration-card";
import { useNvidiaSidecar } from "@/features/settings/hooks/use-settings";
import type { DashboardSettings, SettingsUpdateRequest } from "@/features/settings/schemas";

export type NvidiaSidecarSettingsProps = {
  settings: DashboardSettings;
  busy: boolean;
  onSave: (patch: Partial<SettingsUpdateRequest>) => Promise<DashboardSettings | void>;
  bare?: boolean;
};

const DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1";
const DEFAULT_CONNECT_TIMEOUT_SECONDS = 8;
const DEFAULT_REQUEST_TIMEOUT_SECONDS = 600;
const DEFAULT_MODELS_CACHE_TTL_SECONDS = 60;

export function NvidiaSidecarSettings({ settings, busy, onSave, bare = false }: NvidiaSidecarSettingsProps) {
  const sidecarEnabled = settings.nvidiaSidecarEnabled ?? false;
  const sidecarApiKeyConfigured = settings.nvidiaSidecarApiKeyConfigured ?? false;
  const { modelsQuery, testMutation } = useNvidiaSidecar({
    modelsEnabled: sidecarEnabled && sidecarApiKeyConfigured,
  });

  return (
    <SidecarIntegrationCard.Provider
      settings={settings}
      busy={busy}
      meta={{
        id: "nvidia",
        title: "NVIDIA Integration",
        conflictName: "NVIDIA",
        description: "Route configured NVIDIA models through codex-lb.",
        icon: Globe,
        sectionId: "nvidia-sidecar",
        enableLabel: "Enable NVIDIA Integration",
        enableDescription: "When enabled, matching model requests route to NVIDIA.",
        callout: (
          <>
            Create an API key at{" "}
            <a href="https://build.nvidia.com/settings" target="_blank" rel="noopener noreferrer">
              build.nvidia.com/settings
            </a>
            , then pin full model IDs from Discovered Models (for example <code>z-ai/glm-5.3</code>).
          </>
        ),
        baseUrlPlaceholder: DEFAULT_BASE_URL,
        apiKeyPlaceholder: "nvapi-…",
        apiKeyConfigured: sidecarApiKeyConfigured,
        externalLink: { href: "https://build.nvidia.com/", label: "NVIDIA NIM catalog" },
      }}
      initial={{
        enabled: sidecarEnabled,
        baseUrl: settings.nvidiaSidecarBaseUrl ?? DEFAULT_BASE_URL,
        prefixes: settings.nvidiaSidecarModelPrefixes ?? [],
        fullModels: settings.nvidiaSidecarFullModels ?? [],
        connectTimeout: settings.nvidiaSidecarConnectTimeoutSeconds ?? DEFAULT_CONNECT_TIMEOUT_SECONDS,
        requestTimeout: settings.nvidiaSidecarRequestTimeoutSeconds ?? DEFAULT_REQUEST_TIMEOUT_SECONDS,
        cacheTtl: settings.nvidiaSidecarModelsCacheTtlSeconds ?? DEFAULT_MODELS_CACHE_TTL_SECONDS,
        defaultReasoningEffort: settings.nvidiaSidecarDefaultReasoningEffort ?? null,
      }}
      models={{ rows: modelsQuery.data?.models ?? [], isLoading: modelsQuery.isLoading }}
      onSave={onSave}
      onTestConnection={() => testMutation.mutateAsync()}
      buildEnablePatch={(enabled) => ({ nvidiaSidecarEnabled: enabled })}
      buildEffortPatch={(effort) => ({ nvidiaSidecarDefaultReasoningEffort: effort })}
      buildPatch={(state) => ({
        nvidiaSidecarBaseUrl: state.baseUrl,
        nvidiaSidecarModelPrefixes: state.prefixes,
        nvidiaSidecarFullModels: state.fullModels,
        nvidiaSidecarConnectTimeoutSeconds: state.connectTimeout,
        nvidiaSidecarRequestTimeoutSeconds: state.requestTimeout,
        nvidiaSidecarModelsCacheTtlSeconds: state.cacheTtl,
        ...(state.apiKey ? { nvidiaSidecarApiKey: state.apiKey } : {}),
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
