import { z } from "zod";

export const FreeModelProviderSchema = z.enum(["openrouter", "orcarouter"]);
export const FreeModelCandidateGroupSchema = z.enum(["new", "unresolved", "due", "cooldown"]);
export const FreeModelRunStatusSchema = z.enum(["running", "completed", "cancelled", "expired", "failed"]);
export const FreeModelItemStateSchema = z.enum(["queued", "passed", "failed", "unresolved"]);
export const FreeModelProviderPlanStatusSchema = z.enum(["ok", "disabled", "missing_api_key", "unreachable", "error"]);
// What the vendor EXPLICITLY attributed a rate-limit rejection to. "unknown"
// is the honest default: a bare 429/402 or a generic message proves nothing.
export const FreeModelLimitScopeSchema = z.enum(["shared", "model", "unknown"]);

export const FreeModelCandidateSchema = z.object({
  provider: FreeModelProviderSchema,
  modelId: z.string(),
  group: FreeModelCandidateGroupSchema,
  ownedBy: z.string().nullable().optional().default(null),
  lastVerdict: z.enum(["passed", "failed"]).nullable().optional().default(null),
  lastVerdictAt: z.string().nullable().optional().default(null),
  failureStreak: z.number().int().nonnegative().optional().default(0),
  cooldownUntil: z.string().nullable().optional().default(null),
});

export const FreeModelProviderPlanSchema = z.object({
  provider: FreeModelProviderSchema,
  status: FreeModelProviderPlanStatusSchema,
  message: z.string().nullable().optional().default(null),
  discoveredCount: z.number().int().nonnegative().optional().default(0),
  freeCount: z.number().int().nonnegative().optional().default(0),
  alreadyPinnedCount: z.number().int().nonnegative().optional().default(0),
  skippedSelectorCount: z.number().int().nonnegative().optional().default(0),
  candidates: z.array(FreeModelCandidateSchema).optional().default([]),
});

export const FreeModelDiscoveryPlanSchema = z.object({
  generatedAt: z.string(),
  providers: z.array(FreeModelProviderPlanSchema).optional().default([]),
  activeRunId: z.string().nullable().optional().default(null),
});

export const FreeModelDiscoveryStartRequestSchema = z.object({
  selections: z
    .array(
      z.object({
        provider: FreeModelProviderSchema,
        modelId: z.string().min(1),
      }),
    )
    .min(1),
});

export const FreeModelDiscoveryRunCountsSchema = z.object({
  total: z.number().int().nonnegative().optional().default(0),
  queued: z.number().int().nonnegative().optional().default(0),
  passed: z.number().int().nonnegative().optional().default(0),
  failed: z.number().int().nonnegative().optional().default(0),
  unresolved: z.number().int().nonnegative().optional().default(0),
  added: z.number().int().nonnegative().optional().default(0),
  // Split of `queued`: never-attempted vs. probed-and-retrying.
  awaitingFirstAttempt: z.number().int().nonnegative().optional().default(0),
  retrying: z.number().int().nonnegative().optional().default(0),
});

export const FreeModelDiscoveryRunItemSchema = z.object({
  provider: FreeModelProviderSchema,
  modelId: z.string(),
  group: FreeModelCandidateGroupSchema,
  state: FreeModelItemStateSchema,
  attempts: z.number().int().nonnegative(),
  nextAttemptAt: z.string().nullable().optional().default(null),
  lastAttemptAt: z.string().nullable().optional().default(null),
  lastHttpStatus: z.number().int().nullable().optional().default(null),
  lastOutcome: z.string().nullable().optional().default(null),
  contentChars: z.number().int().nullable().optional().default(null),
  contentOkMatch: z.boolean().nullable().optional().default(null),
  reasoningChars: z.number().int().nullable().optional().default(null),
  addedToFullModels: z.boolean().optional().default(false),
  resolvedAt: z.string().nullable().optional().default(null),
  limitScope: FreeModelLimitScopeSchema.nullable().optional().default(null),
});

export const FreeModelDiscoveryProviderProgressSchema = z.object({
  provider: FreeModelProviderSchema,
  counts: FreeModelDiscoveryRunCountsSchema,
  currentIntervalSeconds: z.number().nullable().optional().default(null),
  nextProbeAt: z.string().nullable().optional().default(null),
  waitingReason: z.string().nullable().optional().default(null),
  limitScope: FreeModelLimitScopeSchema.nullable().optional().default(null),
  providerPaused: z.boolean().optional().default(false),
});

export const FreeModelDiscoveryRunSchema = z.object({
  id: z.string(),
  status: FreeModelRunStatusSchema,
  startedAt: z.string(),
  finishedAt: z.string().nullable().optional().default(null),
  deadlineAt: z.string(),
  cancelRequested: z.boolean().optional().default(false),
  pacingFloorSeconds: z.number(),
  pacingCapSeconds: z.number(),
  maxAttemptsPerItem: z.number().int(),
  errorMessage: z.string().nullable().optional().default(null),
  counts: FreeModelDiscoveryRunCountsSchema,
  providers: z.array(FreeModelDiscoveryProviderProgressSchema).optional().default([]),
  items: z.array(FreeModelDiscoveryRunItemSchema).optional().default([]),
});

export const FreeModelDiscoveryCurrentRunSchema = FreeModelDiscoveryRunSchema.nullable();

export type FreeModelProvider = z.infer<typeof FreeModelProviderSchema>;
export type FreeModelCandidateGroup = z.infer<typeof FreeModelCandidateGroupSchema>;
export type FreeModelRunStatus = z.infer<typeof FreeModelRunStatusSchema>;
export type FreeModelItemState = z.infer<typeof FreeModelItemStateSchema>;
export type FreeModelLimitScope = z.infer<typeof FreeModelLimitScopeSchema>;
export type FreeModelCandidate = z.infer<typeof FreeModelCandidateSchema>;
export type FreeModelProviderPlan = z.infer<typeof FreeModelProviderPlanSchema>;
export type FreeModelDiscoveryPlan = z.infer<typeof FreeModelDiscoveryPlanSchema>;
export type FreeModelDiscoveryStartRequest = z.infer<typeof FreeModelDiscoveryStartRequestSchema>;
export type FreeModelDiscoveryRun = z.infer<typeof FreeModelDiscoveryRunSchema>;
export type FreeModelDiscoveryRunItem = z.infer<typeof FreeModelDiscoveryRunItemSchema>;
export type FreeModelDiscoveryRunCounts = z.infer<typeof FreeModelDiscoveryRunCountsSchema>;
