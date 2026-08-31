import type {
  DashboardSettings,
  SettingsUpdateRequest,
} from "@/features/settings/schemas";
import { OMNIROUTE_ENABLED } from "@/lib/product-capabilities";

/** Update fields the server refuses while the OmniRoute capability is off. */
const OMNIROUTE_UPDATE_FIELDS = [
  "omnirouteSidecarEnabled",
  "omnirouteSidecarBaseUrl",
  "omnirouteSidecarApiKey",
  "omnirouteSidecarClearApiKey",
  "omnirouteSidecarModelPrefixes",
  "omnirouteSidecarFullModels",
  "omnirouteSidecarSelectedModels",
  "omnirouteSidecarConnectTimeoutSeconds",
  "omnirouteSidecarRequestTimeoutSeconds",
  "omnirouteSidecarModelsCacheTtlSeconds",
  "omnirouteSidecarDefaultReasoningEffort",
] as const satisfies readonly (keyof SettingsUpdateRequest)[];

export function buildSettingsUpdateRequest(
  settings: DashboardSettings,
  patch: Partial<SettingsUpdateRequest>,
): SettingsUpdateRequest {
  const payload: SettingsUpdateRequest = {
    expectedVersion: settings.version,
    stickyThreadsEnabled: settings.stickyThreadsEnabled,
    upstreamStreamTransport: settings.upstreamStreamTransport,
    prohibitFastMode: settings.prohibitFastMode,
    httpDownstreamTransportPolicy: settings.httpDownstreamTransportPolicy,
    preferEarlierResetAccounts: settings.preferEarlierResetAccounts,
    preferEarlierResetWindow: settings.preferEarlierResetWindow,
    showResetCreditBadges: settings.showResetCreditBadges,
    autoRedeemResetCreditsBeforeExpiry: settings.autoRedeemResetCreditsBeforeExpiry,
    showResetCreditExpiryBadge: settings.showResetCreditExpiryBadge,
    routingStrategy: settings.routingStrategy,
    relativeAvailabilityPower: settings.relativeAvailabilityPower,
    relativeAvailabilityTopK: settings.relativeAvailabilityTopK,
    singleAccountId: settings.singleAccountId,
    openaiCacheAffinityMaxAgeSeconds: settings.openaiCacheAffinityMaxAgeSeconds,
    dashboardSessionTtlSeconds: settings.dashboardSessionTtlSeconds,
    warmupModel: settings.warmupModel,
    stickyReallocationBudgetThresholdPct: settings.stickyReallocationBudgetThresholdPct,
    stickyReallocationPrimaryBudgetThresholdPct: settings.stickyReallocationPrimaryBudgetThresholdPct,
    stickyReallocationSecondaryBudgetThresholdPct: settings.stickyReallocationSecondaryBudgetThresholdPct,
    additionalQuotaRoutingPolicies: settings.additionalQuotaRoutingPolicies ?? {},
    modelAliases: settings.modelAliases ?? {},
    customAliasCatalog: settings.customAliasCatalog ?? {},
    importWithoutOverwrite: settings.importWithoutOverwrite,
    totpRequiredOnLogin: settings.totpRequiredOnLogin,
    apiKeyAuthEnabled: settings.apiKeyAuthEnabled,
    limitWarmupEnabled: settings.limitWarmupEnabled,
    limitWarmupWindows: settings.limitWarmupWindows,
    limitWarmupModel: settings.limitWarmupModel,
    limitWarmupPrompt: settings.limitWarmupPrompt,
    limitWarmupCooldownSeconds: settings.limitWarmupCooldownSeconds,
    limitWarmupExhaustedThresholdPercent: settings.limitWarmupExhaustedThresholdPercent,
    limitWarmupIdleThresholdPercent: settings.limitWarmupIdleThresholdPercent,
    limitWarmupMinAvailablePercent: settings.limitWarmupMinAvailablePercent,
    limitWarmupStaggeredIdleEnabled: settings.limitWarmupStaggeredIdleEnabled,
    weeklyPaceWorkingDays: settings.weeklyPaceWorkingDays,
    weeklyPaceSmoothingMinutes: settings.weeklyPaceSmoothingMinutes,
    claudeSidecarEnabled: settings.claudeSidecarEnabled,
    claudeSidecarBaseUrl: settings.claudeSidecarBaseUrl,
    claudeSidecarModelPrefixes: settings.claudeSidecarModelPrefixes,
    claudeSidecarFullModels: settings.claudeSidecarFullModels,
    claudeSidecarConnectTimeoutSeconds: settings.claudeSidecarConnectTimeoutSeconds,
    claudeSidecarRequestTimeoutSeconds: settings.claudeSidecarRequestTimeoutSeconds,
    claudeSidecarModelsCacheTtlSeconds: settings.claudeSidecarModelsCacheTtlSeconds,
    claudeSidecarQuotaPollIntervalSeconds: settings.claudeSidecarQuotaPollIntervalSeconds,
    claudeSidecarAuthPlans: settings.claudeSidecarAuthPlans,
    claudeSidecarUsagePollIntervalSeconds: settings.claudeSidecarUsagePollIntervalSeconds,
    claudeSidecarUsageQueueBatchSize: settings.claudeSidecarUsageQueueBatchSize,
    claudeSidecarUsageCollectionEnabled: settings.claudeSidecarUsageCollectionEnabled,
    claudeSidecarDefaultReasoningEffort: settings.claudeSidecarDefaultReasoningEffort ?? null,
    openrouterSidecarEnabled: settings.openrouterSidecarEnabled,
    openrouterSidecarBaseUrl: settings.openrouterSidecarBaseUrl,
    openrouterSidecarModelPrefixes: settings.openrouterSidecarModelPrefixes,
    openrouterSidecarFullModels: settings.openrouterSidecarFullModels,
    openrouterSidecarConnectTimeoutSeconds: settings.openrouterSidecarConnectTimeoutSeconds,
    openrouterSidecarRequestTimeoutSeconds: settings.openrouterSidecarRequestTimeoutSeconds,
    openrouterSidecarModelsCacheTtlSeconds: settings.openrouterSidecarModelsCacheTtlSeconds,
    openrouterSidecarDefaultReasoningEffort: settings.openrouterSidecarDefaultReasoningEffort ?? null,
    orcarouterSidecarEnabled: settings.orcarouterSidecarEnabled,
    orcarouterSidecarBaseUrl: settings.orcarouterSidecarBaseUrl,
    orcarouterSidecarModelPrefixes: settings.orcarouterSidecarModelPrefixes,
    orcarouterSidecarFullModels: settings.orcarouterSidecarFullModels,
    orcarouterSidecarConnectTimeoutSeconds: settings.orcarouterSidecarConnectTimeoutSeconds,
    orcarouterSidecarRequestTimeoutSeconds: settings.orcarouterSidecarRequestTimeoutSeconds,
    orcarouterSidecarModelsCacheTtlSeconds: settings.orcarouterSidecarModelsCacheTtlSeconds,
    orcarouterSidecarDefaultReasoningEffort: settings.orcarouterSidecarDefaultReasoningEffort ?? null,
    ...(OMNIROUTE_ENABLED
      ? {
          omnirouteSidecarEnabled: settings.omnirouteSidecarEnabled,
          omnirouteSidecarBaseUrl: settings.omnirouteSidecarBaseUrl,
          omnirouteSidecarModelPrefixes: settings.omnirouteSidecarModelPrefixes,
          omnirouteSidecarFullModels: settings.omnirouteSidecarFullModels,
          omnirouteSidecarSelectedModels: settings.omnirouteSidecarSelectedModels,
          omnirouteSidecarConnectTimeoutSeconds: settings.omnirouteSidecarConnectTimeoutSeconds,
          omnirouteSidecarRequestTimeoutSeconds: settings.omnirouteSidecarRequestTimeoutSeconds,
          omnirouteSidecarModelsCacheTtlSeconds: settings.omnirouteSidecarModelsCacheTtlSeconds,
          omnirouteSidecarDefaultReasoningEffort: settings.omnirouteSidecarDefaultReasoningEffort ?? null,
        }
      : {}),
    ollamaSidecarEnabled: settings.ollamaSidecarEnabled,
    ollamaSidecarBaseUrl: settings.ollamaSidecarBaseUrl,
    ollamaSidecarModelPrefixes: settings.ollamaSidecarModelPrefixes,
    ollamaSidecarFullModels: settings.ollamaSidecarFullModels,
    ollamaSidecarConnectTimeoutSeconds: settings.ollamaSidecarConnectTimeoutSeconds,
    ollamaSidecarRequestTimeoutSeconds: settings.ollamaSidecarRequestTimeoutSeconds,
    ollamaSidecarModelsCacheTtlSeconds: settings.ollamaSidecarModelsCacheTtlSeconds,
    ollamaSidecarDefaultReasoningEffort: settings.ollamaSidecarDefaultReasoningEffort ?? null,
    guestAccessEnabled: settings.guestAccessEnabled,
    hideUpstreamQuotaFromApiKeys: settings.hideUpstreamQuotaFromApiKeys,
    ...patch,
  };
  if (payload.expectedVersion === undefined) {
    delete payload.expectedVersion;
  }
  if (
    (payload.stickyReallocationBudgetThresholdPct === undefined ||
      settings.__stickyReallocationBudgetThresholdPctProvided === false) &&
    !("stickyReallocationBudgetThresholdPct" in patch)
  ) {
    delete payload.stickyReallocationBudgetThresholdPct;
  }
  if (
    (payload.stickyReallocationPrimaryBudgetThresholdPct === undefined ||
      settings.__stickyReallocationPrimaryBudgetThresholdPctProvided === false) &&
    !("stickyReallocationPrimaryBudgetThresholdPct" in patch)
  ) {
    delete payload.stickyReallocationPrimaryBudgetThresholdPct;
  }
  if (
    (payload.stickyReallocationSecondaryBudgetThresholdPct === undefined ||
      settings.__stickyReallocationSecondaryBudgetThresholdPctProvided === false) &&
    !("stickyReallocationSecondaryBudgetThresholdPct" in patch)
  ) {
    delete payload.stickyReallocationSecondaryBudgetThresholdPct;
  }
  if (
    "stickyReallocationPrimaryBudgetThresholdPct" in patch &&
    !("stickyReallocationBudgetThresholdPct" in patch) &&
    settings.__stickyReallocationBudgetThresholdPctProvided !== false
  ) {
    payload.stickyReallocationBudgetThresholdPct = patch.stickyReallocationPrimaryBudgetThresholdPct;
  }
  if (!OMNIROUTE_ENABLED) {
    // A disabled capability must never be written, even if a caller passes an
    // OmniRoute field through `patch`. The server rejects these fields too.
    for (const field of OMNIROUTE_UPDATE_FIELDS) {
      delete payload[field];
    }
  }
  return payload;
}
