import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { createElement, type PropsWithChildren } from "react";
import { toast } from "sonner";
import { describe, expect, it, vi } from "vitest";

import * as settingsApi from "@/features/settings/api";
import { useSettings, useTelemetryConsent, useTelemetryPreview } from "@/features/settings/hooks/use-settings";
import { ApiError } from "@/lib/api-client";
import { createDashboardSettings } from "@/test/mocks/factories";
import { server } from "@/test/mocks/server";

function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
      },
    },
  });
}

function createWrapper(queryClient: QueryClient) {
  return function Wrapper({ children }: PropsWithChildren) {
    return createElement(QueryClientProvider, { client: queryClient }, children);
  };
}

describe("useSettings", () => {
  it("loads settings and invalidates cache on update", async () => {
    const queryClient = createTestQueryClient();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    const { result } = renderHook(() => useSettings(), {
      wrapper: createWrapper(queryClient),
    });

    await waitFor(() => expect(result.current.settingsQuery.isSuccess).toBe(true));
    expect(result.current.settingsQuery.data?.stickyThreadsEnabled).toBeTypeOf("boolean");
    expect(result.current.settingsQuery.data?.openaiCacheAffinityMaxAgeSeconds).toBeTypeOf("number");
    expect(result.current.settingsQuery.data?.dashboardSessionTtlSeconds).toBeTypeOf("number");

    await result.current.updateSettingsMutation.mutateAsync({
      stickyThreadsEnabled: false,
      preferEarlierResetAccounts: true,
      preferEarlierResetWindow: "secondary",
      openaiCacheAffinityMaxAgeSeconds: 180,
      dashboardSessionTtlSeconds: 31536000,
      stickyReallocationBudgetThresholdPct: 95,
      stickyReallocationPrimaryBudgetThresholdPct: 95,
      stickyReallocationSecondaryBudgetThresholdPct: 100,
      importWithoutOverwrite: true,
      totpRequiredOnLogin: false,
      apiKeyAuthEnabled: true,
    });

    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["settings", "detail"] });
    });
  });

  it("retries once on settings_conflict without toasting the conflict", async () => {
    const queryClient = createTestQueryClient();
    const loaded = createDashboardSettings({ version: 3, stickyThreadsEnabled: false });
    const afterConflict = createDashboardSettings({ version: 4, stickyThreadsEnabled: false });
    const saved = createDashboardSettings({ version: 5, stickyThreadsEnabled: true });
    server.use(http.get("*/api/settings", () => HttpResponse.json(loaded)));

    const toastError = vi.spyOn(toast, "error").mockImplementation(() => "");
    const toastSuccess = vi.spyOn(toast, "success").mockImplementation(() => "");
    const updateSpy = vi
      .spyOn(settingsApi, "updateSettings")
      .mockRejectedValueOnce(
        new ApiError({
          message: "Settings were modified since this form was loaded; reload and retry",
          status: 409,
          code: "settings_conflict",
        }),
      )
      .mockResolvedValueOnce(saved);
    const getSpy = vi.spyOn(settingsApi, "getSettings");

    try {
      const { result } = renderHook(() => useSettings(), {
        wrapper: createWrapper(queryClient),
      });

      await waitFor(() => expect(result.current.settingsQuery.isSuccess).toBe(true));
      expect(result.current.settingsQuery.data?.version).toBe(3);
      getSpy.mockResolvedValueOnce(afterConflict);

      await result.current.updateSettingsMutation.mutateAsync({ stickyThreadsEnabled: true });

      expect(updateSpy).toHaveBeenCalledTimes(2);
      expect(updateSpy).toHaveBeenNthCalledWith(1, {
        stickyThreadsEnabled: true,
        expectedVersion: 3,
      });
      expect(updateSpy).toHaveBeenNthCalledWith(2, {
        stickyThreadsEnabled: true,
        expectedVersion: 4,
      });
      expect(toastError).not.toHaveBeenCalled();
      expect(toastSuccess).toHaveBeenCalled();
    } finally {
      updateSpy.mockRestore();
      getSpy.mockRestore();
      toastError.mockRestore();
      toastSuccess.mockRestore();
    }
  });
});

describe("useTelemetryConsent", () => {
  it("loads consent and invalidates cache on decision", async () => {
    const queryClient = createTestQueryClient();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    const { result } = renderHook(() => useTelemetryConsent(), {
      wrapper: createWrapper(queryClient),
    });

    await waitFor(() => expect(result.current.telemetryConsentQuery.isSuccess).toBe(true));
    expect(result.current.telemetryConsentQuery.data?.state).toBe("enabled");
    expect(result.current.telemetryConsentQuery.data?.active).toBe(true);
    // A persisted decision skips the expensive snapshot build entirely.
    expect(result.current.telemetryConsentQuery.data?.preview).toBeNull();

    await result.current.updateTelemetryConsentMutation.mutateAsync({ enabled: false });

    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["settings", "telemetry"] });
    });
  });
});

describe("useTelemetryPreview", () => {
  it("stays idle until enabled, then loads the preview envelope", async () => {
    const queryClient = createTestQueryClient();

    const { result, rerender } = renderHook(({ enabled }) => useTelemetryPreview(enabled), {
      wrapper: createWrapper(queryClient),
      initialProps: { enabled: false },
    });

    expect(result.current.telemetryPreviewQuery.isFetching).toBe(false);
    expect(result.current.telemetryPreviewQuery.data).toBeUndefined();

    rerender({ enabled: true });

    await waitFor(() => expect(result.current.telemetryPreviewQuery.isSuccess).toBe(true));
    const preview = result.current.telemetryPreviewQuery.data?.preview;
    expect(preview?.metrics.schema_version).toBe(1);
    expect(preview?.instance_id).toBe("00000000-0000-4000-8000-000000000000");
    expect(preview?.timestamp).toBe("2026-08-06T00:00:00Z");
  });
});
