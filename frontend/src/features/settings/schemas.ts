import { z } from "zod";

export const RoutingStrategySchema = z.enum([
  "usage_weighted",
  "round_robin",
  "capacity_weighted",
  "sequential_drain",
  "reset_drain",
  "single_account",
  "relative_availability",
  "fill_first",
]);
export const UpstreamStreamTransportSchema = z.enum([
  "default",
  "auto",
  "http",
  "websocket",
]);
export const LimitWarmupWindowsSchema = z.enum([
  "primary",
  "secondary",
  "both",
]);
export const AdditionalQuotaRoutingPolicySchema = z.enum([
  "inherit",
  "normal",
  "burn_first",
  "preserve",
]);
export const AdditionalQuotaPolicySchema = z.object({
  quotaKey: z.string(),
  displayLabel: z.string(),
  routingPolicy: AdditionalQuotaRoutingPolicySchema,
  modelIds: z.array(z.string()).optional().default([]),
});
const LimitWarmupModelSchema = z.string().min(1).max(128);
const LimitWarmupPromptSchema = z.string().min(1).max(512);
const WeeklyPaceWorkingDaysValueSchema = z.string().regex(/^[0-6](,[0-6])*$/);
const WeeklyPaceWorkingDaysSchema = WeeklyPaceWorkingDaysValueSchema.default("0,1,2,3,4,5,6");
const ClaudeSidecarStatusValueSchema = z.enum(["disabled", "missing_api_key", "unreachable", "unauthorized", "healthy", "error"]);
const ThirdPartySidecarStatusValueSchema = z.enum([
  "disabled",
  "missing_api_key",
  "unreachable",
  "unauthorized",
  "healthy",
  "error",
]);
export const SidecarModelPrefixSchema = z.object({
  prefix: z.string().trim().min(1).max(64).transform((value) => value.toLowerCase()),
  strip: z.boolean().optional().default(false),
});
const SidecarModelPrefixesSchema = z.array(SidecarModelPrefixSchema).max(32);
const RequiredSidecarModelPrefixesSchema = SidecarModelPrefixesSchema.min(1);
const SidecarFullModelsSchema = z.array(z.string().trim().min(1).max(256)).max(256);
export const ClaudeSidecarPlanTypeSchema = z.enum(["pro", "max5", "max20", "custom"]);
export const ClaudeSidecarAuthPlanSchema = z.object({
  authIndex: z.string().trim().min(1).max(255).nullable().optional(),
  email: z.string().trim().min(1).max(255).nullable().optional(),
  source: z.string().trim().min(1).max(255).nullable().optional(),
  planType: ClaudeSidecarPlanTypeSchema,
  primaryTokenBudget: z.number().int().positive().nullable().optional(),
  secondaryTokenBudget: z.number().int().positive().nullable().optional(),
});

