import type {
  DashboardSettings,
  SettingsUpdateRequest,
} from "@/features/settings/schemas";

export function buildSettingsUpdateRequest(
  settings: DashboardSettings,
  patch: Partial<SettingsUpdateRequest>,
): SettingsUpdateRequest {
  const payload: SettingsUpdateRequest = {
    stickyThreadsEnabled: settings.stickyThreadsEnabled,
    upstreamStreamTransport: settings.upstreamStreamTransport,
    preferEarlierResetAccounts: settings.preferEarlierResetAccounts,
    preferEarlierResetWindow: settings.preferEarlierResetWindow,
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
    importWithoutOverwrite: settings.importWithoutOverwrite,
    totpRequiredOnLogin: settings.totpRequiredOnLogin,
    apiKeyAuthEnabled: settings.apiKeyAuthEnabled,
    limitWarmupEnabled: settings.limitWarmupEnabled,
    limitWarmupWindows: settings.limitWarmupWindows,
    limitWarmupModel: settings.limitWarmupModel,
    limitWarmupPrompt: settings.limitWarmupPrompt,
    limitWarmupCooldownSeconds: settings.limitWarmupCooldownSeconds,
    limitWarmupMinAvailablePercent: settings.limitWarmupMinAvailablePercent,
    weeklyPaceWorkingDays: settings.weeklyPaceWorkingDays,
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
    omnirouteSidecarEnabled: settings.omnirouteSidecarEnabled,
    omnirouteSidecarBaseUrl: settings.omnirouteSidecarBaseUrl,
    omnirouteSidecarModelPrefixes: settings.omnirouteSidecarModelPrefixes,
    omnirouteSidecarFullModels: settings.omnirouteSidecarFullModels,
    omnirouteSidecarSelectedModels: settings.omnirouteSidecarSelectedModels,
    omnirouteSidecarConnectTimeoutSeconds: settings.omnirouteSidecarConnectTimeoutSeconds,
    omnirouteSidecarRequestTimeoutSeconds: settings.omnirouteSidecarRequestTimeoutSeconds,
    omnirouteSidecarModelsCacheTtlSeconds: settings.omnirouteSidecarModelsCacheTtlSeconds,
    omnirouteSidecarDefaultReasoningEffort: settings.omnirouteSidecarDefaultReasoningEffort ?? null,
    ollamaSidecarEnabled: settings.ollamaSidecarEnabled,
    ollamaSidecarBaseUrl: settings.ollamaSidecarBaseUrl,
    ollamaSidecarModelPrefixes: settings.ollamaSidecarModelPrefixes,
    ollamaSidecarFullModels: settings.ollamaSidecarFullModels,
    ollamaSidecarConnectTimeoutSeconds: settings.ollamaSidecarConnectTimeoutSeconds,
    ollamaSidecarRequestTimeoutSeconds: settings.ollamaSidecarRequestTimeoutSeconds,
    ollamaSidecarModelsCacheTtlSeconds: settings.ollamaSidecarModelsCacheTtlSeconds,
    ollamaSidecarDefaultReasoningEffort: settings.ollamaSidecarDefaultReasoningEffort ?? null,
    guestAccessEnabled: settings.guestAccessEnabled,
    ...patch,
  };
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
  return payload;
}
