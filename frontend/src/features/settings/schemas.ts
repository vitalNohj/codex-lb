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
const ClaudeSidecarModelPrefixesSchema = z.array(z.string().trim().min(1).max(64)).min(1).max(32);

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
    claudeSidecarModelPrefixes: ClaudeSidecarModelPrefixesSchema.optional().default(["claude"]),
    claudeSidecarConnectTimeoutSeconds: z.number().positive().optional().default(8),
    claudeSidecarRequestTimeoutSeconds: z.number().positive().optional().default(600),
    claudeSidecarModelsCacheTtlSeconds: z.number().nonnegative().optional().default(60),
    claudeSidecarLastHealthStatus: z.string().nullable().optional().default(null),
    claudeSidecarLastHealthMessage: z.string().nullable().optional().default(null),
    claudeSidecarLastCheckedAt: z.string().datetime({ offset: true }).nullable().optional().default(null),
    claudeSidecarLastModelCount: z.number().int().nonnegative().nullable().optional().default(null),
  })
  .transform((settings) => {
    const legacyProvided = settings.stickyReallocationBudgetThresholdPct !== undefined;
    const primaryProvided = settings.stickyReallocationPrimaryBudgetThresholdPct !== undefined;
    const secondaryProvided = settings.stickyReallocationSecondaryBudgetThresholdPct !== undefined;
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
  claudeSidecarModelPrefixes: ClaudeSidecarModelPrefixesSchema.optional(),
  claudeSidecarConnectTimeoutSeconds: z.number().positive().optional(),
  claudeSidecarRequestTimeoutSeconds: z.number().positive().optional(),
  claudeSidecarModelsCacheTtlSeconds: z.number().nonnegative().optional(),
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
type ClaudeSidecarSettingsFields = Pick<
  ParsedDashboardSettings,
  | "claudeSidecarEnabled"
  | "claudeSidecarBaseUrl"
  | "claudeSidecarApiKeyConfigured"
  | "claudeSidecarModelPrefixes"
  | "claudeSidecarConnectTimeoutSeconds"
  | "claudeSidecarRequestTimeoutSeconds"
  | "claudeSidecarModelsCacheTtlSeconds"
  | "claudeSidecarLastHealthStatus"
  | "claudeSidecarLastHealthMessage"
  | "claudeSidecarLastCheckedAt"
  | "claudeSidecarLastModelCount"
>;

export type DashboardSettings = Omit<
  ParsedDashboardSettings,
  keyof StickyThresholdPresenceFlags | keyof StickyThresholdValues | keyof ClaudeSidecarSettingsFields
> &
  Partial<StickyThresholdPresenceFlags> &
  Partial<StickyThresholdValues> &
  Partial<ClaudeSidecarSettingsFields>;
export type SettingsUpdateRequest = z.infer<typeof SettingsUpdateRequestSchema>;
export type ClaudeSidecarModelSummary = z.infer<typeof ClaudeSidecarModelSummarySchema>;
export type ClaudeSidecarStatusResponse = z.infer<typeof ClaudeSidecarStatusResponseSchema>;
export type ClaudeSidecarTestResponse = z.infer<typeof ClaudeSidecarTestResponseSchema>;
export type ClaudeSidecarModelsResponse = z.infer<typeof ClaudeSidecarModelsResponseSchema>;
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