export const DashboardSettingsSchema = z
  .object({
    stickyThreadsEnabled: z.boolean(),
    upstreamStreamTransport:
      UpstreamStreamTransportSchema.optional().default("default"),
    upstreamProxyRoutingEnabled: z.boolean().optional().default(false),
    upstreamProxyDefaultPoolId: z.string().nullable().optional().default(null),
    preferEarlierResetAccounts: z.boolean(),
    preferEarlierResetWindow: z.enum(["primary", "secondary"]).optional().default("secondary"),
    routingStrategy: RoutingStrategySchema.optional().default("usage_weighted"),
    relativeAvailabilityPower: z.number().positive().optional().default(2),
    relativeAvailabilityTopK: z
      .number()
      .int()
      .min(1)
      .max(20)
      .optional()
      .default(5),
    singleAccountId: z.string().nullable().optional().default(null),
    openaiCacheAffinityMaxAgeSeconds: z
      .number()
      .int()
      .positive()
      .optional()
      .default(300),
    dashboardSessionTtlSeconds: z
      .number()
      .int()
      .min(3600)
      .optional()
      .default(43200),
    stickyReallocationBudgetThresholdPct: z.number().min(0).max(100).optional(),
    stickyReallocationPrimaryBudgetThresholdPct: z.number().min(0).max(100).optional(),
    stickyReallocationSecondaryBudgetThresholdPct: z.number().min(0).max(100).optional(),
    additionalQuotaRoutingPolicies: z
      .record(z.string(), AdditionalQuotaRoutingPolicySchema)
      .optional(),
    additionalQuotaPolicies: z.array(AdditionalQuotaPolicySchema).optional().default([]),
    warmupModel: z.string().trim().min(1).optional().default("gpt-5.4-mini"),
    importWithoutOverwrite: z.boolean(),
    totpRequiredOnLogin: z.boolean(),
    totpConfigured: z.boolean(),
    apiKeyAuthEnabled: z.boolean(),
    limitWarmupEnabled: z.boolean().optional().default(false),
    limitWarmupWindows: LimitWarmupWindowsSchema.optional().default("both"),
    limitWarmupModel: LimitWarmupModelSchema.optional().default("auto"),
    limitWarmupPrompt: LimitWarmupPromptSchema.optional().default("Say OK."),
    limitWarmupCooldownSeconds: z.number().int().min(60).optional().default(3600),
    limitWarmupMinAvailablePercent: z
      .number()
      .positive()
      .max(100)
      .optional()
      .default(100),
    weeklyPaceWorkingDays: WeeklyPaceWorkingDaysSchema,
    claudeSidecarEnabled: z.boolean().optional().default(false),
    claudeSidecarBaseUrl: z.string().trim().min(1).optional().default("http://127.0.0.1:8317"),
    claudeSidecarApiKeyConfigured: z.boolean().optional().default(false),
    claudeSidecarModelPrefixes: RequiredSidecarModelPrefixesSchema.optional().default([
      { prefix: "claude", strip: false },
      { prefix: "cp-", strip: true },
      { prefix: "cp_", strip: true },
    ]),
    claudeSidecarFullModels: SidecarFullModelsSchema.optional().default([]),
    claudeSidecarConnectTimeoutSeconds: z.number().positive().optional().default(8),
    claudeSidecarRequestTimeoutSeconds: z.number().positive().optional().default(600),
    claudeSidecarModelsCacheTtlSeconds: z.number().nonnegative().optional().default(60),
    claudeSidecarLastHealthStatus: z.string().nullable().optional().default(null),
    claudeSidecarLastHealthMessage: z.string().nullable().optional().default(null),
    claudeSidecarLastCheckedAt: z.string().datetime({ offset: true }).nullable().optional().default(null),
    claudeSidecarLastModelCount: z.number().int().nonnegative().nullable().optional().default(null),
    claudeSidecarManagementKeyConfigured: z.boolean().optional().default(false),
    claudeSidecarQuotaPollIntervalSeconds: z.number().positive().optional().default(60),
    claudeSidecarAuthPlans: z.array(ClaudeSidecarAuthPlanSchema).optional().default([]),
    claudeSidecarUsagePollIntervalSeconds: z.number().positive().optional().default(15),
    claudeSidecarUsageQueueBatchSize: z.number().int().positive().optional().default(100),
    claudeSidecarUsageCollectionEnabled: z.boolean().optional().default(true),
    openrouterSidecarEnabled: z.boolean().optional().default(false),
    openrouterSidecarBaseUrl: z.string().trim().min(1).optional().default("https://openrouter.ai/api/v1"),
    openrouterSidecarApiKeyConfigured: z.boolean().optional().default(false),
    openrouterSidecarModelPrefixes: SidecarModelPrefixesSchema.optional().default([]),
    openrouterSidecarFullModels: SidecarFullModelsSchema.optional().default([]),
    openrouterSidecarConnectTimeoutSeconds: z.number().positive().optional().default(8),
    openrouterSidecarRequestTimeoutSeconds: z.number().positive().optional().default(600),
    openrouterSidecarModelsCacheTtlSeconds: z.number().nonnegative().optional().default(60),
    openrouterSidecarLastHealthStatus: z.string().nullable().optional().default(null),
    openrouterSidecarLastHealthMessage: z.string().nullable().optional().default(null),
    openrouterSidecarLastCheckedAt: z.string().datetime({ offset: true }).nullable().optional().default(null),
    openrouterSidecarLastModelCount: z.number().int().nonnegative().nullable().optional().default(null),
    omnirouteSidecarEnabled: z.boolean().optional().default(false),
    omnirouteSidecarBaseUrl: z.string().trim().min(1).optional().default("http://127.0.0.1:20128/v1"),
    omnirouteSidecarApiKeyConfigured: z.boolean().optional().default(false),
    omnirouteSidecarModelPrefixes: SidecarModelPrefixesSchema.optional().default([]),
    omnirouteSidecarFullModels: SidecarFullModelsSchema.optional().default([]),
    omnirouteSidecarSelectedModels: SidecarFullModelsSchema.optional().default([]),
    omnirouteSidecarConnectTimeoutSeconds: z.number().positive().optional().default(8),
    omnirouteSidecarRequestTimeoutSeconds: z.number().positive().optional().default(600),
    omnirouteSidecarModelsCacheTtlSeconds: z.number().nonnegative().optional().default(60),
    omnirouteSidecarLastHealthStatus: z.string().nullable().optional().default(null),
    omnirouteSidecarLastHealthMessage: z.string().nullable().optional().default(null),
    omnirouteSidecarLastCheckedAt: z.string().datetime({ offset: true }).nullable().optional().default(null),
    omnirouteSidecarLastModelCount: z.number().int().nonnegative().nullable().optional().default(null),
    ollamaSidecarEnabled: z.boolean().optional().default(false),
    ollamaSidecarBaseUrl: z.string().trim().min(1).optional().default("https://ollama.com"),
    ollamaSidecarApiKeyConfigured: z.boolean().optional().default(false),
    ollamaSidecarModelPrefixes: SidecarModelPrefixesSchema.optional().default([]),
    ollamaSidecarFullModels: SidecarFullModelsSchema.optional().default([]),
    ollamaSidecarConnectTimeoutSeconds: z.number().positive().optional().default(8),
    ollamaSidecarRequestTimeoutSeconds: z.number().positive().optional().default(600),
    ollamaSidecarModelsCacheTtlSeconds: z.number().nonnegative().optional().default(60),
    ollamaSidecarLastHealthStatus: z.string().nullable().optional().default(null),
    ollamaSidecarLastHealthMessage: z.string().nullable().optional().default(null),
    ollamaSidecarLastCheckedAt: z.string().datetime({ offset: true }).nullable().optional().default(null),
    ollamaSidecarLastModelCount: z.number().int().nonnegative().nullable().optional().default(null),
  })
  .transform((settings) => {
    const legacyProvided = settings.stickyReallocationBudgetThresholdPct !== undefined;
    const primaryProvided = settings.stickyReallocationPrimaryBudgetThresholdPct !== undefined;
    const secondaryProvided = settings.stickyReallocationSecondaryBudgetThresholdPct !== undefined;
    const omnirouteFullModels =
      settings.omnirouteSidecarFullModels.length > 0
        ? settings.omnirouteSidecarFullModels
        : settings.omnirouteSidecarSelectedModels;
    const primaryThreshold =
      settings.stickyReallocationPrimaryBudgetThresholdPct ??
      settings.stickyReallocationBudgetThresholdPct ??
      95;
    return {
      ...settings,
      stickyReallocationBudgetThresholdPct:
        settings.stickyReallocationBudgetThresholdPct ?? primaryThreshold,
      stickyReallocationPrimaryBudgetThresholdPct: primaryThreshold,
      stickyReallocationSecondaryBudgetThresholdPct:
        settings.stickyReallocationSecondaryBudgetThresholdPct ??
        settings.stickyReallocationBudgetThresholdPct ??
        100,
      __stickyReallocationBudgetThresholdPctProvided: legacyProvided,
      __stickyReallocationPrimaryBudgetThresholdPctProvided: primaryProvided,
      __stickyReallocationSecondaryBudgetThresholdPctProvided: secondaryProvided,
      omnirouteSidecarFullModels: omnirouteFullModels,
      omnirouteSidecarSelectedModels:
        settings.omnirouteSidecarSelectedModels.length > 0
          ? settings.omnirouteSidecarSelectedModels
          : omnirouteFullModels,
    };
  });

