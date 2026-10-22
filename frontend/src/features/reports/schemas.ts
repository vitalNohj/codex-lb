import { z } from "zod";

const DailyReportRowSchema = z.object({
  date: z.string(),
  requests: z.number(),
  conversations: z.number(),
  inputTokens: z.number(),
  outputTokens: z.number(),
  reasoningTokens: z.number().nullable(),
  cachedInputTokens: z.number(),
  costUsd: z.number(),
  activeAccounts: z.number(),
  cancelledCount: z.number(),
  errorCount: z.number(),
  medianTtftMs: z.number().optional().default(0),
  medianTps: z.number().optional().default(0),
  medianQueueMs: z.number().optional().default(0),
});

const ModelCostEntrySchema = z.object({
  model: z.string(),
  costUsd: z.number(),
  requests: z.number(),
  percentage: z.number(),
});

const UseragentCostEntrySchema = z.object({
  useragent: z.string(),
  costUsd: z.number(),
  requests: z.number(),
  percentage: z.number(),
});

const AccountCostEntrySchema = z.object({
  accountId: z.string().nullable(),
  alias: z.string().nullable(),
  costUsd: z.number(),
  requests: z.number(),
});

const MonthlyModelEntrySchema = z.object({
  model: z.string(),
  costUsd: z.number(),
  requests: z.number(),
  percentage: z.number(),
});

const MonthlyUsageEntrySchema = z.object({
  month: z.string(),
  requests: z.number(),
  inputTokens: z.number(),
  outputTokens: z.number(),
  cachedInputTokens: z.number(),
  costUsd: z.number(),
  models: z.array(MonthlyModelEntrySchema),
});

const ReportSummarySchema = z.object({
  totalCostUsd: z.number(),
  totalInputTokens: z.number(),
  totalOutputTokens: z.number(),
  totalReasoningTokens: z.number(),
  reasoningUsageKnownRequests: z.number(),
  totalCachedTokens: z.number(),
  totalRequests: z.number(),
  totalCancelled: z.number(),
  totalErrors: z.number(),
  totalConversations: z.number(),
  activeAccounts: z.number(),
  avgCostPerDay: z.number(),
  avgRequestsPerDay: z.number(),
});

const ReportComparisonPreviousSchema = z.object({
  totalCostUsd: z.number(),
  totalTokens: z.number(),
  totalRequests: z.number(),
});

const ReportComparisonSchema = z.object({
  canCompare: z.boolean(),
  previous: ReportComparisonPreviousSchema,
});

export const ReportsOptionsResponseSchema = z.object({
  models: z.array(z.string()),
  useragents: z.array(z.string()),
});

export const ReportsResponseSchema = z.object({
  generatedAt: z.string().optional(),
  speedMetricsAvailable: z.boolean().optional(),
  speedMetricsMaxDays: z.number().optional(),
  summary: ReportSummarySchema,
  comparison: ReportComparisonSchema,
  daily: z.array(DailyReportRowSchema),
  byModel: z.array(ModelCostEntrySchema),
  byUseragent: z.array(UseragentCostEntrySchema),
  byAccount: z.array(AccountCostEntrySchema),
  // Lifetime additions (optional for rolling-deploy tolerance against a
  // backend that predates them):
  monthly: z.array(MonthlyUsageEntrySchema).optional(),
  // Inclusive UTC date from which raw-only measures are guaranteed (null
  // when request-log retention is disabled).
  rawMetricsSince: z.string().nullable().optional(),
  // Inclusive UTC date from which the hourly-rollup window is guaranteed
  // (null when hourly retention is disabled or the per-day series is
  // served at UTC-day grain) — a non-UTC timezone's per-day series is
  // served at hour grain, so hourly-rollup pruning shrinks it.
  hourlyCoverageSince: z.string().nullable().optional(),
  // Inclusive UTC date of the earliest countable activity (rollup-backed
  // once raw is pruned); the All-time range origin.
  earliestActivityAt: z.string().nullable().optional(),
});

const ThreadIdentityFacetSchema = z.object({
  requests: z.number(),
  requestShare: z.number(),
  unattributedRequestShare: z.number(),
  conversations: z.number(),
  meanAccountsPerConversation: z.number(),
  singleAccountConversationShare: z.number(),
  turns: z.number(),
  accountSwitchRate: z.number(),
  cacheHitRatio: z.number(),
  cacheSampleInputTokens: z.number(),
  threadGroupingApproximate: z.boolean(),
});

export const ThreadIdentityResponseSchema = z.object({
  generatedAt: z.string().optional(),
  available: z.boolean(),
  maxDays: z.number(),
  windowDays: z.number(),
  conversationMinRequests: z.number(),
  switchMaxGapSeconds: z.number(),
  cacheMinInputTokens: z.number(),
  totalRequests: z.number(),
  unkeyedRequestShare: z.number(),
  keyed: ThreadIdentityFacetSchema,
  unkeyed: ThreadIdentityFacetSchema,
});

export type DailyReportRow = z.input<typeof DailyReportRowSchema>;
export type ModelCostEntry = z.infer<typeof ModelCostEntrySchema>;
export type UseragentCostEntry = z.infer<typeof UseragentCostEntrySchema>;
export type AccountCostEntry = z.infer<typeof AccountCostEntrySchema>;
export type MonthlyModelEntry = z.infer<typeof MonthlyModelEntrySchema>;
export type MonthlyUsageEntry = z.infer<typeof MonthlyUsageEntrySchema>;
export type ReportSummary = z.infer<typeof ReportSummarySchema>;
export type ReportComparison = z.infer<typeof ReportComparisonSchema>;
export type ReportsResponse = z.infer<typeof ReportsResponseSchema>;
export type ThreadIdentityFacet = z.infer<typeof ThreadIdentityFacetSchema>;
export type ThreadIdentityResponse = z.infer<typeof ThreadIdentityResponseSchema>;
