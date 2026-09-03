import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { ApiError } from "@/lib/api-client";
import {
  addUpstreamProxyPoolMember,
  createUpstreamProxyEndpoint,
  createUpstreamProxyPool,
  getClaudeSidecarQuota,
  getClaudeSidecarRouting,
  getClaudeSidecarStatus,
  getOllamaSidecarStatus,
  getOmniRouteSidecarStatus,
  getOpenRouterSidecarStatus,
  getOrcaRouterSidecarStatus,
  getSettings,
  listClaudeSidecarModels,
  listOllamaSidecarModels,
  listOmniRouteSidecarModels,
  listOpenRouterSidecarModels,
  listOrcaRouterSidecarModels,
  getTelemetryConsent,
  getUpstreamProxyAdmin,
  putAccountProxyBinding,
  setClaudeSidecarAccountPaused,
  setClaudeSidecarAccountPriority,
  setClaudeSidecarRoutingStrategy,
  testClaudeSidecarConnection,
  testOllamaSidecarConnection,
  testOmniRouteSidecarConnection,
  testOpenRouterSidecarConnection,
  testOrcaRouterSidecarConnection,
  testUpstreamProxyEndpoint,
  updateSettings,
  updateTelemetryConsent,
} from "@/features/settings/api";
import type { ClaudeSidecarRoutingStrategy, SettingsUpdateRequest } from "@/features/settings/schemas";
import type {
  AccountProxyBindingRequest,
  TelemetryConsentUpdateRequest,
  UpstreamProxyEndpointCreateRequest,
  UpstreamProxyPoolCreateRequest,
  UpstreamProxyPoolMemberRequest,
} from "@/features/settings/schemas";

export function useSettings() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const { data, error, isFetching, isLoading, isPending, isSuccess, refetch } = useQuery({
    queryKey: ["settings", "detail"],
    queryFn: getSettings,
  });
  const settingsQuery = { data, error, isFetching, isLoading, isPending, isSuccess, refetch };

  const updateSettingsMutation = useMutation({
    mutationFn: (payload: SettingsUpdateRequest) => updateSettings(payload),
    onSuccess: () => {
      toast.success(t("settings.toasts.saved"));
      void queryClient.invalidateQueries({ queryKey: ["settings", "detail"] });
      void queryClient.invalidateQueries({ queryKey: ["settings", "upstream-proxy"] });
    },
    onError: (error: Error) => {
      toast.error(error.message || t("settings.toasts.saveFailed"));
      if (error instanceof ApiError && error.code === "settings_conflict") {
        // Another writer committed since this form was loaded; refetch so the
        // next save carries the fresh expectedVersion.
        void queryClient.invalidateQueries({ queryKey: ["settings", "detail"] });
      }
    },
  });

  return {
    settingsQuery,
    updateSettingsMutation,
  };
}