export const SettingsUpdateRequestSchema = z.object({
  stickyThreadsEnabled: z.boolean().optional(),
  upstreamStreamTransport: UpstreamStreamTransportSchema.optional(),
  upstreamProxyRoutingEnabled: z.boolean().optional(),
  upstreamProxyDefaultPoolId: z.string().nullable().optional(),
  preferEarlierResetAccounts: z.boolean().optional(),
  preferEarlierResetWindow: z.enum(["primary", "secondary"]).optional(),
  routingStrategy: RoutingStrategySchema.optional(),
  relativeAvailabilityPower: z.number().positive().optional(),
  relativeAvailabilityTopK: z.number().int().min(1).max(20).optional(),
  singleAccountId: z.string().nullable().optional(),
  openaiCacheAffinityMaxAgeSeconds: z.number().int().positive().optional(),
  dashboardSessionTtlSeconds: z.number().int().min(3600).optional(),
  stickyReallocationBudgetThresholdPct: z.number().min(0).max(100).optional(),
  stickyReallocationPrimaryBudgetThresholdPct: z.number().min(0).max(100).optional(),
  stickyReallocationSecondaryBudgetThresholdPct: z.number().min(0).max(100).optional(),
  additionalQuotaRoutingPolicies: z
    .record(z.string(), AdditionalQuotaRoutingPolicySchema)
    .optional(),
  warmupModel: z.string().trim().min(1).optional(),
  importWithoutOverwrite: z.boolean().optional(),
  totpRequiredOnLogin: z.boolean().optional(),
  apiKeyAuthEnabled: z.boolean().optional(),
  limitWarmupEnabled: z.boolean().optional(),
  limitWarmupWindows: LimitWarmupWindowsSchema.optional(),
  limitWarmupModel: LimitWarmupModelSchema.optional(),
  limitWarmupPrompt: LimitWarmupPromptSchema.optional(),
  limitWarmupCooldownSeconds: z.number().int().min(60).optional(),
  limitWarmupMinAvailablePercent: z.number().positive().max(100).optional(),
  weeklyPaceWorkingDays: WeeklyPaceWorkingDaysValueSchema.optional(),
  claudeSidecarEnabled: z.boolean().optional(),
  claudeSidecarBaseUrl: z.string().trim().min(1).max(2048).optional(),
  claudeSidecarApiKey: z.string().trim().max(4096).optional(),
  claudeSidecarClearApiKey: z.boolean().optional(),
  claudeSidecarModelPrefixes: RequiredSidecarModelPrefixesSchema.optional(),
  claudeSidecarFullModels: SidecarFullModelsSchema.optional(),
  claudeSidecarConnectTimeoutSeconds: z.number().positive().optional(),
  claudeSidecarRequestTimeoutSeconds: z.number().positive().optional(),
  claudeSidecarModelsCacheTtlSeconds: z.number().nonnegative().optional(),
  claudeSidecarManagementKey: z.string().trim().max(4096).optional(),
  claudeSidecarClearManagementKey: z.boolean().optional(),
  claudeSidecarQuotaPollIntervalSeconds: z.number().positive().optional(),
  claudeSidecarAuthPlans: z.array(ClaudeSidecarAuthPlanSchema).optional(),
  claudeSidecarUsagePollIntervalSeconds: z.number().positive().optional(),
  claudeSidecarUsageQueueBatchSize: z.number().int().positive().max(1000).optional(),
  claudeSidecarUsageCollectionEnabled: z.boolean().optional(),
  openrouterSidecarEnabled: z.boolean().optional(),
  openrouterSidecarBaseUrl: z.string().trim().min(1).max(2048).optional(),
  openrouterSidecarApiKey: z.string().trim().max(4096).optional(),
  openrouterSidecarClearApiKey: z.boolean().optional(),
  openrouterSidecarModelPrefixes: SidecarModelPrefixesSchema.optional(),
  openrouterSidecarFullModels: SidecarFullModelsSchema.optional(),
  openrouterSidecarConnectTimeoutSeconds: z.number().positive().optional(),
  openrouterSidecarRequestTimeoutSeconds: z.number().positive().optional(),
  openrouterSidecarModelsCacheTtlSeconds: z.number().nonnegative().optional(),
  omnirouteSidecarEnabled: z.boolean().optional(),
  omnirouteSidecarBaseUrl: z.string().trim().min(1).max(2048).optional(),
  omnirouteSidecarApiKey: z.string().trim().max(4096).optional(),
  omnirouteSidecarClearApiKey: z.boolean().optional(),
  omnirouteSidecarModelPrefixes: SidecarModelPrefixesSchema.optional(),
  omnirouteSidecarFullModels: SidecarFullModelsSchema.optional(),
  omnirouteSidecarSelectedModels: SidecarFullModelsSchema.optional(),
  omnirouteSidecarConnectTimeoutSeconds: z.number().positive().optional(),
  omnirouteSidecarRequestTimeoutSeconds: z.number().positive().optional(),
  omnirouteSidecarModelsCacheTtlSeconds: z.number().nonnegative().optional(),
  ollamaSidecarEnabled: z.boolean().optional(),
  ollamaSidecarBaseUrl: z.string().trim().min(1).max(2048).optional(),
  ollamaSidecarApiKey: z.string().trim().max(4096).optional(),
  ollamaSidecarClearApiKey: z.boolean().optional(),
  ollamaSidecarModelPrefixes: SidecarModelPrefixesSchema.optional(),
  ollamaSidecarFullModels: SidecarFullModelsSchema.optional(),
  ollamaSidecarConnectTimeoutSeconds: z.number().positive().optional(),
  ollamaSidecarRequestTimeoutSeconds: z.number().positive().optional(),
  ollamaSidecarModelsCacheTtlSeconds: z.number().nonnegative().optional(),
});

