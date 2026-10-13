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

export const ReportsResponseSchema = z.object({
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
  // Inclusive UTC date of the earliest countable activity (rollup-backed
  // once raw is pruned); the All-time range origin.
  earliestActivityAt: z.string().nullable().optional(),
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
