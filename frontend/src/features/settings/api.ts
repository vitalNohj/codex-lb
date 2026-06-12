import { get, post, put } from "@/lib/api-client";
import {
  AccountProxyBindingRequestSchema,
  AccountProxyBindingSchema,
  ClaudeSidecarModelsResponseSchema,
  ClaudeSidecarQuotaResponseSchema,
  ClaudeSidecarStatusResponseSchema,
  ClaudeSidecarTestResponseSchema,
  DashboardSettingsSchema,
  OmniRouteSidecarModelsResponseSchema,
  OmniRouteSidecarStatusResponseSchema,
  OmniRouteSidecarTestResponseSchema,
  OpenRouterSidecarModelsResponseSchema,
  OpenRouterSidecarStatusResponseSchema,
  OpenRouterSidecarTestResponseSchema,
  SettingsUpdateRequestSchema,
  UpstreamProxyAdminSchema,
  UpstreamProxyEndpointCreateRequestSchema,
  UpstreamProxyEndpointSchema,
  UpstreamProxyPoolCreateRequestSchema,
  UpstreamProxyPoolMemberRequestSchema,
  UpstreamProxyPoolSchema,
} from "@/features/settings/schemas";

const SETTINGS_PATH = "/api/settings";
const UPSTREAM_PROXY_PATH = `${SETTINGS_PATH}/upstream-proxy`;
const CLAUDE_SIDECAR_PATH = "/api/claude-sidecar";
const OPENROUTER_SIDECAR_PATH = "/api/openrouter-sidecar";
const OMNIROUTE_SIDECAR_PATH = "/api/omniroute-sidecar";

export function getSettings() {
  return get(SETTINGS_PATH, DashboardSettingsSchema);
}

export function updateSettings(payload: unknown) {
  const validated = SettingsUpdateRequestSchema.parse(payload);
  return put(SETTINGS_PATH, DashboardSettingsSchema, {
    body: validated,
  });
}

export function getUpstreamProxyAdmin() {
  return get(UPSTREAM_PROXY_PATH, UpstreamProxyAdminSchema);
}

export function createUpstreamProxyEndpoint(payload: unknown) {
  const validated = UpstreamProxyEndpointCreateRequestSchema.parse(payload);
  return post(`${UPSTREAM_PROXY_PATH}/endpoints`, UpstreamProxyEndpointSchema, {
    body: validated,
  });
}

export function createUpstreamProxyPool(payload: unknown) {
  const validated = UpstreamProxyPoolCreateRequestSchema.parse(payload);
  return post(`${UPSTREAM_PROXY_PATH}/pools`, UpstreamProxyPoolSchema, {
    body: validated,
  });
}

export function addUpstreamProxyPoolMember(poolId: string, payload: unknown) {
  const validated = UpstreamProxyPoolMemberRequestSchema.parse(payload);
  return post(`${UPSTREAM_PROXY_PATH}/pools/${encodeURIComponent(poolId)}/members`, UpstreamProxyPoolSchema, {
    body: validated,
  });
}

export function putAccountProxyBinding(accountId: string, payload: unknown) {
  const validated = AccountProxyBindingRequestSchema.parse(payload);
  return put(`${UPSTREAM_PROXY_PATH}/accounts/${encodeURIComponent(accountId)}/binding`, AccountProxyBindingSchema, {
    body: validated,
  });
}

export function getClaudeSidecarStatus() {
  return get(`${CLAUDE_SIDECAR_PATH}/status`, ClaudeSidecarStatusResponseSchema);
}

export function testClaudeSidecarConnection() {
  return post(`${CLAUDE_SIDECAR_PATH}/test`, ClaudeSidecarTestResponseSchema);
}

export function listClaudeSidecarModels() {
  return get(`${CLAUDE_SIDECAR_PATH}/models`, ClaudeSidecarModelsResponseSchema);
}

export function getClaudeSidecarQuota() {
  return get(`${CLAUDE_SIDECAR_PATH}/quota`, ClaudeSidecarQuotaResponseSchema);
}

export function getOpenRouterSidecarStatus() {
  return get(`${OPENROUTER_SIDECAR_PATH}/status`, OpenRouterSidecarStatusResponseSchema);
}

export function testOpenRouterSidecarConnection() {
  return post(`${OPENROUTER_SIDECAR_PATH}/test`, OpenRouterSidecarTestResponseSchema);
}

export function listOpenRouterSidecarModels() {
  return get(`${OPENROUTER_SIDECAR_PATH}/models`, OpenRouterSidecarModelsResponseSchema);
}

export function getOmniRouteSidecarStatus() {
  return get(`${OMNIROUTE_SIDECAR_PATH}/status`, OmniRouteSidecarStatusResponseSchema);
}

export function testOmniRouteSidecarConnection() {
  return post(`${OMNIROUTE_SIDECAR_PATH}/test`, OmniRouteSidecarTestResponseSchema);
}

export function listOmniRouteSidecarModels() {
  return get(`${OMNIROUTE_SIDECAR_PATH}/models`, OmniRouteSidecarModelsResponseSchema);
}