export const ClaudeSidecarModelSummarySchema = z.object({
  id: z.string(),
  created: z.number().int().nullable().optional(),
  ownedBy: z.string().nullable().optional(),
});

export const ClaudeSidecarStatusResponseSchema = z.object({
  enabled: z.boolean(),
  configured: z.boolean(),
  status: ClaudeSidecarStatusValueSchema,
  message: z.string().nullable().optional(),
  baseUrl: z.string(),
  modelCount: z.number().int().nonnegative().nullable().optional(),
  lastCheckedAt: z.string().datetime({ offset: true }).nullable().optional(),
});
export const ClaudeSidecarTestResponseSchema = ClaudeSidecarStatusResponseSchema.extend({
  models: z.array(ClaudeSidecarModelSummarySchema).default([]),
});
export const ClaudeSidecarModelsResponseSchema = z.object({
  models: z.array(ClaudeSidecarModelSummarySchema).default([]),
});

const OpenRouterSidecarStatusValueSchema = ThirdPartySidecarStatusValueSchema;

export const OpenRouterSidecarModelSummarySchema = z.object({
  id: z.string(),
  created: z.number().int().nullable().optional(),
  ownedBy: z.string().nullable().optional(),
});

export const OpenRouterSidecarStatusResponseSchema = z.object({
  enabled: z.boolean(),
  configured: z.boolean(),
  status: OpenRouterSidecarStatusValueSchema,
  message: z.string().nullable().optional(),
  baseUrl: z.string(),
  modelCount: z.number().int().nonnegative().nullable().optional(),
  lastCheckedAt: z.string().datetime({ offset: true }).nullable().optional(),
});

