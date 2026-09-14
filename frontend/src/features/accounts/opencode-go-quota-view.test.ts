import { describe, expect, it } from "vitest";

import { OpenCodeGoQuotaResponseSchema } from "@/features/accounts/opencode-go-schemas";
import {
  hasExhaustedWindow,
  resolveOpenCodeGoCardState,
  toQuotaWindowView,
} from "@/features/accounts/opencode-go-quota-view";
import { ApiError } from "@/lib/api-client";
import { createOpenCodeGoQuota } from "@/test/mocks/factories";

function parseWindow(overrides: Record<string, unknown>) {
  return OpenCodeGoQuotaResponseSchema.parse(
    createOpenCodeGoQuota({
      windows: [
        {
          key: "five_hour",
          upstreamKey: "rolling",
          status: "ok",
          percentUsed: 10,
          resetsAt: null,
          limitReached: false,
          ...overrides,
        },
      ],
    }),
  ).windows[0];
}

function expectQuota(state: ReturnType<typeof resolveOpenCodeGoCardState>) {
  if (state.kind !== "quota") {
    throw new Error(`expected quota state, got ${state.kind}`);
  }
  return state;
}

describe("toQuotaWindowView", () => {
  it("keeps percentUsed in the used direction and derives headroom for colour only", () => {
    const view = toQuotaWindowView(parseWindow({ percentUsed: 80 }));

    expect(view.percentUsed).toBe(80);
    expect(view.headroomPercent).toBe(20);
  });

  it("treats a null percentUsed as unknown rather than zero or full", () => {
    const view = toQuotaWindowView(parseWindow({ percentUsed: null }));

    expect(view.percentUsed).toBeNull();
    expect(view.headroomPercent).toBeNull();
  });

  it("clamps out-of-range percentages instead of overflowing the bar", () => {
    expect(toQuotaWindowView(parseWindow({ percentUsed: 140 })).percentUsed).toBe(100);
    expect(toQuotaWindowView(parseWindow({ percentUsed: -12 })).percentUsed).toBe(0);
  });

  it("preserves the upstream key so our window naming stays auditable", () => {
    const view = toQuotaWindowView(parseWindow({ key: "five_hour", upstreamKey: "rolling" }));

    expect(view.key).toBe("five_hour");
    expect(view.upstreamKey).toBe("rolling");
    expect(view.known).toBe(true);
  });

  it("marks an unrecognized future window key as unknown instead of dropping it", () => {
    const view = toQuotaWindowView(
      parseWindow({ key: "daily", upstreamKey: "daily", percentUsed: 5 }),
    );

    expect(view.known).toBe(false);
    expect(view.percentUsed).toBe(5);
  });

  it("does not synthesize a reset instant", () => {
    expect(toQuotaWindowView(parseWindow({ resetsAt: null })).resetsAt).toBeNull();
  });

  it("keeps an undeterminable limitReached as null rather than false", () => {
    expect(toQuotaWindowView(parseWindow({ limitReached: null })).limitReached).toBeNull();
  });
});

