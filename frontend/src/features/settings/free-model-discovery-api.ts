import { get, post } from "@/lib/api-client";
import {
  FreeModelDiscoveryCurrentRunSchema,
  FreeModelDiscoveryPlanSchema,
  FreeModelDiscoveryRunSchema,
  FreeModelDiscoveryStartRequestSchema,
  type FreeModelDiscoveryStartRequest,
} from "@/features/settings/free-model-discovery-schemas";

const FREE_MODEL_DISCOVERY_PATH = "/api/free-model-discovery";

export function getFreeModelDiscoveryPlan() {
  return get(`${FREE_MODEL_DISCOVERY_PATH}/plan`, FreeModelDiscoveryPlanSchema);
}

export function startFreeModelDiscoveryRun(payload: FreeModelDiscoveryStartRequest) {
  const validated = FreeModelDiscoveryStartRequestSchema.parse(payload);
  return post(`${FREE_MODEL_DISCOVERY_PATH}/runs`, FreeModelDiscoveryRunSchema, { body: validated });
}

export function getCurrentFreeModelDiscoveryRun() {
  return get(`${FREE_MODEL_DISCOVERY_PATH}/runs/current`, FreeModelDiscoveryCurrentRunSchema);
}

export function cancelFreeModelDiscoveryRun(runId: string) {
  return post(`${FREE_MODEL_DISCOVERY_PATH}/runs/${encodeURIComponent(runId)}/cancel`, FreeModelDiscoveryRunSchema);
}
