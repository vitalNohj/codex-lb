import { describe, expect, it } from "vitest";

import {
  DashboardSettingsSchema,
  OpenCodeGoSidecarModelsResponseSchema,
  OpenCodeGoSidecarModelSummarySchema,
  OpenCodeGoSidecarStatusResponseSchema,
  OpenCodeGoSidecarTestResponseSchema,
} from "@/features/settings/schemas";

/**
 * Parse tests against the literal JSON in the backend contract
 * (`data/codexlb-opencode-go-integration/contract.md`, sections 2 and 3).
 *
 * These exist so a drift between the published contract and this frontend fails
 * as a test rather than as a runtime schema mismatch in the dashboard. The
 * payloads below are copied from that document, not invented here.
 */
describe("OpenCode Go backend contract", () => {
  describe("status response (contract section 3)", () => {
    it("parses the documented disabled example verbatim", () => {
      const parsed = OpenCodeGoSidecarStatusResponseSchema.parse({
        enabled: false,
        configured: false,
        status: "disabled",
        message: "OpenCode Go is disabled",
        baseUrl: "https://opencode.ai/zen/go/v1",
        modelCount: null,
        lastCheckedAt: null,
      });

      expect(parsed.status).toBe("disabled");
      expect(parsed.modelCount).toBeNull();
    });

    it("accepts every status in the shared sidecar vocabulary", () => {
      for (const status of [
        "disabled",
        "missing_api_key",
        "unreachable",
        "unauthorized",
        "healthy",
        "error",
      ]) {
        expect(() =>
          OpenCodeGoSidecarStatusResponseSchema.parse({
            enabled: true,
            configured: true,
            status,
            message: null,
            baseUrl: "https://opencode.ai/zen/go/v1",
            modelCount: 15,
            lastCheckedAt: "2026-09-14T00:00:00Z",
          }),
        ).not.toThrow();
      }
    });

    it("rejects a status value outside that vocabulary", () => {
      expect(() =>
        OpenCodeGoSidecarStatusResponseSchema.parse({
          enabled: true,
          configured: true,
          status: "degraded",
          baseUrl: "https://opencode.ai/zen/go/v1",
        }),
      ).toThrow();
    });
  });

  describe("model summary (contract section 3)", () => {
    it("parses the documented example row verbatim", () => {
      const parsed = OpenCodeGoSidecarModelSummarySchema.parse({
        id: "glm-5.3",
        created: 1789353162,
        ownedBy: "opencode",
        protocol: "chat_completions",
        supported: true,
      });

      expect(parsed).toEqual({
        id: "glm-5.3",
        created: 1789353162,
        ownedBy: "opencode",
        protocol: "chat_completions",
        supported: true,
      });
    });

    it("accepts all four documented protocol values, including unknown", () => {
      for (const protocol of ["chat_completions", "messages", "responses", "unknown"]) {
        expect(OpenCodeGoSidecarModelSummarySchema.parse({ id: "m", protocol }).protocol).toBe(
          protocol,
        );
      }
    });

    it("treats protocol unknown as a real value, not a parse failure", () => {
      const parsed = OpenCodeGoSidecarModelSummarySchema.parse({
        id: "some-unlisted-preview",
        protocol: "unknown",
        supported: false,
      });

      expect(parsed.protocol).toBe("unknown");
      expect(parsed.supported).toBe(false);
    });

    it("defaults a summary without protocol/supported to the conservative reading", () => {
      // An older backend that sends only the shared sidecar fields must never
      // have its models treated as dispatchable.
      const parsed = OpenCodeGoSidecarModelSummarySchema.parse({
        id: "legacy",
        created: 1,
        ownedBy: "opencode",
      });

      expect(parsed.protocol).toBe("unknown");
      expect(parsed.supported).toBe(false);
    });

    it("rejects an undocumented protocol rather than guessing", () => {
      expect(() =>
        OpenCodeGoSidecarModelSummarySchema.parse({ id: "m", protocol: "grpc" }),
      ).toThrow();
    });
  });

  describe("test and models responses (contract section 3)", () => {
    it("parses the documented test response verbatim", () => {
      const parsed = OpenCodeGoSidecarTestResponseSchema.parse({
        enabled: true,
        configured: true,
        status: "healthy",
        message: null,
        baseUrl: "https://opencode.ai/zen/go/v1",
        modelCount: 1,
        lastCheckedAt: "2026-09-14T00:00:00Z",
        models: [
          {
            id: "glm-5.3",
            created: 1789353162,
            ownedBy: "opencode",
            protocol: "chat_completions",
            supported: true,
          },
        ],
      });

      expect(parsed.models).toHaveLength(1);
      expect(parsed.models[0].supported).toBe(true);
    });

    it("parses the documented empty models response for a disabled integration", () => {
      // Contract: GET /models returns {"models": []} with no upstream call when
      // the integration is disabled or unconfigured.
      expect(OpenCodeGoSidecarModelsResponseSchema.parse({ models: [] }).models).toEqual([]);
    });

    it("parses a full advertised catalogue mixing supported and unsupported rows", () => {
      const parsed = OpenCodeGoSidecarModelsResponseSchema.parse({
        models: [
          { id: "glm-5.3", protocol: "chat_completions", supported: true },
          { id: "kimi-k3", protocol: "chat_completions", supported: true },
          { id: "minimax-m3", protocol: "messages", supported: false },
          { id: "grok-4.6", protocol: "responses", supported: false },
          { id: "muse-spark-1.3-contributor", protocol: "responses", supported: false },
          { id: "brand-new-id", protocol: "unknown", supported: false },
        ],
      });

      expect(parsed.models.filter((model) => model.supported).map((model) => model.id)).toEqual([
        "glm-5.3",
        "kimi-k3",
      ]);
    });
  });

  describe("settings fields (contract section 2)", () => {
    it("applies the documented defaults when the server omits the fields", () => {
      const parsed = DashboardSettingsSchema.parse({
        stickyThreadsEnabled: true,
        upstreamStreamTransport: "default",
        preferEarlierResetAccounts: false,
        routingStrategy: "round_robin",
        openaiCacheAffinityMaxAgeSeconds: 300,
        dashboardSessionTtlSeconds: 43200,
        importWithoutOverwrite: false,
        totpRequiredOnLogin: false,
        totpConfigured: false,
        apiKeyAuthEnabled: true,
      });

      expect(parsed.opencodeGoSidecarEnabled).toBe(false);
      expect(parsed.opencodeGoSidecarBaseUrl).toBe("https://opencode.ai/zen/go/v1");
      expect(parsed.opencodeGoSidecarApiKeyConfigured).toBe(false);
      // Empty on upgrade; the server seeds `opencode-go/` only on fresh install,
      // so the dashboard must not invent a prefix of its own.
      expect(parsed.opencodeGoSidecarModelPrefixes).toEqual([]);
      expect(parsed.opencodeGoSidecarFullModels).toEqual([]);
      expect(parsed.opencodeGoSidecarConnectTimeoutSeconds).toBe(8);
      expect(parsed.opencodeGoSidecarRequestTimeoutSeconds).toBe(600);
      expect(parsed.opencodeGoSidecarModelsCacheTtlSeconds).toBe(60);
      expect(parsed.opencodeGoSidecarLastHealthStatus).toBeNull();
      expect(parsed.opencodeGoSidecarLastCheckedAt).toBeNull();
      expect(parsed.opencodeGoSidecarLastModelCount).toBeNull();
    });

    it("parses the fresh-install seeded prefix with stripping on", () => {
      const parsed = DashboardSettingsSchema.parse({
        stickyThreadsEnabled: true,
        upstreamStreamTransport: "default",
        preferEarlierResetAccounts: false,
        routingStrategy: "round_robin",
        openaiCacheAffinityMaxAgeSeconds: 300,
        dashboardSessionTtlSeconds: 43200,
        importWithoutOverwrite: false,
        totpRequiredOnLogin: false,
        totpConfigured: false,
        apiKeyAuthEnabled: true,
        opencodeGoSidecarModelPrefixes: [{ prefix: "opencode-go/", strip: true }],
      });

      expect(parsed.opencodeGoSidecarModelPrefixes).toEqual([
        { prefix: "opencode-go/", strip: true },
      ]);
    });

    it("never exposes the API key itself in any parsed shape", () => {
      const parsed = DashboardSettingsSchema.parse({
        stickyThreadsEnabled: true,
        upstreamStreamTransport: "default",
        preferEarlierResetAccounts: false,
        routingStrategy: "round_robin",
        openaiCacheAffinityMaxAgeSeconds: 300,
        dashboardSessionTtlSeconds: 43200,
        importWithoutOverwrite: false,
        totpRequiredOnLogin: false,
        totpConfigured: false,
        apiKeyAuthEnabled: true,
        opencodeGoSidecarApiKeyConfigured: true,
      });

      expect(parsed.opencodeGoSidecarApiKeyConfigured).toBe(true);
      expect("opencodeGoSidecarApiKey" in parsed).toBe(false);
    });
  });
});