describe("resolveOpenCodeGoCardState", () => {
  it("reports loading while the first read is in flight", () => {
    expect(
      resolveOpenCodeGoCardState({ data: undefined, isPending: true, error: null }).kind,
    ).toBe("loading");
  });

  it("renders nothing when the deployment has no Go quota endpoint", () => {
    const state = resolveOpenCodeGoCardState({
      data: undefined,
      isPending: false,
      error: new ApiError({ message: "Not Found", status: 404, code: "not_found" }),
    });

    expect(state.kind).toBe("absent");
  });

  it("separates a schema mismatch from an upstream outage", () => {
    const state = resolveOpenCodeGoCardState({
      data: undefined,
      isPending: false,
      error: new ApiError({
        message: "Response schema mismatch",
        status: 200,
        code: "invalid_response_schema",
      }),
    });

    expect(state).toMatchObject({ kind: "notice", notice: "malformed", actionable: false });
  });

  it("does not blame the upstream key when our own dashboard call fails", () => {
    // Per the contract a 401 from this endpoint means the dashboard session is
    // invalid and says nothing about the OpenCode Go credential.
    const state = resolveOpenCodeGoCardState({
      data: undefined,
      isPending: false,
      error: new ApiError({ message: "unauthorized", status: 401, code: "unauthorized" }),
    });

    expect(state).toMatchObject({ kind: "notice", notice: "unavailable" });
  });

  it("offers a settings action for the disabled and unconfigured statuses", () => {
    const disabled = resolveOpenCodeGoCardState({
      data: createOpenCodeGoQuota({ status: "disabled", windows: [] }),
      isPending: false,
      error: null,
    });
    const unconfigured = resolveOpenCodeGoCardState({
      data: createOpenCodeGoQuota({ status: "not_configured", windows: [] }),
      isPending: false,
      error: null,
    });

    expect(disabled).toMatchObject({ kind: "notice", notice: "disabled", actionable: true });
    expect(unconfigured).toMatchObject({
      kind: "notice",
      notice: "not_configured",
      actionable: true,
    });
  });

  it("ignores stray windows on a disabled status rather than displaying them", () => {
    // The contract guarantees disabled carries no windows and issues no upstream
    // traffic, so a populated list would be a server bug - not data to render.
    const state = resolveOpenCodeGoCardState({
      data: createOpenCodeGoQuota({ status: "disabled" }),
      isPending: false,
      error: null,
    });

    expect(state).toMatchObject({ kind: "notice", notice: "disabled" });
  });

  it("maps each data-free status to its own notice", () => {
    for (const [status, notice] of [
      ["unauthorized", "unauthorized"],
      ["rate_limited", "rate_limited"],
      ["unavailable", "unavailable"],
    ] as const) {
      const state = resolveOpenCodeGoCardState({
        data: createOpenCodeGoQuota({ status, windows: [] }),
        isPending: false,
        error: null,
      });

      expect(state).toMatchObject({ kind: "notice", notice });
    }
  });

  it("treats an ok status with no parseable window as unknown, not as an empty card", () => {
    const state = resolveOpenCodeGoCardState({
      data: createOpenCodeGoQuota({ status: "ok", windows: [] }),
      isPending: false,
      error: null,
    });

    expect(state).toMatchObject({ kind: "notice", notice: "unavailable" });
  });

  it("surfaces the stale reason when a stale read carries no windows", () => {
    const state = resolveOpenCodeGoCardState({
      data: createOpenCodeGoQuota({
        status: "stale",
        stale: true,
        staleReason: "connect timeout",
        windows: [],
      }),
      isPending: false,
      error: null,
    });

    expect(state).toMatchObject({ kind: "notice", message: "connect timeout" });
  });

  it("handles a partial window list without filling the gap", () => {
    const state = expectQuota(
      resolveOpenCodeGoCardState({
        data: createOpenCodeGoQuota({
          windows: [
            {
              key: "five_hour",
              upstreamKey: "rolling",
              status: "ok",
              percentUsed: 30,
              resetsAt: null,
              limitReached: false,
            },
          ],
        }),
        isPending: false,
        error: null,
      }),
    );

    expect(state.windows).toHaveLength(1);
    expect(state.windows[0]?.key).toBe("five_hour");
  });

  it("keeps a known window beside an unknown one", () => {
    const state = expectQuota(
      resolveOpenCodeGoCardState({
        data: createOpenCodeGoQuota({
          windows: [
            {
              key: "five_hour",
              upstreamKey: "rolling",
              status: "ok",
              percentUsed: 30,
              resetsAt: null,
              limitReached: false,
            },
            {
              key: "weekly",
              upstreamKey: "weekly",
              status: "unknown",
              percentUsed: null,
              resetsAt: null,
              limitReached: null,
            },
          ],
        }),
        isPending: false,
        error: null,
      }),
    );

    expect(state.windows[0]?.percentUsed).toBe(30);
    expect(state.windows[1]?.percentUsed).toBeNull();
  });

  it("passes the server's scope through without upgrading unknown", () => {
    const state = expectQuota(
      resolveOpenCodeGoCardState({
        data: createOpenCodeGoQuota(),
        isPending: false,
        error: null,
      }),
    );

    expect(state.scope).toBe("unknown");
    expect(state.hasModelDetail).toBe(false);
    expect(state.models).toEqual([]);
  });

  it("does not expose model detail while modelBreakdownAvailable is false", () => {
    // Even if a models array leaked through, the server's own flag governs.
    const state = expectQuota(
      resolveOpenCodeGoCardState({
        data: createOpenCodeGoQuota({
          modelBreakdownAvailable: false,
          models: [
            {
              modelId: "claude-sonnet-4.5",
              displayName: null,
              windows: [
                {
                  key: "five_hour",
                  upstreamKey: "rolling",
                  status: "ok",
                  percentUsed: 12,
                  resetsAt: null,
                  limitReached: false,
                },
              ],
            },
          ],
        }),
        isPending: false,
        error: null,
      }),
    );

    expect(state.hasModelDetail).toBe(false);
    expect(state.models).toEqual([]);
  });

  it("does not treat a model list without windows as per-model quota data", () => {
    const state = expectQuota(
      resolveOpenCodeGoCardState({
        data: createOpenCodeGoQuota({
          modelBreakdownAvailable: true,
          scope: "per_model",
          models: [{ modelId: "claude-sonnet-4.5", displayName: null, windows: [] }],
        }),
        isPending: false,
        error: null,
      }),
    );

    expect(state.hasModelDetail).toBe(false);
    expect(state.models).toEqual([]);
  });

  it("exposes per-model detail only for models carrying real windows", () => {
    const state = expectQuota(
      resolveOpenCodeGoCardState({
        data: createOpenCodeGoQuota({
          modelBreakdownAvailable: true,
          scope: "per_model",
          models: [
            {
              modelId: "with-windows",
              displayName: null,
              windows: [
                {
                  key: "five_hour",
                  upstreamKey: "rolling",
                  status: "ok",
                  percentUsed: 12,
                  resetsAt: null,
                  limitReached: false,
                },
              ],
            },
            { modelId: "without-windows", displayName: null, windows: [] },
          ],
        }),
        isPending: false,
        error: null,
      }),
    );

    expect(state.hasModelDetail).toBe(true);
    expect(state.models.map((model) => model.modelId)).toEqual(["with-windows"]);
  });

  it("keeps last-good values visible while flagging the stale read", () => {
    const state = expectQuota(
      resolveOpenCodeGoCardState({
        data: createOpenCodeGoQuota({
          status: "stale",
          stale: true,
          staleReason: "read timeout",
        }),
        isPending: false,
        error: null,
      }),
    );

    expect(state.stale).toBe(true);
    expect(state.staleReason).toBe("read timeout");
    expect(state.windows).toHaveLength(2);
  });

  it("treats a stale status as stale even if the boolean disagrees", () => {
    const state = expectQuota(
      resolveOpenCodeGoCardState({
        data: createOpenCodeGoQuota({ status: "stale", stale: false }),
        isPending: false,
        error: null,
      }),
    );

    expect(state.stale).toBe(true);
  });
});

