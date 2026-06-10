import { describe, expect, it } from "vitest";

import {
  AccountAuthExportResponseSchema,
  AccountProbeResponseSchema,
  AccountSummarySchema,
  ImportStateSchema,
  OAuthStateSchema,
} from "@/features/accounts/schemas";

const ISO = "2026-01-01T00:00:00+00:00";

describe("AccountSummarySchema", () => {
  it("parses lightweight account payload", () => {
    const parsed = AccountSummarySchema.parse({
      accountId: "acc-1",
      email: "user@example.com",
      displayName: "User",
      planType: "pro",
      status: "active",
      usage: {
        primaryRemainingPercent: 85,
        secondaryRemainingPercent: null,
        monthlyRemainingPercent: 95,
      },
      resetAtPrimary: ISO,
      resetAtSecondary: null,
      resetAtMonthly: ISO,
      windowMinutesPrimary: null,
      windowMinutesSecondary: 10080,
      windowMinutesMonthly: 43200,
      requestUsage: {
        requestCount: 3,
        totalTokens: 1500,
        cachedInputTokens: 1100,
        totalCostUsd: 0.02,
      },
      auth: {
        access: {
          expiresAt: ISO,
          state: "valid",
        },
        refresh: {
          state: "stored",
        },
        idToken: {
          state: "parsed",
        },
      },
    });

    expect(parsed.accountId).toBe("acc-1");
    expect(parsed.routingPolicy ?? "normal").toBe("normal");
    expect(parsed.usage?.primaryRemainingPercent).toBe(85);
    expect(parsed.usage?.monthlyRemainingPercent).toBe(95);
    expect(parsed.windowMinutesSecondary).toBe(10080);
    expect(parsed.windowMinutesMonthly).toBe(43200);
    expect(parsed.requestUsage?.totalCostUsd).toBe(0.02);
  });

  it("parses synthetic sidecar account fields", () => {
    const parsed = AccountSummarySchema.parse({
      accountId: "claude-sidecar",
      email: "cliproxyapi.local",
      displayName: "Claude via CLIProxyAPI",
      planType: "claude",
      status: "paused",
      kind: "sidecar",
      provider: "claude",
      readOnly: true,
      synthetic: true,
      healthStatus: "unreachable",
      healthMessage: "connection refused",
      modelCount: 0,
      baseUrl: "http://127.0.0.1:8317",
      lastCheckedAt: ISO,
    });

    expect(parsed.synthetic).toBe(true);
    expect(parsed.readOnly).toBe(true);
    expect(parsed.healthStatus).toBe("unreachable");
    expect(parsed.sidecarAuths).toEqual([]);
  });

  it("parses synthetic sidecar account with rate-limited quota", () => {
    const parsed = AccountSummarySchema.parse({
      accountId: "claude-sidecar",
      email: "cliproxyapi.local",
      displayName: "Claude via CLIProxyAPI",
      planType: "claude",
      status: "rate_limited",
      kind: "sidecar",
      provider: "claude",
      readOnly: true,
      synthetic: true,
      healthStatus: "healthy",
      baseUrl: "http://127.0.0.1:8317",
      resetAtPrimary: ISO,
      lastRefreshAt: ISO,
      sidecarAuths: [
        {
          name: "claude-1",
          email: "ok@example.com",
          status: "active",
          quotaExceeded: false,
          modelsExceeded: [],
          success: 10,
          failed: 0,
        },
        {
          name: "claude-2",
          email: "exceeded@example.com",
          status: "active",
          quotaExceeded: true,
          nextRecoverAt: ISO,
          modelsExceeded: ["claude-opus-4"],
          success: 5,
          failed: 3,
        },
      ],
    });

    expect(parsed.status).toBe("rate_limited");
    expect(parsed.sidecarAuths).toHaveLength(2);
    expect(parsed.sidecarAuths[1].quotaExceeded).toBe(true);
    expect(parsed.sidecarAuths[1].modelsExceeded).toEqual(["claude-opus-4"]);
    expect(parsed.resetAtPrimary).toBe(ISO);
  });

  it("parses manual routing policy", () => {
    const parsed = AccountSummarySchema.parse({
      accountId: "acc-1",
      email: "user@example.com",
      displayName: "User",
      planType: "pro",
      status: "active",
      routingPolicy: "preserve",
    });

    expect(parsed.routingPolicy).toBe("preserve");
  });
});

describe("AccountAuthExportResponseSchema", () => {
  it("parses combined auth export payloads with raw Codex keys", () => {
    const parsed = AccountAuthExportResponseSchema.parse({
      filename: "opencode-auth-user.json",
      account: {
        accountId: "acc-1",
        chatgptAccountId: "chatgpt-acc-1",
        email: "user@example.com",
      },
      tokens: {
        idToken: "id-token",
        accessToken: "access-token",
        refreshToken: "refresh-token",
        expiresAtMs: 2_000_000_000_000,
      },
      codexAuthJson: {
        auth_mode: "chatgpt",
        OPENAI_API_KEY: null,
        tokens: {
          id_token: "id-token",
          access_token: "access-token",
          refresh_token: "refresh-token",
          account_id: "chatgpt-acc-1",
        },
        last_refresh: "2026-01-01T00:00:00.000000Z",
      },
      opencodeAuthJson: {
        openai: {
          type: "oauth",
          refresh: "refresh-token",
          access: "access-token",
          expires: 2_000_000_000_000,
          accountId: "chatgpt-acc-1",
        },
      },
    });

    expect(parsed.codexAuthJson.tokens.account_id).toBe("chatgpt-acc-1");
    expect(parsed.codexAuthJson.OPENAI_API_KEY).toBeNull();
  });
});

describe("OAuthStateSchema", () => {
  it("parses pending device flow state", () => {
    const parsed = OAuthStateSchema.parse({
      status: "pending",
      method: "device",
      authorizationUrl: null,
      callbackUrl: null,
      verificationUrl: "https://example.com/device",
      userCode: "ABCD-EFGH",
      deviceAuthId: "device-1",
      intervalSeconds: 5,
      expiresInSeconds: 300,
      errorMessage: null,
    });

    expect(parsed.status).toBe("pending");
    expect(parsed.method).toBe("device");
  });

  it("rejects invalid status", () => {
    const result = OAuthStateSchema.safeParse({
      status: "done",
      method: null,
      authorizationUrl: null,
      callbackUrl: null,
      verificationUrl: null,
      userCode: null,
      deviceAuthId: null,
      intervalSeconds: null,
      expiresInSeconds: null,
      errorMessage: null,
    });

    expect(result.success).toBe(false);
  });
});

describe("ImportStateSchema", () => {
  it("parses import states", () => {
    expect(
      ImportStateSchema.safeParse({
        status: "uploading",
        message: null,
      }).success,
    ).toBe(true);

    expect(
      ImportStateSchema.safeParse({
        status: "success",
        message: "Imported 1 account",
      }).success,
    ).toBe(true);
  });
});

describe("AccountProbeResponseSchema", () => {
  it("parses probe response payloads", () => {
    const parsed = AccountProbeResponseSchema.parse({
      status: "probed",
      accountId: "acc-1",
      probeStatusCode: 200,
      primaryUsedPercentBefore: 80,
      primaryUsedPercentAfter: 79,
      secondaryUsedPercentBefore: 50,
      secondaryUsedPercentAfter: 49,
      accountStatusBefore: "active",
      accountStatusAfter: "active",
    });

    expect(parsed.probeStatusCode).toBe(200);
    expect(parsed.accountId).toBe("acc-1");
  });
});