export const OpenRouterSidecarTestResponseSchema = OpenRouterSidecarStatusResponseSchema.extend({
  models: z.array(OpenRouterSidecarModelSummarySchema).default([]),
});

export const OpenRouterSidecarModelsResponseSchema = z.object({
  models: z.array(OpenRouterSidecarModelSummarySchema).default([]),
});

const OmniRouteSidecarStatusValueSchema = ThirdPartySidecarStatusValueSchema;

export const OmniRouteSidecarModelSummarySchema = z.object({
  id: z.string(),
  created: z.number().int().nullable().optional(),
  ownedBy: z.string().nullable().optional(),
});

export const OmniRouteSidecarStatusResponseSchema = z.object({
  enabled: z.boolean(),
  configured: z.boolean(),
  status: OmniRouteSidecarStatusValueSchema,
  message: z.string().nullable().optional(),
  baseUrl: z.string(),
  modelCount: z.number().int().nonnegative().nullable().optional(),
  lastCheckedAt: z.string().datetime({ offset: true }).nullable().optional(),
});

export const OmniRouteSidecarTestResponseSchema = OmniRouteSidecarStatusResponseSchema.extend({
  models: z.array(OmniRouteSidecarModelSummarySchema).default([]),
});

export const OmniRouteSidecarModelsResponseSchema = z.object({
  models: z.array(OmniRouteSidecarModelSummarySchema).default([]),
});

export const OllamaSidecarModelSummarySchema = z.object({
  id: z.string(),
  created: z.number().int().nullable().optional(),
  ownedBy: z.string().nullable().optional(),
});

