import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import {
  addUpstreamProxyPoolMember,
  createUpstreamProxyEndpoint,
  createUpstreamProxyPool,
  getClaudeSidecarQuota,
  getClaudeSidecarStatus,
  getOllamaSidecarStatus,
  getOmniRouteSidecarStatus,
  getOpenRouterSidecarStatus,
  getSettings,
  listClaudeSidecarModels,
  listOllamaSidecarModels,
  listOmniRouteSidecarModels,
  listOpenRouterSidecarModels,
  getUpstreamProxyAdmin,
  putAccountProxyBinding,
  testClaudeSidecarConnection,
  testOllamaSidecarConnection,
  testOmniRouteSidecarConnection,
  testOpenRouterSidecarConnection,
  updateSettings,
} from "@/features/settings/api";
import type { SettingsUpdateRequest } from "@/features/settings/schemas";
import type {
  AccountProxyBindingRequest,
  UpstreamProxyEndpointCreateRequest,
  UpstreamProxyPoolCreateRequest,
  UpstreamProxyPoolMemberRequest,
} from "@/features/settings/schemas";

export function useSettings() {
  const queryClient = useQueryClient();

  const { data, error, isFetching, isLoading, isPending, isSuccess, refetch } = useQuery({
    queryKey: ["settings", "detail"],
    queryFn: getSettings,
  });
  const settingsQuery = { data, error, isFetching, isLoading, isPending, isSuccess, refetch };

  const updateSettingsMutation = useMutation({
    mutationFn: (payload: SettingsUpdateRequest) => updateSettings(payload),
    onSuccess: () => {
      toast.success("Settings saved");
      void queryClient.invalidateQueries({ queryKey: ["settings", "detail"] });
      void queryClient.invalidateQueries({ queryKey: ["settings", "upstream-proxy"] });
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to save settings");
    },
  });

  return {
    settingsQuery,
    updateSettingsMutation,
  };
}

export function useUpstreamProxyAdmin() {
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
      toast.success("Proxy endpoint created");
      void queryClient.invalidateQueries({ queryKey: ["settings", "upstream-proxy"] });
      void queryClient.invalidateQueries({ queryKey: ["settings", "detail"] });
    },
    onError: (error: Error) => {
      toast.error(error.message || "Proxy endpoint creation failed");
    },
  });

  const createPoolMutation = useMutation({
    mutationFn: (payload: UpstreamProxyPoolCreateRequest) => createUpstreamProxyPool(payload),
    onSuccess: () => {
      toast.success("Proxy pool created");
      void queryClient.invalidateQueries({ queryKey: ["settings", "upstream-proxy"] });
      void queryClient.invalidateQueries({ queryKey: ["settings", "detail"] });
    },
    onError: (error: Error) => {
      toast.error(error.message || "Proxy pool creation failed");
    },
  });

  const addPoolMemberMutation = useMutation({
    mutationFn: ({ poolId, payload }: { poolId: string; payload: UpstreamProxyPoolMemberRequest }) =>
      addUpstreamProxyPoolMember(poolId, payload),
    onSuccess: () => {
      toast.success("Proxy pool member added");
      void queryClient.invalidateQueries({ queryKey: ["settings", "upstream-proxy"] });
      void queryClient.invalidateQueries({ queryKey: ["settings", "detail"] });
    },
    onError: (error: Error) => {
      toast.error(error.message || "Proxy pool update failed");
    },
  });

  const accountBindingMutation = useMutation({
    mutationFn: ({ accountId, payload }: { accountId: string; payload: AccountProxyBindingRequest }) =>
      putAccountProxyBinding(accountId, payload),
    onSuccess: () => {
      toast.success("Account proxy binding saved");
      void queryClient.invalidateQueries({ queryKey: ["settings", "upstream-proxy"] });
      void queryClient.invalidateQueries({ queryKey: ["settings", "detail"] });
    },
    onError: (error: Error) => {
      toast.error(error.message || "Account proxy binding failed");
    },
  });

  return {
    upstreamProxyQuery,
    createEndpointMutation,
    createPoolMutation,
    addPoolMemberMutation,
    accountBindingMutation,
  };
}

export type SidecarConnectionProvider = "claude" | "openrouter" | "omniroute" | "ollama";

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

export function useClaudeSidecar() {
  const statusQuery = useQuery({
    queryKey: ["settings", "claude-sidecar", "status"],
    queryFn: getClaudeSidecarStatus,
  });
  const modelsQuery = useQuery({
    queryKey: ["settings", "claude-sidecar", "models"],
    queryFn: listClaudeSidecarModels,
  });
  const testMutation = useSidecarConnectionTest("claude");
  return { statusQuery, modelsQuery, testMutation };
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
