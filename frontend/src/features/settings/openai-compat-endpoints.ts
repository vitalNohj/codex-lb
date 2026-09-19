import type {
  DashboardSettings,
  OpenAICompatEndpoint,
  OpenAICompatEndpointUpdate,
} from "@/features/settings/schemas";

export const OPENAI_COMPAT_MAX_ENDPOINTS = 32;
export const OPENAI_COMPAT_INTEGRATION_PREFIX = "openaiCompat:" as const;
export const OPENAI_COMPAT_ACCOUNT_PREFIX = "openai-compat-";
export const OPENAI_COMPAT_SECTION_PREFIX = "openai-compat-";
export const OPENAI_COMPAT_FILTER_KEY = "openai_compat";

export const DEFAULT_OPENAI_COMPAT_CONNECT_TIMEOUT_SECONDS = 8;
export const DEFAULT_OPENAI_COMPAT_REQUEST_TIMEOUT_SECONDS = 600;
export const DEFAULT_OPENAI_COMPAT_MODELS_CACHE_TTL_SECONDS = 60;

export function openaiCompatIntegrationId(endpointId: string): `openaiCompat:${string}` {
  return `${OPENAI_COMPAT_INTEGRATION_PREFIX}${endpointId}`;
}

export function isOpenAICompatIntegrationId(id: string): id is `openaiCompat:${string}` {
  return id.startsWith(OPENAI_COMPAT_INTEGRATION_PREFIX);
}

export function openaiCompatEndpointIdFromIntegrationId(id: string): string | null {
  if (!isOpenAICompatIntegrationId(id)) {
    return null;
  }
  return id.slice(OPENAI_COMPAT_INTEGRATION_PREFIX.length);
}

export function openaiCompatAccountId(endpointId: string): string {
  return `${OPENAI_COMPAT_ACCOUNT_PREFIX}${endpointId}`;
}

export function openaiCompatEndpointIdFromAccountId(accountId: string | null | undefined): string | null {
  if (!accountId?.startsWith(OPENAI_COMPAT_ACCOUNT_PREFIX)) {
    return null;
  }
  return accountId.slice(OPENAI_COMPAT_ACCOUNT_PREFIX.length);
}

export function openaiCompatSectionId(endpointId: string): string {
  return `${OPENAI_COMPAT_SECTION_PREFIX}${endpointId}`;
}

export function toOpenAICompatEndpointUpdate(
  endpoint: OpenAICompatEndpoint,
  patch?: Partial<OpenAICompatEndpointUpdate>,
): OpenAICompatEndpointUpdate {
  return {
    id: endpoint.id,
    name: endpoint.name,
    enabled: endpoint.enabled,
    baseUrl: endpoint.baseUrl,
    modelPrefixes: endpoint.modelPrefixes ?? [],
    fullModels: endpoint.fullModels ?? [],
    connectTimeoutSeconds: endpoint.connectTimeoutSeconds ?? DEFAULT_OPENAI_COMPAT_CONNECT_TIMEOUT_SECONDS,
    requestTimeoutSeconds: endpoint.requestTimeoutSeconds ?? DEFAULT_OPENAI_COMPAT_REQUEST_TIMEOUT_SECONDS,
    modelsCacheTtlSeconds: endpoint.modelsCacheTtlSeconds ?? DEFAULT_OPENAI_COMPAT_MODELS_CACHE_TTL_SECONDS,
    defaultReasoningEffort: endpoint.defaultReasoningEffort ?? null,
    ...patch,
  };
}

export function mapOpenAICompatEndpointUpdates(
  settings: DashboardSettings,
  endpointId: string,
  patch: Partial<OpenAICompatEndpointUpdate>,
): OpenAICompatEndpointUpdate[] {
  return (settings.openaiCompatEndpoints ?? []).map((endpoint) =>
    endpoint.id === endpointId
      ? toOpenAICompatEndpointUpdate(endpoint, patch)
      : toOpenAICompatEndpointUpdate(endpoint),
  );
}

export function storedOpenAICompatEndpointUpdates(
  settings: DashboardSettings,
): OpenAICompatEndpointUpdate[] {
  return (settings.openaiCompatEndpoints ?? []).map((endpoint) => toOpenAICompatEndpointUpdate(endpoint));
}