export const OllamaSidecarStatusResponseSchema = z.object({
  enabled: z.boolean(),
  configured: z.boolean(),
  status: ThirdPartySidecarStatusValueSchema,
  message: z.string().nullable().optional(),
  baseUrl: z.string(),
  modelCount: z.number().int().nonnegative().nullable().optional(),
  lastCheckedAt: z.string().datetime({ offset: true }).nullable().optional(),
});

export const OllamaSidecarTestResponseSchema = OllamaSidecarStatusResponseSchema.extend({
  models: z.array(OllamaSidecarModelSummarySchema).default([]),
});

export const OllamaSidecarModelsResponseSchema = z.object({
  models: z.array(OllamaSidecarModelSummarySchema).default([]),
});

const ClaudeSidecarQuotaStatusSchema = z.enum([
  "healthy",
  "unauthorized",
  "unreachable",
  "error",
  "unknown",
  "disabled",
  "not_configured",
]);

export const ClaudeSidecarQuotaAuthSchema = z.object({
  name: z.string(),
  authIndex: z.string().nullable().optional(),
  email: z.string().nullable().optional(),
  status: z.string().nullable().optional(),
  quotaExceeded: z.boolean().default(false),
  nextRecoverAt: z.string().datetime({ offset: true }).nullable().optional(),
  modelsExceeded: z.array(z.string()).default([]),
  success: z.number().int().nonnegative().default(0),
  failed: z.number().int().nonnegative().default(0),
  planType: z.string().nullable().optional(),
  usageSource: z.string().nullable().optional(),
  primaryRemainingPercent: z.number().nullable().optional(),
  secondaryRemainingPercent: z.number().nullable().optional(),
  primaryUsedTokens: z.number().int().nonnegative().nullable().optional(),
  secondaryUsedTokens: z.number().int().nonnegative().nullable().optional(),
  primaryTokenBudget: z.number().int().positive().nullable().optional(),
  secondaryTokenBudget: z.number().int().positive().nullable().optional(),
  resetAtPrimary: z.string().datetime({ offset: true }).nullable().optional(),
  resetAtSecondary: z.string().datetime({ offset: true }).nullable().optional(),
  confidence: z.string().nullable().optional(),
});

export const ClaudeSidecarQuotaResponseSchema = z.object({
  status: ClaudeSidecarQuotaStatusSchema,
  message: z.string().nullable().optional(),
  checkedAt: z.string().datetime({ offset: true }).nullable().optional(),
  accounts: z.array(ClaudeSidecarQuotaAuthSchema).default([]),
});

type ParsedDashboardSettings = z.infer<typeof DashboardSettingsSchema>;
type StickyThresholdPresenceFlags = Pick<
  ParsedDashboardSettings,
  | "__stickyReallocationBudgetThresholdPctProvided"
  | "__stickyReallocationPrimaryBudgetThresholdPctProvided"
  | "__stickyReallocationSecondaryBudgetThresholdPctProvided"
>;
type StickyThresholdValues = Pick<
  ParsedDashboardSettings,
  | "stickyReallocationBudgetThresholdPct"
  | "stickyReallocationPrimaryBudgetThresholdPct"
  | "stickyReallocationSecondaryBudgetThresholdPct"
>;
type OpenRouterSidecarSettingsFields = Pick<
  ParsedDashboardSettings,
  | "openrouterSidecarEnabled"
  | "openrouterSidecarBaseUrl"
  | "openrouterSidecarApiKeyConfigured"
  | "openrouterSidecarModelPrefixes"
  | "openrouterSidecarFullModels"
  | "openrouterSidecarConnectTimeoutSeconds"
  | "openrouterSidecarRequestTimeoutSeconds"
  | "openrouterSidecarModelsCacheTtlSeconds"
  | "openrouterSidecarLastHealthStatus"
  | "openrouterSidecarLastHealthMessage"
  | "openrouterSidecarLastCheckedAt"
  | "openrouterSidecarLastModelCount"
>;