describe("hasExhaustedWindow", () => {
  it("is false for every non-quota state", () => {
    expect(hasExhaustedWindow({ kind: "loading" })).toBe(false);
    expect(hasExhaustedWindow({ kind: "absent" })).toBe(false);
    expect(
      hasExhaustedWindow({
        kind: "notice",
        notice: "disabled",
        message: null,
        actionable: true,
      }),
    ).toBe(false);
  });

  it("flags limitReached and a rate-limited window", () => {
    const reached = resolveOpenCodeGoCardState({
      data: createOpenCodeGoQuota({
        windows: [
          {
            key: "weekly",
            upstreamKey: "weekly",
            status: "ok",
            percentUsed: 100,
            resetsAt: null,
            limitReached: true,
          },
        ],
      }),
      isPending: false,
      error: null,
    });
    const throttled = resolveOpenCodeGoCardState({
      data: createOpenCodeGoQuota({
        windows: [
          {
            key: "five_hour",
            upstreamKey: "rolling",
            status: "rate_limited",
            percentUsed: null,
            resetsAt: null,
            limitReached: null,
          },
        ],
      }),
      isPending: false,
      error: null,
    });

    expect(hasExhaustedWindow(reached)).toBe(true);
    expect(hasExhaustedWindow(throttled)).toBe(true);
  });

  it("does not read a null limitReached as exhausted", () => {
    const state = resolveOpenCodeGoCardState({
      data: createOpenCodeGoQuota({
        windows: [
          {
            key: "weekly",
            upstreamKey: "weekly",
            status: "unknown",
            percentUsed: null,
            resetsAt: null,
            limitReached: null,
          },
        ],
      }),
      isPending: false,
      error: null,
    });

    expect(hasExhaustedWindow(state)).toBe(false);
  });

  it("is false when every reported window is healthy", () => {
    expect(
      hasExhaustedWindow(
        resolveOpenCodeGoCardState({
          data: createOpenCodeGoQuota(),
          isPending: false,
          error: null,
        }),
      ),
    ).toBe(false);
  });
});

