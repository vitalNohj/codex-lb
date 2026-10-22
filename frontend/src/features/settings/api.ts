<<<<<<< 22625a07e
import { del, get, patch, post, put } from "@/lib/api-client";
||||||| 84fde5a1e
import { get, post, put } from "@/lib/api-client";
=======
import { del, get, post, put } from "@/lib/api-client";
>>>>>>> 72630bbfe
import {
  AccountProxyBindingRequestSchema,
  AccountProxyBindingSchema,
  AliasPoolsHealthResponseSchema,
  ClaudeSidecarModelsResponseSchema,
  CliproxyAccountsResponseSchema,
  CliproxyApiKeyAccountSchema,
  CliproxyApiKeyDeleteRequestSchema,
  CliproxyApiKeyDeleteResponseSchema,
  CliproxyApiKeyWriteRequestSchema,
  CliproxyCatalogModelRequestSchema,
  CliproxyCatalogModelResponseSchema,
  CliproxyCredentialFieldsResponseSchema,
  CliproxyCredentialFieldsUpdateSchema,
  CliproxyCredentialDeleteRequestSchema,
  CliproxyCredentialDeleteResponseSchema,
  CliproxyCredentialRefreshResponseSchema,
  CliproxyCredentialStatusResponseSchema,
  CliproxyCredentialStatusUpdateSchema,
  CliproxyCredentialUploadRequestSchema,
  CliproxyCredentialUploadResponseSchema,
  CliproxyOauthCallbackRequestSchema,
  CliproxyOauthCallbackResponseSchema,
  CliproxyOauthCancelResponseSchema,
  CliproxyOauthProvidersResponseSchema,
  CliproxyOauthStartResponseSchema,
  CliproxyOauthStatusResponseSchema,
  ClaudeSidecarQuotaResponseSchema,
  ClaudeSidecarRoutingResponseSchema,
  ClaudeSidecarStatusResponseSchema,
  ClaudeSidecarTestResponseSchema,
  DashboardSettingsSchema,
<<<<<<< 22625a07e
  OllamaSidecarModelsResponseSchema,
  OllamaSidecarStatusResponseSchema,
  OllamaSidecarTestResponseSchema,
  OmniRouteSidecarModelsResponseSchema,
  OmniRouteSidecarStatusResponseSchema,
  OmniRouteSidecarTestResponseSchema,
  OpenCodeGoSidecarModelsResponseSchema,
  OpenCodeGoSidecarStatusResponseSchema,
  OpenCodeGoSidecarTestResponseSchema,
  OpenRouterSidecarModelsResponseSchema,
  OpenRouterSidecarStatusResponseSchema,
  OpenRouterSidecarTestResponseSchema,
  OpenAICompatModelsResponseSchema,
  OpenAICompatStatusResponseSchema,
  OpenAICompatTestResponseSchema,
  OrcaRouterSidecarModelsResponseSchema,
  OrcaRouterSidecarStatusResponseSchema,
  OrcaRouterSidecarTestResponseSchema,
||||||| 84fde5a1e
=======
  ModelContextWindowOverrideUpsertRequestSchema,
  ModelContextWindowOverridesSchema,
>>>>>>> 72630bbfe
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
const CLIPROXY_ACCOUNTS_PATH = "/api/cliproxy/accounts";
const CLIPROXY_API_KEYS_PATH = "/api/cliproxy/api-keys";
const CLIPROXY_OAUTH_PATH = "/api/cliproxy/oauth";
const OPENROUTER_SIDECAR_PATH = "/api/openrouter-sidecar";
const OPENAI_COMPAT_PATH = "/api/openai-compat";
const ORCAROUTER_SIDECAR_PATH = "/api/orcarouter-sidecar";
const OMNIROUTE_SIDECAR_PATH = "/api/omniroute-sidecar";
const OLLAMA_SIDECAR_PATH = "/api/ollama-sidecar";
const OPENCODE_GO_SIDECAR_PATH = "/api/opencode-go-sidecar";
const TELEMETRY_PATH = `${SETTINGS_PATH}/telemetry`;
<<<<<<< 22625a07e
const ALIAS_POOLS_HEALTH_PATH = `${SETTINGS_PATH}/alias-pools/health`;
||||||| 84fde5a1e
=======
const MODEL_CONTEXT_WINDOW_OVERRIDES_PATH = `${SETTINGS_PATH}/model-context-window-overrides`;
>>>>>>> 72630bbfe

export function getSettings() {
  return get(SETTINGS_PATH, DashboardSettingsSchema);
}

export function updateSettings(payload: unknown) {
  const validated = SettingsUpdateRequestSchema.parse(payload);
  return put(SETTINGS_PATH, DashboardSettingsSchema, {
    body: validated,
  });
}

export function getAliasPoolsHealth() {
  return get(ALIAS_POOLS_HEALTH_PATH, AliasPoolsHealthResponseSchema);
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

<<<<<<< 22625a07e
export function getCliproxyAccounts(provider?: string) {
  const path = provider ? `${CLIPROXY_ACCOUNTS_PATH}?provider=${encodeURIComponent(provider)}` : CLIPROXY_ACCOUNTS_PATH;
  return get(path, CliproxyAccountsResponseSchema);
}

export function updateCliproxyCredentialFields(name: string, payload: unknown) {
  const validated = CliproxyCredentialFieldsUpdateSchema.parse(payload);
  return patch(
    `${CLIPROXY_ACCOUNTS_PATH}/${encodeURIComponent(name)}/fields`,
    CliproxyCredentialFieldsResponseSchema,
    { body: validated },
  );
}

export function updateCliproxyCredentialStatus(name: string, payload: unknown) {
  const validated = CliproxyCredentialStatusUpdateSchema.parse(payload);
  return patch(
    `${CLIPROXY_ACCOUNTS_PATH}/${encodeURIComponent(name)}/status`,
    CliproxyCredentialStatusResponseSchema,
    { body: validated },
  );
}

export function getCliproxyOauthProviders() {
  return get(`${CLIPROXY_OAUTH_PATH}/providers`, CliproxyOauthProvidersResponseSchema);
}

export function startCliproxyOauth(provider: string) {
  return post(
    `${CLIPROXY_OAUTH_PATH}/${encodeURIComponent(provider)}/authorize`,
    CliproxyOauthStartResponseSchema,
  );
}

export function getCliproxyOauthStatus(state: string) {
  return get(
    `${CLIPROXY_OAUTH_PATH}/status?state=${encodeURIComponent(state)}`,
    CliproxyOauthStatusResponseSchema,
  );
}

export function cancelCliproxyOauth(state: string) {
  return del(
    `${CLIPROXY_OAUTH_PATH}/session?state=${encodeURIComponent(state)}`,
    CliproxyOauthCancelResponseSchema,
  );
}

export function submitCliproxyOauthCallback(payload: unknown) {
  const validated = CliproxyOauthCallbackRequestSchema.parse(payload);
  return post(`${CLIPROXY_OAUTH_PATH}/callback`, CliproxyOauthCallbackResponseSchema, {
    body: validated,
  });
}

export function startCliproxyCredentialRefresh(name: string) {
  return post(
    `${CLIPROXY_ACCOUNTS_PATH}/${encodeURIComponent(name)}/refresh`,
    CliproxyCredentialRefreshResponseSchema,
  );
}

export function getCliproxyCredentialRefresh(name: string) {
  return get(
    `${CLIPROXY_ACCOUNTS_PATH}/${encodeURIComponent(name)}/refresh`,
    CliproxyCredentialRefreshResponseSchema,
  );
}

export function deleteCliproxyCredential(name: string) {
  const validated = CliproxyCredentialDeleteRequestSchema.parse({ confirm: true });
  return del(
    `${CLIPROXY_ACCOUNTS_PATH}/${encodeURIComponent(name)}`,
    CliproxyCredentialDeleteResponseSchema,
    { body: validated },
  );
}

export function createCliproxyApiKey(payload: unknown) {
  const validated = CliproxyApiKeyWriteRequestSchema.parse(payload);
  return post(CLIPROXY_API_KEYS_PATH, CliproxyApiKeyAccountSchema, { body: validated });
}

export function updateCliproxyApiKey(kind: string, index: number, payload: unknown) {
  const validated = CliproxyApiKeyWriteRequestSchema.parse(payload);
  return patch(
    `${CLIPROXY_API_KEYS_PATH}/${encodeURIComponent(kind)}/${index}`,
    CliproxyApiKeyAccountSchema,
    { body: validated },
  );
}

export function deleteCliproxyApiKey(kind: string, index: number, accountId: string) {
  const validated = CliproxyApiKeyDeleteRequestSchema.parse({ confirm: true, accountId });
  return del(
    `${CLIPROXY_API_KEYS_PATH}/${encodeURIComponent(kind)}/${index}`,
    CliproxyApiKeyDeleteResponseSchema,
    { body: validated },
  );
}

export function addCliproxyCatalogModel(model: string) {
  const validated = CliproxyCatalogModelRequestSchema.parse({ model });
  return post("/api/cliproxy/catalog/models", CliproxyCatalogModelResponseSchema, { body: validated });
}

export function uploadCliproxyCredential(payload: unknown) {
  const validated = CliproxyCredentialUploadRequestSchema.parse(payload);
  return post(`${CLIPROXY_ACCOUNTS_PATH}/upload`, CliproxyCredentialUploadResponseSchema, {
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

export function setClaudeSidecarSessionAffinity(sessionAffinity: boolean) {
  return put(`${CLAUDE_SIDECAR_PATH}/routing/session-affinity`, ClaudeSidecarRoutingResponseSchema, {
    body: { sessionAffinity },
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

export function setClaudeSidecarAccountExcludedModels(name: string, excludedModels: string[]) {
  return put(`${CLAUDE_SIDECAR_PATH}/routing/excluded-models`, ClaudeSidecarRoutingResponseSchema, {
    body: { name, excludedModels },
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

export function getOpenAICompatStatus(endpointId: string) {
  return get(`${OPENAI_COMPAT_PATH}/${endpointId}/status`, OpenAICompatStatusResponseSchema);
}

export function testOpenAICompatConnection(endpointId: string) {
  return post(`${OPENAI_COMPAT_PATH}/${endpointId}/test`, OpenAICompatTestResponseSchema);
}

export function listOpenAICompatModels(endpointId: string) {
  return get(`${OPENAI_COMPAT_PATH}/${endpointId}/models`, OpenAICompatModelsResponseSchema);
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

export function getOpenCodeGoSidecarStatus() {
  return get(`${OPENCODE_GO_SIDECAR_PATH}/status`, OpenCodeGoSidecarStatusResponseSchema);
}

export function testOpenCodeGoSidecarConnection() {
  return post(`${OPENCODE_GO_SIDECAR_PATH}/test`, OpenCodeGoSidecarTestResponseSchema);
}

export function listOpenCodeGoSidecarModels() {
  return get(`${OPENCODE_GO_SIDECAR_PATH}/models`, OpenCodeGoSidecarModelsResponseSchema);
||||||| 84fde5a1e
=======
// M4 model catalogue: per-model context window overrides (one dashboard row per slug).
export function getModelContextWindowOverrides() {
  return get(MODEL_CONTEXT_WINDOW_OVERRIDES_PATH, ModelContextWindowOverridesSchema);
}

export function putModelContextWindowOverride(slug: string, payload: unknown) {
  const validated = ModelContextWindowOverrideUpsertRequestSchema.parse(payload);
  return put(`${MODEL_CONTEXT_WINDOW_OVERRIDES_PATH}/${encodeURIComponent(slug)}`, ModelContextWindowOverridesSchema, {
    body: validated,
  });
}

export function deleteModelContextWindowOverride(slug: string) {
  return del(`${MODEL_CONTEXT_WINDOW_OVERRIDES_PATH}/${encodeURIComponent(slug)}`, ModelContextWindowOverridesSchema);
>>>>>>> 72630bbfe
}