type OmniRouteSidecarSettingsFields = Pick<
  ParsedDashboardSettings,
  | "omnirouteSidecarEnabled"
  | "omnirouteSidecarBaseUrl"
  | "omnirouteSidecarApiKeyConfigured"
  | "omnirouteSidecarModelPrefixes"
  | "omnirouteSidecarFullModels"
  | "omnirouteSidecarSelectedModels"
  | "omnirouteSidecarConnectTimeoutSeconds"
  | "omnirouteSidecarRequestTimeoutSeconds"
  | "omnirouteSidecarModelsCacheTtlSeconds"
  | "omnirouteSidecarLastHealthStatus"
  | "omnirouteSidecarLastHealthMessage"
  | "omnirouteSidecarLastCheckedAt"
  | "omnirouteSidecarLastModelCount"
>;

type OllamaSidecarSettingsFields = Pick<
  ParsedDashboardSettings,
  | "ollamaSidecarEnabled"
  | "ollamaSidecarBaseUrl"
  | "ollamaSidecarApiKeyConfigured"
  | "ollamaSidecarModelPrefixes"
  | "ollamaSidecarFullModels"
  | "ollamaSidecarConnectTimeoutSeconds"
  | "ollamaSidecarRequestTimeoutSeconds"
  | "ollamaSidecarModelsCacheTtlSeconds"
  | "ollamaSidecarLastHealthStatus"
  | "ollamaSidecarLastHealthMessage"
  | "ollamaSidecarLastCheckedAt"
  | "ollamaSidecarLastModelCount"
>;

type ClaudeSidecarSettingsFields = Pick<
  ParsedDashboardSettings,
  | "claudeSidecarEnabled"
  | "claudeSidecarBaseUrl"
  | "claudeSidecarApiKeyConfigured"
  | "claudeSidecarModelPrefixes"
  | "claudeSidecarFullModels"
  | "claudeSidecarConnectTimeoutSeconds"
  | "claudeSidecarRequestTimeoutSeconds"
  | "claudeSidecarModelsCacheTtlSeconds"
  | "claudeSidecarLastHealthStatus"
  | "claudeSidecarLastHealthMessage"
  | "claudeSidecarLastCheckedAt"
  | "claudeSidecarLastModelCount"
  | "claudeSidecarManagementKeyConfigured"
  | "claudeSidecarQuotaPollIntervalSeconds"
  | "claudeSidecarAuthPlans"
  | "claudeSidecarUsagePollIntervalSeconds"
  | "claudeSidecarUsageQueueBatchSize"
  | "claudeSidecarUsageCollectionEnabled"
>;

export type DashboardSettings = Omit<
  ParsedDashboardSettings,
  | keyof StickyThresholdPresenceFlags
  | keyof StickyThresholdValues
  | keyof ClaudeSidecarSettingsFields
  | keyof OpenRouterSidecarSettingsFields
  | keyof OmniRouteSidecarSettingsFields
  | keyof OllamaSidecarSettingsFields
> &
  Partial<StickyThresholdPresenceFlags> &
  Partial<StickyThresholdValues> &
  Partial<ClaudeSidecarSettingsFields> &
  Partial<OpenRouterSidecarSettingsFields> &
  Partial<OmniRouteSidecarSettingsFields> &
  Partial<OllamaSidecarSettingsFields>;
