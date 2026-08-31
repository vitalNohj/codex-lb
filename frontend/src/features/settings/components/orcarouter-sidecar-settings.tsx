import { Globe } from "lucide-react";

import { SidecarIntegrationCard } from "@/features/settings/components/sidecar-integration-card";
import { useOrcaRouterSidecar } from "@/features/settings/hooks/use-settings";
import type { DashboardSettings, SettingsUpdateRequest } from "@/features/settings/schemas";

export type OrcaRouterSidecarSettingsProps = {
  settings: DashboardSettings;
  busy: boolean;
  onSave: (payload: SettingsUpdateRequest) => Promise<void>;
  bare?: boolean;
};

const DEFAULT_BASE_URL = "https://api.orcarouter.ai/v1";
const DEFAULT_CONNECT_TIMEOUT_SECONDS = 8;
const DEFAULT_REQUEST_TIMEOUT_SECONDS = 600;
const DEFAULT_MODELS_CACHE_TTL_SECONDS = 60;

export function OrcaRouterSidecarSettings({ settings, busy, onSave, bare = false }: OrcaRouterSidecarSettingsProps) {
  const sidecarEnabled = settings.orcarouterSidecarEnabled ?? false;
  const sidecarApiKeyConfigured = settings.orcarouterSidecarApiKeyConfigured ?? false;
  const { modelsQuery, testMutation } = useOrcaRouterSidecar({
    modelsEnabled: sidecarEnabled && sidecarApiKeyConfigured,
  });

  return (
    <SidecarIntegrationCard.Provider
      settings={settings}
      busy={busy}
      meta={{
        id: "orcarouter",
        title: "OrcaRouter Integration",
        conflictName: "OrcaRouter",
        description: "Route orcarouter/ models and pinned vendor IDs through OrcaRouter.",
        icon: Globe,
        sectionId: "orcarouter-sidecar",
        enableLabel: "Enable OrcaRouter Integration",
        enableDescription: "When enabled, matching model requests route to OrcaRouter.",
        callout: (
          <>
            Create an API key (sk-orca-…) at{" "}
            <a href="https://www.orcarouter.ai/console" target="_blank" rel="noopener noreferrer">
              orcarouter.ai/console
            </a>
            . Seeded prefix <code>orcarouter/</code> is forwarded unchanged (strip off), so{" "}
            <code>orcarouter/auto</code> stays <code>orcarouter/auto</code>. If another integration already
            owns <code>orcarouter/</code>, remove that prefix before enabling. Pin Orca vendor IDs as full
            models; do not seed openai/, google/, anthropic/, or deepseek/.
          </>
        ),
        baseUrlPlaceholder: DEFAULT_BASE_URL,
        apiKeyPlaceholder: "sk-orca-…",
        apiKeyConfigured: sidecarApiKeyConfigured,
        externalLink: { href: "https://docs.orcarouter.ai/getting-started/quickstart", label: "OrcaRouter docs" },
      }}
      initial={{
        enabled: sidecarEnabled,
        baseUrl: settings.orcarouterSidecarBaseUrl ?? DEFAULT_BASE_URL,
        prefixes: settings.orcarouterSidecarModelPrefixes ?? [],
        fullModels: settings.orcarouterSidecarFullModels ?? [],
        connectTimeout: settings.orcarouterSidecarConnectTimeoutSeconds ?? DEFAULT_CONNECT_TIMEOUT_SECONDS,
        requestTimeout: settings.orcarouterSidecarRequestTimeoutSeconds ?? DEFAULT_REQUEST_TIMEOUT_SECONDS,
        cacheTtl: settings.orcarouterSidecarModelsCacheTtlSeconds ?? DEFAULT_MODELS_CACHE_TTL_SECONDS,
        defaultReasoningEffort: settings.orcarouterSidecarDefaultReasoningEffort ?? null,
      }}
      models={{ rows: modelsQuery.data?.models ?? [], isLoading: modelsQuery.isLoading }}
      onSave={onSave}
      onTestConnection={() => testMutation.mutateAsync()}
      buildEnablePatch={(enabled) => ({ orcarouterSidecarEnabled: enabled })}
      buildEffortPatch={(effort) => ({ orcarouterSidecarDefaultReasoningEffort: effort })}
      buildPatch={(state) => ({
        orcarouterSidecarBaseUrl: state.baseUrl,
        orcarouterSidecarModelPrefixes: state.prefixes,
        orcarouterSidecarFullModels: state.fullModels,
        orcarouterSidecarConnectTimeoutSeconds: state.connectTimeout,
        orcarouterSidecarRequestTimeoutSeconds: state.requestTimeout,
        orcarouterSidecarModelsCacheTtlSeconds: state.cacheTtl,
        ...(state.apiKey ? { orcarouterSidecarApiKey: state.apiKey } : {}),
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
