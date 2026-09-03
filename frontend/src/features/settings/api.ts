import { get, post, put } from "@/lib/api-client";
import {
  AccountProxyBindingRequestSchema,
  AccountProxyBindingSchema,
  ClaudeSidecarModelsResponseSchema,
  ClaudeSidecarQuotaResponseSchema,
  ClaudeSidecarRoutingResponseSchema,
  ClaudeSidecarStatusResponseSchema,
  ClaudeSidecarTestResponseSchema,
  DashboardSettingsSchema,
  OllamaSidecarModelsResponseSchema,
  OllamaSidecarStatusResponseSchema,
  OllamaSidecarTestResponseSchema,
  OmniRouteSidecarModelsResponseSchema,
  OmniRouteSidecarStatusResponseSchema,
  OmniRouteSidecarTestResponseSchema,
  OpenRouterSidecarModelsResponseSchema,
  OpenRouterSidecarStatusResponseSchema,
  OpenRouterSidecarTestResponseSchema,
  OrcaRouterSidecarModelsResponseSchema,
  OrcaRouterSidecarStatusResponseSchema,
  OrcaRouterSidecarTestResponseSchema,
  SettingsUpdateRequestSchema,
  TelemetryConsentSchema,
  TelemetryConsentUpdateRequestSchema,
  UpstreamProxyAdminSchema,
  UpstreamProxyEndpointCreateRequestSchema,
  UpstreamProxyEndpointSchema,
  UpstreamProxyEndpointTestResponseSchema,
  UpstreamProxyPoolCreateRequestSchema,
  UpstreamProxyPoolMemberRequestSchema,
  UpstreamProxyPoolSchema,
} from "@/features/settings/schemas";
import type { ClaudeSidecarRoutingStrategy } from "@/features/settings/schemas";

const SETTINGS_PATH = "/api/settings";
const UPSTREAM_PROXY_PATH = `${SETTINGS_PATH}/upstream-proxy`;
const CLAUDE_SIDECAR_PATH = "/api/claude-sidecar";
const OPENROUTER_SIDECAR_PATH = "/api/openrouter-sidecar";
const ORCAROUTER_SIDECAR_PATH = "/api/orcarouter-sidecar";
const OMNIROUTE_SIDECAR_PATH = "/api/omniroute-sidecar";
const OLLAMA_SIDECAR_PATH = "/api/ollama-sidecar";
const TELEMETRY_PATH = `${SETTINGS_PATH}/telemetry`;

export function getSettings() {
  return get(SETTINGS_PATH, DashboardSettingsSchema);
}

export function updateSettings(payload: unknown) {
  const validated = SettingsUpdateRequestSchema.parse(payload);
  return put(SETTINGS_PATH, DashboardSettingsSchema, {
    body: validated,
  });
}

export function getTelemetryConsent(options: { includePreview?: boolean } = {}) {
  const path = options.includePreview ? `${TELEMETRY_PATH}?include_preview=true` : TELEMETRY_PATH;
  return get(path, TelemetryConsentSchema);
}

export function updateTelemetryConsent(payload: unknown) {
  const validated = TelemetryConsentUpdateRequestSchema.parse(payload);
  return put(TELEMETRY_PATH, TelemetryConsentSchema, {
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

export function testUpstreamProxyEndpoint(endpointId: string) {
  return post(
    `${UPSTREAM_PROXY_PATH}/endpoints/${encodeURIComponent(endpointId)}/test`,
    UpstreamProxyEndpointTestResponseSchema,
  );
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

export function getClaudeSidecarRouting() {
  return get(`${CLAUDE_SIDECAR_PATH}/routing`, ClaudeSidecarRoutingResponseSchema);
}

export function setClaudeSidecarRoutingStrategy(strategy: ClaudeSidecarRoutingStrategy) {
  return put(`${CLAUDE_SIDECAR_PATH}/routing/strategy`, ClaudeSidecarRoutingResponseSchema, {
    body: { strategy },
  });
}

export function setClaudeSidecarAccountPriority(name: string, priority: number) {
  return put(`${CLAUDE_SIDECAR_PATH}/routing/priority`, ClaudeSidecarRoutingResponseSchema, {
    body: { name, priority },
  });
}

export function setClaudeSidecarAccountPaused(name: string, paused: boolean) {
  return put(`${CLAUDE_SIDECAR_PATH}/routing/paused`, ClaudeSidecarRoutingResponseSchema, {
    body: { name, paused },
  });
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

export function getOrcaRouterSidecarStatus() {
  return get(`${ORCAROUTER_SIDECAR_PATH}/status`, OrcaRouterSidecarStatusResponseSchema);
}

export function testOrcaRouterSidecarConnection() {
  return post(`${ORCAROUTER_SIDECAR_PATH}/test`, OrcaRouterSidecarTestResponseSchema);
}

export function listOrcaRouterSidecarModels() {
  return get(`${ORCAROUTER_SIDECAR_PATH}/models`, OrcaRouterSidecarModelsResponseSchema);
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

export function getOllamaSidecarStatus() {
  return get(`${OLLAMA_SIDECAR_PATH}/status`, OllamaSidecarStatusResponseSchema);
}

export function testOllamaSidecarConnection() {
  return post(`${OLLAMA_SIDECAR_PATH}/test`, OllamaSidecarTestResponseSchema);
}

export function listOllamaSidecarModels() {
  return get(`${OLLAMA_SIDECAR_PATH}/models`, OllamaSidecarModelsResponseSchema);
}
