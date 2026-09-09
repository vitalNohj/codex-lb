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

const ApiKeyCostEntrySchema = z.object({
  apiKeyId: z.string().nullable(),
  name: z.string().nullable(),
  keyPrefix: z.string().nullable(),
  costUsd: z.number(),
  requests: z.number(),
  tokens: z.number(),
  percentage: z.number(),
  avgDayRequests: z.number(),
  peakDayDate: z.string().nullable(),
  peakDayRequests: z.number(),
  peakDayCostUsd: z.number(),
  burstRatio: z.number(),
});

const ApiKeyDailyRowSchema = z.object({
  date: z.string(),
  apiKeyId: z.string().nullable(),
  requests: z.number(),
  costUsd: z.number(),
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
  byApiKey: z.array(ApiKeyCostEntrySchema),
  dailyByApiKey: z.array(ApiKeyDailyRowSchema),
});

export type DailyReportRow = z.input<typeof DailyReportRowSchema>;
export type ModelCostEntry = z.infer<typeof ModelCostEntrySchema>;
export type UseragentCostEntry = z.infer<typeof UseragentCostEntrySchema>;
export type AccountCostEntry = z.infer<typeof AccountCostEntrySchema>;
export type ApiKeyCostEntry = z.infer<typeof ApiKeyCostEntrySchema>;
export type ApiKeyDailyRow = z.infer<typeof ApiKeyDailyRowSchema>;
export type ReportSummary = z.infer<typeof ReportSummarySchema>;
export type ReportComparison = z.infer<typeof ReportComparisonSchema>;
export type ReportsResponse = z.infer<typeof ReportsResponseSchema>;