export function useTelemetryConsent(options?: { enabled?: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const { data, error, isFetching, isLoading, isPending, isSuccess, refetch } = useQuery({
    queryKey: ["settings", "telemetry"],
    queryFn: () => getTelemetryConsent(),
    enabled: options?.enabled ?? true,
  });
  const telemetryConsentQuery = { data, error, isFetching, isLoading, isPending, isSuccess, refetch };

  const updateTelemetryConsentMutation = useMutation({
    mutationFn: (payload: TelemetryConsentUpdateRequest) => updateTelemetryConsent(payload),
    onSuccess: () => {
      toast.success(t("settings.telemetry.toasts.saved"));
      void queryClient.invalidateQueries({ queryKey: ["settings", "telemetry"] });
    },
    onError: (error: Error) => {
      toast.error(error.message || t("settings.telemetry.toasts.saveFailed"));
    },
  });

  return {
    telemetryConsentQuery,
    updateTelemetryConsentMutation,
  };
}

// On-demand snapshot preview for the settings "View collected data" dialog.
// The snapshot build is expensive, so the query stays idle until `enabled`
// flips true (the dialog opens); consent mutations invalidate it via the
// ["settings", "telemetry"] key prefix.
export function useTelemetryPreview(enabled: boolean) {
  const { data, error, isFetching, isLoading, isPending, isSuccess, refetch } = useQuery({
    queryKey: ["settings", "telemetry", "preview"],
    queryFn: () => getTelemetryConsent({ includePreview: true }),
    enabled,
  });
  return {
    telemetryPreviewQuery: { data, error, isFetching, isLoading, isPending, isSuccess, refetch },
  };
}

export function useUpstreamProxyAdmin() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const {
    data: upstreamProxyData,
    error: upstreamProxyError,
    isFetching: upstreamProxyIsFetching,
    isLoading: upstreamProxyIsLoading,
    isPending: upstreamProxyIsPending,
    isSuccess: upstreamProxyIsSuccess,
    refetch: refetchUpstreamProxy,
  } = useQuery({
    queryKey: ["settings", "upstream-proxy"],
    queryFn: getUpstreamProxyAdmin,
  });
  const upstreamProxyQuery = {
    data: upstreamProxyData,
    error: upstreamProxyError,
    isFetching: upstreamProxyIsFetching,
    isLoading: upstreamProxyIsLoading,
    isPending: upstreamProxyIsPending,
    isSuccess: upstreamProxyIsSuccess,
    refetch: refetchUpstreamProxy,
  };

  const createEndpointMutation = useMutation({
    mutationFn: (payload: UpstreamProxyEndpointCreateRequest) => createUpstreamProxyEndpoint(payload),
    onSuccess: () => {
      toast.success(t("upstreamProxy.toasts.endpointCreated"));
      void queryClient.invalidateQueries({ queryKey: ["settings", "upstream-proxy"] });
      void queryClient.invalidateQueries({ queryKey: ["settings", "detail"] });
    },
    onError: (error: Error) => {
      toast.error(error.message || t("upstreamProxy.toasts.endpointCreateFailed"));
    },
  });

  const createPoolMutation = useMutation({
    mutationFn: (payload: UpstreamProxyPoolCreateRequest) => createUpstreamProxyPool(payload),
    onSuccess: () => {
      toast.success(t("upstreamProxy.toasts.poolCreated"));
      void queryClient.invalidateQueries({ queryKey: ["settings", "upstream-proxy"] });
      void queryClient.invalidateQueries({ queryKey: ["settings", "detail"] });
    },
    onError: (error: Error) => {
      toast.error(error.message || t("upstreamProxy.toasts.poolCreateFailed"));
    },
  });

  const addPoolMemberMutation = useMutation({
    mutationFn: ({ poolId, payload }: { poolId: string; payload: UpstreamProxyPoolMemberRequest }) =>
      addUpstreamProxyPoolMember(poolId, payload),
    onSuccess: () => {
      toast.success(t("upstreamProxy.toasts.memberAdded"));
      void queryClient.invalidateQueries({ queryKey: ["settings", "upstream-proxy"] });
      void queryClient.invalidateQueries({ queryKey: ["settings", "detail"] });
    },
    onError: (error: Error) => {
      toast.error(error.message || t("upstreamProxy.toasts.poolUpdateFailed"));
    },
  });

  const testEndpointMutation = useMutation({
    mutationFn: (endpointId: string) => testUpstreamProxyEndpoint(endpointId),
    onSuccess: (result) => {
      if (result.ok) {
        toast.success(t("upstreamProxy.toasts.endpointReachable"));
      } else {
        toast.error(result.error || t("upstreamProxy.toasts.endpointTestFailed"));
      }
    },
    onError: (error: Error) => {
      toast.error(error.message || t("upstreamProxy.toasts.endpointTestFailed"));
    },
  });

  const accountBindingMutation = useMutation({
    mutationFn: ({ accountId, payload }: { accountId: string; payload: AccountProxyBindingRequest }) =>
      putAccountProxyBinding(accountId, payload),
    onSuccess: () => {
      toast.success(t("upstreamProxy.toasts.accountBindingSaved"));
      void queryClient.invalidateQueries({ queryKey: ["settings", "upstream-proxy"] });
      void queryClient.invalidateQueries({ queryKey: ["settings", "detail"] });
    },
    onError: (error: Error) => {
      toast.error(error.message || t("upstreamProxy.toasts.accountBindingFailed"));
    },
  });

  return {
    upstreamProxyQuery,
    createEndpointMutation,
    createPoolMutation,
    addPoolMemberMutation,
    testEndpointMutation,
    accountBindingMutation,
  };
}