describe("resolveOpenCodeGoCardState cached-data retention", () => {
  const boom = new ApiError({ message: "boom", status: 500, code: "request_failed" });

  it("retains a known-good snapshot when the latest request failed", () => {
    const state = expectQuota(
      resolveOpenCodeGoCardState({
        data: createOpenCodeGoQuota(),
        isPending: false,
        error: boom,
      }),
    );

    expect(state.windows).toHaveLength(2);
    expect(state.refreshFailed).toBe(true);
    // Retained values are never presented as current.
    expect(state.stale).toBe(true);
  });

  it("does not adopt our own request error as the upstream stale reason", () => {
    const state = expectQuota(
      resolveOpenCodeGoCardState({
        data: createOpenCodeGoQuota(),
        isPending: false,
        error: boom,
      }),
    );

    expect(state.staleReason).toBeNull();
  });

  it("falls back to a notice only when there is no cached snapshot to keep", () => {
    expect(
      resolveOpenCodeGoCardState({ data: undefined, isPending: false, error: boom }),
    ).toMatchObject({ kind: "notice", notice: "unavailable" });
  });

  it("retains the snapshot when a previously working route starts 404ing", () => {
    // A 404 after a success cannot prove the route never existed - it proves the
    // opposite. Deleting real numbers on that evidence would be wrong.
    const state = expectQuota(
      resolveOpenCodeGoCardState({
        data: createOpenCodeGoQuota(),
        isPending: false,
        error: new ApiError({ message: "Not Found", status: 404, code: "not_found" }),
      }),
    );

    expect(state.windows).toHaveLength(2);
    expect(state.endpointUnavailable).toBe(true);
    expect(state.refreshFailed).toBe(true);
    expect(state.stale).toBe(true);
  });

  it("still reports absent for a 404 with no snapshot to keep", () => {
    // The no-data 404 case is unchanged: nothing was ever read, so the
    // deployment genuinely has no Go quota route and the card is hidden.
    expect(
      resolveOpenCodeGoCardState({
        data: undefined,
        isPending: false,
        error: new ApiError({ message: "Not Found", status: 404, code: "not_found" }),
      }).kind,
    ).toBe("absent");
  });

  it("distinguishes a vanished endpoint from an ordinary refresh failure", () => {
    const gone = expectQuota(
      resolveOpenCodeGoCardState({
        data: createOpenCodeGoQuota(),
        isPending: false,
        error: new ApiError({ message: "Not Found", status: 404, code: "not_found" }),
      }),
    );
    const flaky = expectQuota(
      resolveOpenCodeGoCardState({
        data: createOpenCodeGoQuota(),
        isPending: false,
        error: new ApiError({ message: "boom", status: 500, code: "request_failed" }),
      }),
    );

    expect(gone.endpointUnavailable).toBe(true);
    expect(flaky.endpointUnavailable).toBe(false);
    expect(flaky.refreshFailed).toBe(true);
  });

  it("keeps a deliberate disabled response distinct from a vanished endpoint", () => {
    // Switching the integration off is an answer, not a failure: the server
    // replied successfully, so old numbers must not linger.
    const state = resolveOpenCodeGoCardState({
      data: createOpenCodeGoQuota({ status: "disabled", windows: [] }),
      isPending: false,
      error: null,
    });

    expect(state).toMatchObject({ kind: "notice", notice: "disabled" });
  });

  it("reports a switched-off integration rather than retaining old numbers", () => {
    const state = resolveOpenCodeGoCardState({
      data: createOpenCodeGoQuota({ status: "disabled", windows: [] }),
      isPending: false,
      error: null,
    });

    expect(state).toMatchObject({ kind: "notice", notice: "disabled" });
  });

  it("clears the failed-refresh flag once a request succeeds again", () => {
    const state = expectQuota(
      resolveOpenCodeGoCardState({
        data: createOpenCodeGoQuota(),
        isPending: false,
        error: null,
      }),
    );

    expect(state.refreshFailed).toBe(false);
    expect(state.endpointUnavailable).toBe(false);
    expect(state.stale).toBe(false);
  });
});
