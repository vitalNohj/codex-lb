import { Globe } from "lucide-react";

import { Button } from "@/components/ui/button";
import { SidecarIntegrationCard } from "@/features/settings/components/sidecar-integration-card";
import { useOpenAICompatSidecar } from "@/features/settings/hooks/use-settings";
import {
  DEFAULT_OPENAI_COMPAT_CONNECT_TIMEOUT_SECONDS,
  DEFAULT_OPENAI_COMPAT_MODELS_CACHE_TTL_SECONDS,
  DEFAULT_OPENAI_COMPAT_REQUEST_TIMEOUT_SECONDS,
  mapOpenAICompatEndpointUpdates,
  openaiCompatIntegrationId,
  openaiCompatSectionId,
  storedOpenAICompatEndpointUpdates,
} from "@/features/settings/openai-compat-endpoints";
import type {
  DashboardSettings,
  OpenAICompatEndpoint,
  SettingsUpdateRequest,
} from "@/features/settings/schemas";

export type OpenAICompatEndpointSettingsProps = {
  endpoint: OpenAICompatEndpoint;
  settings: DashboardSettings;
  busy: boolean;
  onSave: (patch: Partial<SettingsUpdateRequest>) => Promise<DashboardSettings | void>;
  onRemoved?: () => void;
  bare?: boolean;
};

export function OpenAICompatEndpointSettings({
  endpoint,
  settings,
  busy,
  onSave,
  onRemoved,
  bare = false,
}: OpenAICompatEndpointSettingsProps) {
  const sidecarEnabled = endpoint.enabled ?? false;
  const { modelsQuery, testMutation } = useOpenAICompatSidecar(endpoint.id, {
    modelsEnabled: sidecarEnabled,
  });

  const persistEndpoint = (patch: Partial<OpenAICompatEndpoint>) =>
    onSave({
      openaiCompatEndpoints: mapOpenAICompatEndpointUpdates(settings, endpoint.id, patch),
    });

  const handleRemove = async () => {
    const remaining = storedOpenAICompatEndpointUpdates(settings).filter((item) => item.id !== endpoint.id);
    await onSave({ openaiCompatEndpoints: remaining });
    onRemoved?.();
  };

  return (
    <SidecarIntegrationCard.Provider
      settings={settings}
      busy={busy}
      meta={{
        id: openaiCompatIntegrationId(endpoint.id),
        title: endpoint.name,
        conflictName: endpoint.name,
        description: "Route configured models through this OpenAI-compatible endpoint.",
        icon: Globe,
        sectionId: openaiCompatSectionId(endpoint.id),
        enableLabel: `Enable ${endpoint.name}`,
        enableDescription: "When enabled, matching model requests route to this endpoint.",
        callout: (
          <>
            Any OpenAI-compatible Chat Completions server. Vast.ai example:{" "}
            <code>https://openai.vast.ai/&lt;ENDPOINT_NAME&gt;/v1</code>. API key is optional (vLLM, LM Studio).
          </>
        ),
        baseUrlPlaceholder: "https://openai.vast.ai/<ENDPOINT_NAME>/v1",
        apiKeyPlaceholder: "Optional API key",
        apiKeyConfigured: endpoint.apiKeyConfigured ?? false,
      }}
      initial={{
        enabled: sidecarEnabled,
        baseUrl: endpoint.baseUrl,
        prefixes: endpoint.modelPrefixes ?? [],
        fullModels: endpoint.fullModels ?? [],
        connectTimeout: endpoint.connectTimeoutSeconds ?? DEFAULT_OPENAI_COMPAT_CONNECT_TIMEOUT_SECONDS,
        requestTimeout: endpoint.requestTimeoutSeconds ?? DEFAULT_OPENAI_COMPAT_REQUEST_TIMEOUT_SECONDS,
        cacheTtl: endpoint.modelsCacheTtlSeconds ?? DEFAULT_OPENAI_COMPAT_MODELS_CACHE_TTL_SECONDS,
        defaultReasoningEffort: endpoint.defaultReasoningEffort ?? null,
      }}
      models={{ rows: modelsQuery.data?.models ?? [], isLoading: modelsQuery.isLoading }}
      onSave={onSave}
      onTestConnection={() => testMutation.mutateAsync()}
      buildEnablePatch={(enabled) => ({
        openaiCompatEndpoints: mapOpenAICompatEndpointUpdates(settings, endpoint.id, { enabled }),
      })}
      buildEffortPatch={(effort) => ({
        openaiCompatEndpoints: mapOpenAICompatEndpointUpdates(settings, endpoint.id, {
          defaultReasoningEffort: effort,
        }),
      })}
      buildPatch={(state) => ({
        openaiCompatEndpoints: mapOpenAICompatEndpointUpdates(settings, endpoint.id, {
          baseUrl: state.baseUrl,
          modelPrefixes: state.prefixes,
          fullModels: state.fullModels,
          connectTimeoutSeconds: state.connectTimeout,
          requestTimeoutSeconds: state.requestTimeout,
          modelsCacheTtlSeconds: state.cacheTtl,
          ...(state.apiKey ? { apiKey: state.apiKey } : {}),
        }),
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
        <div className="flex justify-end border-t pt-3">
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-8 text-xs text-destructive hover:text-destructive"
            disabled={busy}
            onClick={() => void handleRemove()}
          >
            Remove
          </Button>
        </div>
      </SidecarIntegrationCard.Frame>
    </SidecarIntegrationCard.Provider>
  );
}