export type SidecarConnectionProvider = "claude" | "openrouter" | "orcarouter" | "omniroute" | "ollama";

const SIDECAR_TEST_CONFIG: Record<
  SidecarConnectionProvider,
  {
    queryKey: string;
    testConnection: () => Promise<unknown>;
    successMessage: string;
    errorMessage: string;
  }
> = {
  claude: {
    queryKey: "claude-sidecar",
    testConnection: testClaudeSidecarConnection,
    successMessage: "Claude sidecar tested",
    errorMessage: "Claude sidecar test failed",
  },
  openrouter: {
    queryKey: "openrouter-sidecar",
    testConnection: testOpenRouterSidecarConnection,
    successMessage: "OpenRouter sidecar tested",
    errorMessage: "OpenRouter sidecar test failed",
  },
  orcarouter: {
    queryKey: "orcarouter-sidecar",
    testConnection: testOrcaRouterSidecarConnection,
    successMessage: "OrcaRouter tested",
    errorMessage: "OrcaRouter test failed",
  },
  omniroute: {
    queryKey: "omniroute-sidecar",
    testConnection: testOmniRouteSidecarConnection,
    successMessage: "OmniRoute sidecar tested",
    errorMessage: "OmniRoute sidecar test failed",
  },
  ollama: {
    queryKey: "ollama-sidecar",
    testConnection: testOllamaSidecarConnection,
    successMessage: "Ollama sidecar tested",
    errorMessage: "Ollama sidecar test failed",
  },
};

/**
 * Shared connection-test mutation for sidecar integrations.
 *
 * Status, settings detail, accounts, and models queries are invalidated in
 * `onSettled` (not `onSuccess`) so a failed test still refreshes the Accounts
 * tab connection status with the latest recorded health.
 */
export function useSidecarConnectionTest(provider: SidecarConnectionProvider) {
  const queryClient = useQueryClient();
  const config = SIDECAR_TEST_CONFIG[provider];
  return useMutation({
    mutationFn: config.testConnection,
    onSuccess: () => {
      toast.success(config.successMessage);
    },
    onError: (error: Error) => {
      toast.error(error.message || config.errorMessage);
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["settings", config.queryKey] });
      void queryClient.invalidateQueries({ queryKey: ["settings", "detail"] });
      void queryClient.invalidateQueries({ queryKey: ["accounts"] });
      void queryClient.invalidateQueries({ queryKey: ["models"] });
    },
  });
}

