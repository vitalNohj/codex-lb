import { describe, expect, it } from "vitest";

import { buildSettingsUpdateRequest } from "@/features/settings/payload";
import { DashboardSettingsSchema } from "@/features/settings/schemas";

describe("buildSettingsUpdateRequest", () => {
  it("carries the loaded settings version as expectedVersion for CAS", () => {
    const settings = DashboardSettingsSchema.parse({
      stickyThreadsEnabled: true,
      upstreamStreamTransport: "default",
      preferEarlierResetAccounts: false,
      routingStrategy: "round_robin",
      openaiCacheAffinityMaxAgeSeconds: 300,
      dashboardSessionTtlSeconds: 43200,
      importWithoutOverwrite: true,
      totpRequiredOnLogin: true,
      totpConfigured: false,
      apiKeyAuthEnabled: true,
      version: 7,
    });

    const payload = buildSettingsUpdateRequest(settings, { apiKeyAuthEnabled: false });

    expect(payload.expectedVersion).toBe(7);
    expect(payload.apiKeyAuthEnabled).toBe(false);
  });

  it("omits expectedVersion when the loaded settings carry no version", () => {
    const settings = DashboardSettingsSchema.parse({
      stickyThreadsEnabled: true,
      upstreamStreamTransport: "default",
      preferEarlierResetAccounts: false,
      routingStrategy: "round_robin",
      openaiCacheAffinityMaxAgeSeconds: 300,
      dashboardSessionTtlSeconds: 43200,
      importWithoutOverwrite: true,
      totpRequiredOnLogin: true,
      totpConfigured: false,
      apiKeyAuthEnabled: true,
    });

    const payload = buildSettingsUpdateRequest(settings, { apiKeyAuthEnabled: false });

    expect("expectedVersion" in payload).toBe(false);
  });

  it("does not persist split sticky thresholds synthesized from legacy settings", () => {
    const settings = DashboardSettingsSchema.parse({
      stickyThreadsEnabled: true,
      upstreamStreamTransport: "default",
      preferEarlierResetAccounts: false,
      routingStrategy: "round_robin",
      openaiCacheAffinityMaxAgeSeconds: 300,
      dashboardSessionTtlSeconds: 43200,
      stickyReallocationBudgetThresholdPct: 95,
      importWithoutOverwrite: true,
      totpRequiredOnLogin: true,
      totpConfigured: false,
      apiKeyAuthEnabled: true,
    });

    const payload = buildSettingsUpdateRequest(settings, { dashboardSessionTtlSeconds: 7200 });

    expect(payload.dashboardSessionTtlSeconds).toBe(7200);
    expect(payload.stickyReallocationBudgetThresholdPct).toBe(95);
    expect(payload.stickyReallocationPrimaryBudgetThresholdPct).toBeUndefined();
    expect(payload.stickyReallocationSecondaryBudgetThresholdPct).toBeUndefined();
  });

  it("does not persist sticky threshold defaults synthesized from older settings", () => {
    const settings = DashboardSettingsSchema.parse({
      stickyThreadsEnabled: true,
      upstreamStreamTransport: "default",
      preferEarlierResetAccounts: false,
      routingStrategy: "round_robin",
      openaiCacheAffinityMaxAgeSeconds: 300,
      dashboardSessionTtlSeconds: 43200,
      importWithoutOverwrite: true,
      totpRequiredOnLogin: true,
      totpConfigured: false,
      apiKeyAuthEnabled: true,
    });

    const payload = buildSettingsUpdateRequest(settings, { dashboardSessionTtlSeconds: 7200 });

    expect(payload.dashboardSessionTtlSeconds).toBe(7200);
    expect(payload.stickyReallocationBudgetThresholdPct).toBeUndefined();
    expect(payload.stickyReallocationPrimaryBudgetThresholdPct).toBeUndefined();
    expect(payload.stickyReallocationSecondaryBudgetThresholdPct).toBeUndefined();
  });

  it("does not persist a legacy threshold synthesized from split settings", () => {
    const settings = DashboardSettingsSchema.parse({
      stickyThreadsEnabled: true,
      upstreamStreamTransport: "default",
      preferEarlierResetAccounts: false,
      routingStrategy: "round_robin",
      openaiCacheAffinityMaxAgeSeconds: 300,
      dashboardSessionTtlSeconds: 43200,
      stickyReallocationPrimaryBudgetThresholdPct: 90,
      stickyReallocationSecondaryBudgetThresholdPct: 100,
      importWithoutOverwrite: true,
      totpRequiredOnLogin: true,
      totpConfigured: false,
      apiKeyAuthEnabled: true,
    });

    const payload = buildSettingsUpdateRequest(settings, { dashboardSessionTtlSeconds: 7200 });

    expect(payload.stickyReallocationBudgetThresholdPct).toBeUndefined();
    expect(payload.stickyReallocationPrimaryBudgetThresholdPct).toBe(90);
    expect(payload.stickyReallocationSecondaryBudgetThresholdPct).toBe(100);
  });

  it("persists split sticky thresholds that came from the backend", () => {
    const settings = DashboardSettingsSchema.parse({
      stickyThreadsEnabled: true,
      upstreamStreamTransport: "default",
      preferEarlierResetAccounts: false,
      routingStrategy: "round_robin",
      openaiCacheAffinityMaxAgeSeconds: 300,
      dashboardSessionTtlSeconds: 43200,
      stickyReallocationBudgetThresholdPct: 95,
      stickyReallocationPrimaryBudgetThresholdPct: 90,
      stickyReallocationSecondaryBudgetThresholdPct: 100,
      importWithoutOverwrite: true,
      totpRequiredOnLogin: true,
      totpConfigured: false,
      apiKeyAuthEnabled: true,
    });

    const payload = buildSettingsUpdateRequest(settings, { dashboardSessionTtlSeconds: 7200 });

    expect(payload.stickyReallocationPrimaryBudgetThresholdPct).toBe(90);
    expect(payload.stickyReallocationSecondaryBudgetThresholdPct).toBe(100);
  });

  it("keeps the legacy sticky threshold aligned with primary edits", () => {
    const settings = DashboardSettingsSchema.parse({
      stickyThreadsEnabled: true,
      upstreamStreamTransport: "default",
      preferEarlierResetAccounts: false,
      routingStrategy: "round_robin",
      openaiCacheAffinityMaxAgeSeconds: 300,
      dashboardSessionTtlSeconds: 43200,
      stickyReallocationBudgetThresholdPct: 95,
      stickyReallocationPrimaryBudgetThresholdPct: 95,
      stickyReallocationSecondaryBudgetThresholdPct: 100,
      importWithoutOverwrite: true,
      totpRequiredOnLogin: true,
      totpConfigured: false,
      apiKeyAuthEnabled: true,
      limitWarmupStaggeredIdleEnabled: true,
    });

    const payload = buildSettingsUpdateRequest(settings, {
      stickyReallocationPrimaryBudgetThresholdPct: 80,
    });

    expect(payload.limitWarmupStaggeredIdleEnabled).toBe(true);
    expect(payload.stickyReallocationBudgetThresholdPct).toBe(80);
    expect(payload.stickyReallocationPrimaryBudgetThresholdPct).toBe(80);
    expect(payload.stickyReallocationSecondaryBudgetThresholdPct).toBe(100);
  });

  it("preserves Claude sidecar plan and collector settings", () => {
    const settings = DashboardSettingsSchema.parse({
      stickyThreadsEnabled: true,
      upstreamStreamTransport: "default",
      preferEarlierResetAccounts: false,
      routingStrategy: "round_robin",
      openaiCacheAffinityMaxAgeSeconds: 300,
      dashboardSessionTtlSeconds: 43200,
      importWithoutOverwrite: true,
      totpRequiredOnLogin: true,
      totpConfigured: false,
      apiKeyAuthEnabled: true,
      claudeSidecarAuthPlans: [
        {
          authIndex: "0",
          email: "claude@example.com",
          planType: "custom",
          primaryTokenBudget: 100,
          secondaryTokenBudget: 700,
        },
      ],
      claudeSidecarUsagePollIntervalSeconds: 20,
      claudeSidecarUsageQueueBatchSize: 50,
      claudeSidecarUsageCollectionEnabled: false,
    });

    const payload = buildSettingsUpdateRequest(settings, { dashboardSessionTtlSeconds: 7200 });

    expect(payload.claudeSidecarAuthPlans).toEqual([
      expect.objectContaining({ authIndex: "0", planType: "custom" }),
    ]);
    expect(payload.claudeSidecarUsagePollIntervalSeconds).toBe(20);
    expect(payload.claudeSidecarUsageQueueBatchSize).toBe(50);
    expect(payload.claudeSidecarUsageCollectionEnabled).toBe(false);
  });


  it("preserves OrcaRouter sidecar settings when saving unrelated fields", () => {
    const settings = DashboardSettingsSchema.parse({
      stickyThreadsEnabled: true,
      upstreamStreamTransport: "default",
      preferEarlierResetAccounts: false,
      routingStrategy: "round_robin",
      openaiCacheAffinityMaxAgeSeconds: 300,
      dashboardSessionTtlSeconds: 43200,
      importWithoutOverwrite: true,
      totpRequiredOnLogin: true,
      totpConfigured: false,
      apiKeyAuthEnabled: true,
      orcarouterSidecarEnabled: true,
      orcarouterSidecarBaseUrl: "https://api.orcarouter.ai/v1",
      orcarouterSidecarModelPrefixes: [{ prefix: "orcarouter/", strip: false }],
      orcarouterSidecarFullModels: ["orcarouter/auto"],
      orcarouterSidecarConnectTimeoutSeconds: 3,
      orcarouterSidecarRequestTimeoutSeconds: 120,
      orcarouterSidecarModelsCacheTtlSeconds: 30,
    });

    const payload = buildSettingsUpdateRequest(settings, { dashboardSessionTtlSeconds: 7200 });

    expect(payload.orcarouterSidecarEnabled).toBe(true);
    expect(payload.orcarouterSidecarBaseUrl).toBe("https://api.orcarouter.ai/v1");
    expect(payload.orcarouterSidecarModelPrefixes).toEqual([{ prefix: "orcarouter/", strip: false }]);
    expect(payload.orcarouterSidecarFullModels).toEqual(["orcarouter/auto"]);
  });

  it("preserves Ollama sidecar settings when saving unrelated fields", () => {
    const settings = DashboardSettingsSchema.parse({
      stickyThreadsEnabled: true,
      upstreamStreamTransport: "default",
      preferEarlierResetAccounts: false,
      routingStrategy: "round_robin",
      openaiCacheAffinityMaxAgeSeconds: 300,
      dashboardSessionTtlSeconds: 43200,
      importWithoutOverwrite: true,
      totpRequiredOnLogin: true,
      totpConfigured: false,
      apiKeyAuthEnabled: true,
      ollamaSidecarEnabled: true,
      ollamaSidecarBaseUrl: "https://ollama.com",
      ollamaSidecarModelPrefixes: [{ prefix: "ollama-", strip: true }],
      ollamaSidecarFullModels: ["gpt-oss:120b-cloud"],
      ollamaSidecarConnectTimeoutSeconds: 3,
      ollamaSidecarRequestTimeoutSeconds: 120,
      ollamaSidecarModelsCacheTtlSeconds: 30,
    });

    const payload = buildSettingsUpdateRequest(settings, { dashboardSessionTtlSeconds: 7200 });

    expect(payload.dashboardSessionTtlSeconds).toBe(7200);
    expect(payload.ollamaSidecarEnabled).toBe(true);
    expect(payload.ollamaSidecarBaseUrl).toBe("https://ollama.com");
    expect(payload.ollamaSidecarModelPrefixes).toEqual([{ prefix: "ollama-", strip: true }]);
    expect(payload.ollamaSidecarFullModels).toEqual(["gpt-oss:120b-cloud"]);
    expect(payload.ollamaSidecarConnectTimeoutSeconds).toBe(3);
    expect(payload.ollamaSidecarRequestTimeoutSeconds).toBe(120);
    expect(payload.ollamaSidecarModelsCacheTtlSeconds).toBe(30);
  });

  it("includes limit warm-up exhausted threshold updates", () => {
    const settings = DashboardSettingsSchema.parse({
      stickyThreadsEnabled: true,
      upstreamStreamTransport: "default",
      preferEarlierResetAccounts: false,
      routingStrategy: "round_robin",
      openaiCacheAffinityMaxAgeSeconds: 300,
      dashboardSessionTtlSeconds: 43200,
      importWithoutOverwrite: true,
      totpRequiredOnLogin: true,
      totpConfigured: false,
      apiKeyAuthEnabled: true,
      limitWarmupExhaustedThresholdPercent: 99,
      limitWarmupIdleThresholdPercent: 1,
    });

    const payload = buildSettingsUpdateRequest(settings, {
      limitWarmupExhaustedThresholdPercent: 98.5,
      limitWarmupIdleThresholdPercent: 2.5,
    });

    expect(payload.limitWarmupExhaustedThresholdPercent).toBe(98.5);
    expect(payload.limitWarmupIdleThresholdPercent).toBe(2.5);
  });

  it("includes reset-credit setting updates", () => {
    const settings = DashboardSettingsSchema.parse({
      stickyThreadsEnabled: true,
      upstreamStreamTransport: "default",
      preferEarlierResetAccounts: false,
      routingStrategy: "round_robin",
      openaiCacheAffinityMaxAgeSeconds: 300,
      dashboardSessionTtlSeconds: 43200,
      importWithoutOverwrite: true,
      totpRequiredOnLogin: true,
      totpConfigured: false,
      apiKeyAuthEnabled: true,
      showResetCreditBadges: true,
      autoRedeemResetCreditsBeforeExpiry: false,
      showResetCreditExpiryBadge: true,
    });

    const payload = buildSettingsUpdateRequest(settings, {
      showResetCreditBadges: false,
      autoRedeemResetCreditsBeforeExpiry: true,
      showResetCreditExpiryBadge: false,
    });

    expect(payload.showResetCreditBadges).toBe(false);
    expect(payload.autoRedeemResetCreditsBeforeExpiry).toBe(true);
    expect(payload.showResetCreditExpiryBadge).toBe(false);
  });

  it("does not materialize inherited account capacity limits on unrelated updates", () => {
    const settings = DashboardSettingsSchema.parse({
      stickyThreadsEnabled: true,
      upstreamStreamTransport: "default",
      preferEarlierResetAccounts: false,
      routingStrategy: "round_robin",
      openaiCacheAffinityMaxAgeSeconds: 300,
      dashboardSessionTtlSeconds: 43200,
      proxyAccountResponseCreateLimit: 0,
      proxyAccountStreamLimit: 12,
      proxyAccountStreamRecoveryReserve: 2,
      proxyApiKeyFairShareCongestionThresholdPct: 80,
      importWithoutOverwrite: true,
      totpRequiredOnLogin: true,
      totpConfigured: false,
      apiKeyAuthEnabled: true,
    });

    const payload = buildSettingsUpdateRequest(settings, { warmupModel: "gpt-5.6-sol" });

    expect(payload.warmupModel).toBe("gpt-5.6-sol");
    expect(payload.proxyAccountResponseCreateLimit).toBeUndefined();
    expect(payload.proxyAccountStreamLimit).toBeUndefined();
    expect(payload.proxyAccountStreamRecoveryReserve).toBeUndefined();
    expect(payload.proxyApiKeyFairShareCongestionThresholdPct).toBeUndefined();
  });

  it("includes all account capacity limits when they are explicitly edited", () => {
    const settings = DashboardSettingsSchema.parse({
      stickyThreadsEnabled: true,
      upstreamStreamTransport: "default",
      preferEarlierResetAccounts: false,
      routingStrategy: "round_robin",
      openaiCacheAffinityMaxAgeSeconds: 300,
      dashboardSessionTtlSeconds: 43200,
      importWithoutOverwrite: true,
      totpRequiredOnLogin: true,
      totpConfigured: false,
      apiKeyAuthEnabled: true,
    });

    const payload = buildSettingsUpdateRequest(settings, {
      proxyAccountResponseCreateLimit: 0,
      proxyAccountStreamLimit: 12,
      proxyAccountStreamRecoveryReserve: 2,
      proxyApiKeyFairShareCongestionThresholdPct: 80,
    });

    expect(payload).toMatchObject({
      proxyAccountResponseCreateLimit: 0,
      proxyAccountStreamLimit: 12,
      proxyAccountStreamRecoveryReserve: 2,
      proxyApiKeyFairShareCongestionThresholdPct: 80,
    });
  });
});
