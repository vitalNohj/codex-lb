import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import {
  cancelFreeModelDiscoveryRun,
  getCurrentFreeModelDiscoveryRun,
  getFreeModelDiscoveryPlan,
  startFreeModelDiscoveryRun,
} from "@/features/settings/free-model-discovery-api";
import type { FreeModelDiscoveryStartRequest } from "@/features/settings/free-model-discovery-schemas";

export const FREE_MODEL_DISCOVERY_PLAN_QUERY_KEY = ["settings", "free-model-discovery", "plan"] as const;
export const FREE_MODEL_DISCOVERY_CURRENT_RUN_QUERY_KEY = ["settings", "free-model-discovery", "current"] as const;
const SETTINGS_DETAIL_QUERY_KEY = ["settings", "detail"] as const;

const RUNNING_POLL_MS = 5_000;

export function useFreeModelDiscoveryPlan(options: { enabled: boolean }) {
  return useQuery({
    queryKey: FREE_MODEL_DISCOVERY_PLAN_QUERY_KEY,
    queryFn: getFreeModelDiscoveryPlan,
    enabled: options.enabled,
    // The plan hits both routers' model lists. Never refetch on its own.
    staleTime: Number.POSITIVE_INFINITY,
    gcTime: 0,
  });
}

export function useFreeModelDiscoveryCurrentRun() {
  return useQuery({
    queryKey: FREE_MODEL_DISCOVERY_CURRENT_RUN_QUERY_KEY,
    queryFn: getCurrentFreeModelDiscoveryRun,
    refetchInterval: (query) => (query.state.data?.status === "running" ? RUNNING_POLL_MS : false),
    refetchIntervalInBackground: false,
  });
}

export function useFreeModelDiscoveryMutations() {
  const queryClient = useQueryClient();

  const invalidateRun = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: FREE_MODEL_DISCOVERY_CURRENT_RUN_QUERY_KEY }),
      // Passed models are pinned into settings as the run progresses.
      queryClient.invalidateQueries({ queryKey: SETTINGS_DETAIL_QUERY_KEY }),
    ]);

  const startMutation = useMutation({
    mutationFn: (payload: FreeModelDiscoveryStartRequest) => startFreeModelDiscoveryRun(payload),
    onSuccess: async (run) => {
      toast.success(`Discovery run started with ${run.counts.total} model${run.counts.total === 1 ? "" : "s"}`);
      queryClient.removeQueries({ queryKey: FREE_MODEL_DISCOVERY_PLAN_QUERY_KEY });
      await invalidateRun();
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to start discovery run");
    },
  });

  const cancelMutation = useMutation({
    mutationFn: (runId: string) => cancelFreeModelDiscoveryRun(runId),
    onSuccess: async () => {
      toast.success("Cancel requested; the run stops after the current probe");
      await invalidateRun();
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to cancel discovery run");
    },
  });

  return { startMutation, cancelMutation };
}