export function useClaudeSidecarAccountPause() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ name, paused }: { name: string; paused: boolean }) =>
      setClaudeSidecarAccountPaused(name, paused),
    onError: (error: Error) => {
      toast.error(error.message || "Failed to update CLIProxyAPI account pause state");
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["settings", "claude-sidecar", "routing"] });
      void queryClient.invalidateQueries({ queryKey: ["settings", "claude-sidecar", "quota"] });
      void queryClient.invalidateQueries({ queryKey: ["accounts", "list"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export function useClaudeSidecar(options?: { routingEnabled?: boolean }) {
  const queryClient = useQueryClient();
  const routingQueryKey = ["settings", "claude-sidecar", "routing"] as const;
  const statusQuery = useQuery({
    queryKey: ["settings", "claude-sidecar", "status"],
    queryFn: getClaudeSidecarStatus,
  });
  const modelsQuery = useQuery({
    queryKey: ["settings", "claude-sidecar", "models"],
    queryFn: listClaudeSidecarModels,
  });
  const routingQuery = useQuery({
    queryKey: routingQueryKey,
    queryFn: getClaudeSidecarRouting,
    enabled: options?.routingEnabled ?? false,
  });
  const strategyMutation = useMutation({
    mutationFn: (strategy: ClaudeSidecarRoutingStrategy) => setClaudeSidecarRoutingStrategy(strategy),
    onError: (error: Error) => {
      toast.error(error.message || "Failed to update CLIProxyAPI routing strategy");
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: routingQueryKey });
    },
  });
  const priorityMutation = useMutation({
    mutationFn: ({ name, priority }: { name: string; priority: number }) =>
      setClaudeSidecarAccountPriority(name, priority),
    onError: (error: Error) => {
      toast.error(error.message || "Failed to update CLIProxyAPI account priority");
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: routingQueryKey });
    },
  });
  const pausedMutation = useClaudeSidecarAccountPause();
  const testMutation = useSidecarConnectionTest("claude");
  return { statusQuery, modelsQuery, routingQuery, strategyMutation, priorityMutation, pausedMutation, testMutation };
}

export function useClaudeSidecarQuota() {
  const quotaQuery = useQuery({
    queryKey: ["settings", "claude-sidecar", "quota"],
    queryFn: getClaudeSidecarQuota,
    refetchInterval: 180_000,
  });
  return { quotaQuery };
}

export function useOpenRouterSidecar(options?: { modelsEnabled?: boolean }) {
  const statusQuery = useQuery({
    queryKey: ["settings", "openrouter-sidecar", "status"],
    queryFn: getOpenRouterSidecarStatus,
  });
  const modelsQuery = useQuery({
    queryKey: ["settings", "openrouter-sidecar", "models"],
    queryFn: listOpenRouterSidecarModels,
    enabled: options?.modelsEnabled ?? true,
  });
  const testMutation = useSidecarConnectionTest("openrouter");
  return { statusQuery, modelsQuery, testMutation };
}

export function useOrcaRouterSidecar(options?: { modelsEnabled?: boolean }) {
  const statusQuery = useQuery({
    queryKey: ["settings", "orcarouter-sidecar", "status"],
    queryFn: getOrcaRouterSidecarStatus,
  });
  const modelsQuery = useQuery({
    queryKey: ["settings", "orcarouter-sidecar", "models"],
    queryFn: listOrcaRouterSidecarModels,
    enabled: options?.modelsEnabled ?? true,
  });
  const testMutation = useSidecarConnectionTest("orcarouter");
  return { statusQuery, modelsQuery, testMutation };
}

export function useOmniRouteSidecar(options?: { modelsEnabled?: boolean }) {
  const statusQuery = useQuery({
    queryKey: ["settings", "omniroute-sidecar", "status"],
    queryFn: getOmniRouteSidecarStatus,
  });
  const modelsQuery = useQuery({
    queryKey: ["settings", "omniroute-sidecar", "models"],
    queryFn: listOmniRouteSidecarModels,
    enabled: options?.modelsEnabled ?? true,
  });
  const testMutation = useSidecarConnectionTest("omniroute");
  return { statusQuery, modelsQuery, testMutation };
}

export function useOllamaSidecar(options?: { modelsEnabled?: boolean }) {
  const statusQuery = useQuery({
    queryKey: ["settings", "ollama-sidecar", "status"],
    queryFn: getOllamaSidecarStatus,
  });
  const modelsQuery = useQuery({
    queryKey: ["settings", "ollama-sidecar", "models"],
    queryFn: listOllamaSidecarModels,
    enabled: options?.modelsEnabled ?? true,
  });
  const testMutation = useSidecarConnectionTest("ollama");
  return { statusQuery, modelsQuery, testMutation };
}