export type SettingsUpdateRequest = z.infer<typeof SettingsUpdateRequestSchema>;
export type SidecarModelPrefix = z.infer<typeof SidecarModelPrefixSchema>;
export type ClaudeSidecarModelSummary = z.infer<typeof ClaudeSidecarModelSummarySchema>;
export type ClaudeSidecarStatusResponse = z.infer<typeof ClaudeSidecarStatusResponseSchema>;
export type ClaudeSidecarTestResponse = z.infer<typeof ClaudeSidecarTestResponseSchema>;
export type ClaudeSidecarModelsResponse = z.infer<typeof ClaudeSidecarModelsResponseSchema>;
export type ClaudeSidecarQuotaResponse = z.infer<typeof ClaudeSidecarQuotaResponseSchema>;
export type ClaudeSidecarQuotaAuth = z.infer<typeof ClaudeSidecarQuotaAuthSchema>;
export type ClaudeSidecarAuthPlan = z.infer<typeof ClaudeSidecarAuthPlanSchema>;
export type ClaudeSidecarPlanType = z.infer<typeof ClaudeSidecarPlanTypeSchema>;
export type OpenRouterSidecarModelSummary = z.infer<typeof OpenRouterSidecarModelSummarySchema>;
export type OpenRouterSidecarStatusResponse = z.infer<typeof OpenRouterSidecarStatusResponseSchema>;
export type OpenRouterSidecarTestResponse = z.infer<typeof OpenRouterSidecarTestResponseSchema>;
export type OpenRouterSidecarModelsResponse = z.infer<typeof OpenRouterSidecarModelsResponseSchema>;
export type OmniRouteSidecarModelSummary = z.infer<typeof OmniRouteSidecarModelSummarySchema>;
export type OmniRouteSidecarStatusResponse = z.infer<typeof OmniRouteSidecarStatusResponseSchema>;
export type OmniRouteSidecarTestResponse = z.infer<typeof OmniRouteSidecarTestResponseSchema>;
export type OmniRouteSidecarModelsResponse = z.infer<typeof OmniRouteSidecarModelsResponseSchema>;
export type OllamaSidecarModelSummary = z.infer<typeof OllamaSidecarModelSummarySchema>;
export type OllamaSidecarStatusResponse = z.infer<typeof OllamaSidecarStatusResponseSchema>;
export type OllamaSidecarTestResponse = z.infer<typeof OllamaSidecarTestResponseSchema>;
export type OllamaSidecarModelsResponse = z.infer<typeof OllamaSidecarModelsResponseSchema>;
export type AdditionalQuotaRoutingPolicy = z.infer<typeof AdditionalQuotaRoutingPolicySchema>;

export const UpstreamProxyEndpointSchema = z.object({
  id: z.string(),
  name: z.string(),
  scheme: z.enum(["http", "https", "socks5", "socks5h"]),
  host: z.string(),
  port: z.number().int(),
  username: z.string().nullable().optional(),
  isActive: z.boolean(),
});

export const UpstreamProxyEndpointCreateRequestSchema = z.object({
  name: z.string().trim().min(1).max(128),
  scheme: z.enum(["http", "https", "socks5", "socks5h"]),
  host: z.string().trim().min(1).max(255),
  port: z.number().int().min(1).max(65535),
  username: z.string().trim().max(255).nullable().optional(),
  password: z.string().max(1024).nullable().optional(),
  isActive: z.boolean().optional().default(true),
});

export const UpstreamProxyPoolSchema = z.object({
  id: z.string(),
  name: z.string(),
  isActive: z.boolean(),
  endpointIds: z.array(z.string()),
});

export const UpstreamProxyPoolCreateRequestSchema = z.object({
  name: z.string().trim().min(1).max(128),
  endpointIds: z.array(z.string()).default([]),
  isActive: z.boolean().optional().default(true),
});

export const UpstreamProxyPoolMemberRequestSchema = z.object({
  endpointId: z.string().min(1),
  sortOrder: z.number().int().optional().default(0),
  weight: z.number().int().min(1).optional().default(1),
  isActive: z.boolean().optional().default(true),
});

export const AccountProxyBindingSchema = z.object({
  accountId: z.string(),
  poolId: z.string(),
  isActive: z.boolean(),
});

export const AccountProxyBindingRequestSchema = z.object({
  poolId: z.string().min(1),
  isActive: z.boolean().optional().default(true),
});

export const UpstreamProxyAdminSchema = z.object({
  routingEnabled: z.boolean(),
  defaultPoolId: z.string().nullable(),
  endpoints: z.array(UpstreamProxyEndpointSchema),
  pools: z.array(UpstreamProxyPoolSchema),
  bindings: z.array(AccountProxyBindingSchema),
});

export type UpstreamProxyEndpoint = z.infer<typeof UpstreamProxyEndpointSchema>;
export type UpstreamProxyEndpointCreateRequest = z.infer<typeof UpstreamProxyEndpointCreateRequestSchema>;
export type UpstreamProxyPool = z.infer<typeof UpstreamProxyPoolSchema>;
export type UpstreamProxyPoolCreateRequest = z.infer<typeof UpstreamProxyPoolCreateRequestSchema>;
export type UpstreamProxyPoolMemberRequest = z.infer<typeof UpstreamProxyPoolMemberRequestSchema>;
export type AccountProxyBinding = z.infer<typeof AccountProxyBindingSchema>;
export type AccountProxyBindingRequest = z.infer<typeof AccountProxyBindingRequestSchema>;
export type UpstreamProxyAdmin = z.infer<typeof UpstreamProxyAdminSchema>;
