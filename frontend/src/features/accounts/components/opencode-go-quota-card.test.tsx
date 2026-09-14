import { QueryClient } from "@tanstack/react-query";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OpenCodeGoQuotaCard } from "@/features/accounts/components/opencode-go-quota-card";
import { createOpenCodeGoQuota, type OpenCodeGoQuotaResponse } from "@/test/mocks/factories";
import { server } from "@/test/mocks/server";
import { renderWithProviders } from "@/test/utils";

const QUOTA_ROUTE = "*/api/opencode-go/quota";

function mockQuota(overrides: Partial<OpenCodeGoQuotaResponse> = {}) {
  server.use(
    http.get(QUOTA_ROUTE, () => HttpResponse.json(createOpenCodeGoQuota(overrides))),
  );
}

function mockQuotaFailure(status: number, code = "boom") {
  server.use(
    http.get(QUOTA_ROUTE, () =>
      HttpResponse.json({ error: { code, message: code } }, { status }),
    ),
  );
}

/** A window the server returned but for which no percentage was parseable. */
const UNKNOWN_WEEKLY = {
  key: "weekly" as const,
  upstreamKey: "weekly",
  status: "unknown" as const,
  percentUsed: null,
  resetsAt: null,
  limitReached: null,
};

describe("OpenCodeGoQuotaCard", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date("2026-01-01T12:00:00.000Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows a loading state before the snapshot arrives", () => {
    server.use(
      http.get(QUOTA_ROUTE, async () => {
        await new Promise((resolve) => setTimeout(resolve, 10_000));
        return HttpResponse.json(createOpenCodeGoQuota());
      }),
    );

    renderWithProviders(<OpenCodeGoQuotaCard />);

    expect(screen.getByTestId("opencode-go-quota-loading")).toHaveAttribute("aria-busy", "true");
  });

  it("presents Go as an external subscription, not a Codex account", async () => {
    mockQuota();

    renderWithProviders(<OpenCodeGoQuotaCard />);

    expect(await screen.findByRole("heading", { name: /OpenCode Go/ })).toBeInTheDocument();
    expect(screen.getByText("External subscription")).toBeInTheDocument();
    // No account-style affordances: nothing to pause, probe, delete or re-auth.
    expect(screen.queryByRole("button", { name: /pause/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /delete/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /reauth/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /probe/i })).not.toBeInTheDocument();
  });

  it("links to the Go settings section", async () => {
    mockQuota();

    renderWithProviders(<OpenCodeGoQuotaCard />);

    expect(await screen.findByRole("link", { name: "Go settings" })).toHaveAttribute(
      "href",
      "/settings#opencode-go-sidecar",
    );
  });

  it("labels the five-hour and weekly windows explicitly as used", async () => {
    mockQuota();

    renderWithProviders(<OpenCodeGoQuotaCard />);

    expect(await screen.findByText("5h used")).toBeInTheDocument();
    expect(screen.getByText("Weekly used")).toBeInTheDocument();
    expect(screen.getByText("42%")).toBeInTheDocument();
    expect(screen.getByText("68%")).toBeInTheDocument();
  });

  it("never prints a remaining percentage", async () => {
    // The contract publishes no remaining field because the used direction is a
    // single-source inference; deriving 58% here would fake a second source.
    mockQuota();

    renderWithProviders(<OpenCodeGoQuotaCard />);

    await screen.findByText("42%");
    expect(screen.queryByText(/remaining/i)).not.toBeInTheDocument();
    expect(screen.queryByText("58%")).not.toBeInTheDocument();
    expect(screen.queryByText("32%")).not.toBeInTheDocument();
  });

  it("states the scope is unspecified rather than calling it an account total", async () => {
    mockQuota();

    renderWithProviders(<OpenCodeGoQuotaCard />);

    expect(await screen.findByText("Subscription usage")).toBeInTheDocument();
    expect(screen.getByTestId("opencode-go-scope-note")).toHaveTextContent(
      /without saying whether they cover the whole subscription or a single model/,
    );
    expect(screen.queryByText(/account total/i)).not.toBeInTheDocument();
  });

  it("captions account scope plainly once the server can assert it", async () => {
    mockQuota({ scope: "account" });

    renderWithProviders(<OpenCodeGoQuotaCard />);

    expect(await screen.findByTestId("opencode-go-scope-note")).toHaveTextContent(
      /cover the whole OpenCode Go subscription, across every model/,
    );
  });

  it("says Unknown and draws no fill when a window has no value", async () => {
    mockQuota({ windows: [UNKNOWN_WEEKLY] });

    renderWithProviders(<OpenCodeGoQuotaCard />);

    expect(await screen.findByText("Unknown")).toBeInTheDocument();
    expect(screen.getByTestId("opencode-go-window-unknown-track")).toBeInTheDocument();
    // Neither 0% nor 100%: no fill element and no progress value at all.
    expect(screen.queryByTestId("opencode-go-window-fill")).not.toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("keeps a known window rendered beside an unknown one", async () => {
    mockQuota({
      windows: [
        {
          key: "five_hour",
          upstreamKey: "rolling",
          status: "ok",
          percentUsed: 35,
          resetsAt: "2026-01-01T14:00:00.000Z",
          limitReached: false,
        },
        UNKNOWN_WEEKLY,
      ],
    });

    renderWithProviders(<OpenCodeGoQuotaCard />);

    expect(await screen.findByText("35%")).toBeInTheDocument();
    expect(screen.getByText("Unknown")).toBeInTheDocument();
    expect(screen.getAllByTestId("opencode-go-window-fill")).toHaveLength(1);
  });

  it("renders a partial window list without inventing the missing windows", async () => {
    mockQuota({
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
    });

    renderWithProviders(<OpenCodeGoQuotaCard />);

    expect(await screen.findByText("5h used")).toBeInTheDocument();
    expect(screen.getAllByTestId("opencode-go-window")).toHaveLength(1);
    expect(screen.queryByText("Weekly used")).not.toBeInTheDocument();
    expect(screen.queryByText("Monthly used")).not.toBeInTheDocument();
  });

  it("falls back to the upstream key for an unrecognized future window", async () => {
    mockQuota({
      windows: [
        {
          key: "daily",
          upstreamKey: "daily",
          status: "ok",
          percentUsed: 7,
          resetsAt: null,
          limitReached: false,
        },
      ],
    });

    renderWithProviders(<OpenCodeGoQuotaCard />);

    expect(await screen.findByText("daily used")).toBeInTheDocument();
    expect(screen.getByText("7%")).toBeInTheDocument();
  });

  it("states the reset time is not reported instead of inventing one", async () => {
    mockQuota({ windows: [UNKNOWN_WEEKLY] });

    renderWithProviders(<OpenCodeGoQuotaCard />);

    expect(await screen.findByText("Reset time not reported")).toBeInTheDocument();
  });

  it("renders a reset countdown only when the server supplied one", async () => {
    mockQuota({
      windows: [
        {
          key: "five_hour",
          upstreamKey: "rolling",
          status: "ok",
          percentUsed: 10,
          // Half a minute past the boundary: the shared formatter floors
          // minutes, so this stays "2h 30m" even as the clock ticks forward
          // during the test instead of flipping to "2h 29m".
          resetsAt: "2026-01-01T14:30:30.000Z",
          limitReached: false,
        },
      ],
    });

    renderWithProviders(<OpenCodeGoQuotaCard />);

    // The shared relative formatter already supplies "in ...", so the label must
    // read "Resets in 2h 30m" and never double it up as "Resets in in 2h 30m".
    expect(await screen.findByText("Resets in 2h 30m")).toBeInTheDocument();
    expect(screen.queryByText(/in in /)).not.toBeInTheDocument();
  });

  it("explains that usage is not broken down by model and shows no picker", async () => {
    mockQuota();

    renderWithProviders(<OpenCodeGoQuotaCard />);

    expect(await screen.findByTestId("opencode-go-no-model-detail")).toHaveTextContent(
      /does not break usage down by model/,
    );
    expect(screen.queryByTestId("opencode-go-model-windows")).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    // The aggregate value appears exactly once, never repeated per model.
    expect(screen.getAllByText("42%")).toHaveLength(1);
  });

  it("does not imply per-model data exists just because model ids do", async () => {
    mockQuota({
      modelBreakdownAvailable: false,
      models: [
        { modelId: "claude-sonnet-4.5", displayName: null, windows: [] },
        { modelId: "qwen3.8-max", displayName: null, windows: [] },
      ],
    });

    renderWithProviders(<OpenCodeGoQuotaCard />);

    expect(await screen.findByTestId("opencode-go-no-model-detail")).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.queryByText("claude-sonnet-4.5")).not.toBeInTheDocument();
  });

  it("discloses that the external Use balance setting is outside codex-lb", async () => {
    mockQuota();

    renderWithProviders(<OpenCodeGoQuotaCard />);

    expect(await screen.findByText(/"Use balance" setting is external to codex-lb/)).toBeInTheDocument();
  });

  describe("when the server reports a real model breakdown", () => {
    const perModel: Partial<OpenCodeGoQuotaResponse> = {
      scope: "per_model",
      modelBreakdownAvailable: true,
      models: [
        {
          modelId: "claude-sonnet-4.5",
          displayName: "Claude Sonnet 4.5",
          windows: [
            {
              key: "five_hour",
              upstreamKey: "rolling",
              status: "ok",
              percentUsed: 22,
              resetsAt: "2026-01-01T14:00:00.000Z",
              limitReached: false,
            },
            {
              key: "weekly",
              upstreamKey: "weekly",
              status: "ok",
              percentUsed: 61,
              resetsAt: "2026-01-05T00:00:00.000Z",
              limitReached: false,
            },
          ],
        },
        {
          modelId:
            "an-extremely-long-upstream-model-identifier-that-should-truncate-instead-of-stretching-the-grid",
          displayName: null,
          windows: [
            {
              key: "five_hour",
              upstreamKey: "rolling",
              status: "rate_limited",
              percentUsed: 96,
              resetsAt: "2026-01-01T13:00:00.000Z",
              limitReached: null,
            },
          ],
        },
      ],
    };

    it("lists per-model rows with a picker", async () => {
      mockQuota(perModel);

      renderWithProviders(<OpenCodeGoQuotaCard />);

      expect(await screen.findByText("Per-model limits")).toBeInTheDocument();
      expect(screen.getAllByTestId("opencode-go-model-row")).toHaveLength(2);
      expect(screen.getByRole("combobox", { name: "Model" })).toBeInTheDocument();
    });

    it("shows the raw model id when no display name was sent", async () => {
      mockQuota(perModel);

      renderWithProviders(<OpenCodeGoQuotaCard />);

      expect(
        await screen.findByText(/an-extremely-long-upstream-model-identifier/),
      ).toBeInTheDocument();
    });

    it("filters to one model by keyboard alone and returns focus", async () => {
      mockQuota(perModel);
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });

      renderWithProviders(<OpenCodeGoQuotaCard />);
      const trigger = await screen.findByRole("combobox", { name: "Model" });

      trigger.focus();
      expect(trigger).toHaveFocus();
      await user.keyboard("{Enter}");
      const listbox = await screen.findByRole("listbox");
      expect(within(listbox).getByRole("option", { name: "All models (2)" })).toBeInTheDocument();
      await user.keyboard("{ArrowDown}{Enter}");

      await waitFor(() => {
        expect(screen.getAllByTestId("opencode-go-model-row")).toHaveLength(1);
      });
      expect(
        within(screen.getByTestId("opencode-go-model-row")).getByText("Claude Sonnet 4.5"),
      ).toBeInTheDocument();
      // Keyboard users are not stranded: focus goes back to the trigger.
      expect(screen.getByRole("combobox", { name: "Model" })).toHaveFocus();
    });

    it("marks a rate-limited model window and badges the card", async () => {
      mockQuota(perModel);

      renderWithProviders(<OpenCodeGoQuotaCard />);

      expect(await screen.findByText("Rate limited by OpenCode")).toBeInTheDocument();
      expect(screen.getByText("At limit")).toBeInTheDocument();
    });
  });

  it("marks an exhausted window from limitReached", async () => {
    mockQuota({
      windows: [
        {
          key: "weekly",
          upstreamKey: "weekly",
          status: "ok",
          percentUsed: 100,
          resetsAt: "2026-01-05T00:00:00.000Z",
          limitReached: true,
        },
      ],
    });

    renderWithProviders(<OpenCodeGoQuotaCard />);

    expect(await screen.findByText("Limit reached")).toBeInTheDocument();
    expect(screen.getByText("At limit")).toBeInTheDocument();
  });

  it("does not badge the card when exhaustion is undeterminable", async () => {
    mockQuota({ windows: [UNKNOWN_WEEKLY] });

    renderWithProviders(<OpenCodeGoQuotaCard />);

    await screen.findByText("Unknown");
    expect(screen.queryByText("At limit")).not.toBeInTheDocument();
    expect(screen.queryByText("Limit reached")).not.toBeInTheDocument();
  });

  it("shows when the displayed numbers were obtained", async () => {
    mockQuota();

    renderWithProviders(<OpenCodeGoQuotaCard />);

    expect(await screen.findByTestId("opencode-go-freshness")).toHaveTextContent(/^Measured /);
  });

  it("admits the measurement time is unknown when no timestamp was reported", async () => {
    mockQuota({ checkedAt: null, refreshedAt: null });

    renderWithProviders(<OpenCodeGoQuotaCard />);

    expect(await screen.findByTestId("opencode-go-freshness")).toHaveTextContent(
      "Measurement time not reported",
    );
  });

  it("keeps last-good values visible and flags the failed refresh with its reason", async () => {
    mockQuota({ status: "stale", stale: true, staleReason: "connect timeout" });

    renderWithProviders(<OpenCodeGoQuotaCard />);

    expect(await screen.findByTestId("opencode-go-stale-badge")).toHaveTextContent("Stale");
    expect(screen.getByText("Could not refresh usage")).toBeInTheDocument();
    expect(
      screen.getByText(/Showing the last values that were read successfully/),
    ).toBeInTheDocument();
    expect(screen.getByText("connect timeout")).toBeInTheDocument();
    // The numbers stay on screen rather than being replaced by an error.
    expect(screen.getByText("42%")).toBeInTheDocument();
  });

  it("prompts configuration when Go is off", async () => {
    mockQuota({ status: "disabled", windows: [] });

    renderWithProviders(<OpenCodeGoQuotaCard />);

    const notice = await screen.findByTestId("opencode-go-quota-notice");
    expect(notice).toHaveAttribute("data-notice", "disabled");
    expect(within(notice).getByRole("link", { name: "Go settings" })).toBeInTheDocument();
    expect(screen.queryByTestId("opencode-go-window")).not.toBeInTheDocument();
  });

  it("prompts for a key when Go is enabled but unconfigured", async () => {
    mockQuota({ status: "not_configured", windows: [] });

    renderWithProviders(<OpenCodeGoQuotaCard />);

    expect(await screen.findByText("OpenCode Go is not configured")).toBeInTheDocument();
  });

  it("reports a rejected key without showing any quota numbers", async () => {
    mockQuota({ status: "unauthorized", windows: [] });

    renderWithProviders(<OpenCodeGoQuotaCard />);

    expect(await screen.findByText("OpenCode rejected the key")).toBeInTheDocument();
    expect(screen.queryByTestId("opencode-go-window-fill")).not.toBeInTheDocument();
  });

  it("does not present a throttled usage check as a model quota signal", async () => {
    mockQuota({ status: "rate_limited", windows: [] });

    renderWithProviders(<OpenCodeGoQuotaCard />);

    expect(await screen.findByText("Usage check rate limited")).toBeInTheDocument();
    expect(
      screen.getByText(/says nothing about your remaining model quota/),
    ).toBeInTheDocument();
    expect(screen.queryByText("At limit")).not.toBeInTheDocument();
  });

  it("treats an empty window list as unknown rather than an empty card", async () => {
    mockQuota({ status: "ok", windows: [] });

    renderWithProviders(<OpenCodeGoQuotaCard />);

    const notice = await screen.findByTestId("opencode-go-quota-notice");
    expect(notice).toHaveAttribute("data-notice", "unavailable");
    expect(screen.queryByTestId("opencode-go-window")).not.toBeInTheDocument();
  });

  it("reports a malformed snapshot as an integration fault, not an outage", async () => {
    server.use(http.get(QUOTA_ROUTE, () => HttpResponse.json({ unexpected: true })));

    renderWithProviders(<OpenCodeGoQuotaCard />);

    expect(await screen.findByTestId("opencode-go-quota-notice")).toHaveAttribute(
      "data-notice",
      "malformed",
    );
  });

  it("falls back to a local unavailable notice when the read fails", async () => {
    mockQuotaFailure(500);

    renderWithProviders(<OpenCodeGoQuotaCard />);

    expect(await screen.findByTestId("opencode-go-quota-notice")).toHaveAttribute(
      "data-notice",
      "unavailable",
    );
  });

  it("renders nothing at all when the deployment has no Go quota endpoint", async () => {
    mockQuotaFailure(404, "not_found");

    const { container } = renderWithProviders(<OpenCodeGoQuotaCard />);

    await waitFor(() => {
      expect(container).toBeEmptyDOMElement();
    });
  });
});

/**
 * Retaining a known-good snapshot when our own request to codex-lb fails.
 *
 * Throwing cached values away on a transient refetch replaces real numbers with
 * "unavailable", which is *less* true than what we already know. They are kept
 * and labelled as a failed refresh - never presented as current.
 */
describe("OpenCodeGoQuotaCard cached data", () => {
  const QUOTA_KEY = ["accounts", "opencode-go", "quota"];

  function mockThenFail(status = 500) {
    let calls = 0;
    server.use(
      http.get(QUOTA_ROUTE, () => {
        calls += 1;
        if (calls === 1) return HttpResponse.json(createOpenCodeGoQuota());
        return HttpResponse.json({ error: { code: "boom", message: "boom" } }, { status });
      }),
    );
  }

  it("keeps the last successful values visible when a refetch fails", async () => {
    mockThenFail();
    const { queryClient } = renderWithProviders(<OpenCodeGoQuotaCard />);
    expect(await screen.findByText("42%")).toBeInTheDocument();

    await queryClient.refetchQueries({ queryKey: QUOTA_KEY });

    await waitFor(() => expect(screen.getByTestId("opencode-go-stale-badge")).toBeInTheDocument());
    // The real numbers survive rather than collapsing to an error notice.
    expect(screen.getByText("42%")).toBeInTheDocument();
    expect(screen.getByText("68%")).toBeInTheDocument();
    expect(screen.queryByTestId("opencode-go-quota-notice")).not.toBeInTheDocument();
  });

  it("never presents retained values as current", async () => {
    mockThenFail();
    const { queryClient } = renderWithProviders(<OpenCodeGoQuotaCard />);
    await screen.findByText("42%");
    await queryClient.refetchQueries({ queryKey: QUOTA_KEY });

    await waitFor(() => expect(screen.getByTestId("opencode-go-degraded")).toBeInTheDocument());
    expect(screen.getByText("Could not reach codex-lb to refresh")).toBeInTheDocument();
    expect(
      screen.getByText(/Showing the last values that were read successfully/),
    ).toBeInTheDocument();
  });

  it("reports true freshness of the retained snapshot, not the failed attempt", async () => {
    mockThenFail();
    const { queryClient } = renderWithProviders(<OpenCodeGoQuotaCard />);
    await screen.findByText("42%");
    const before = screen.getByTestId("opencode-go-freshness").textContent;

    await queryClient.refetchQueries({ queryKey: QUOTA_KEY });
    await waitFor(() => expect(screen.getByTestId("opencode-go-stale-badge")).toBeInTheDocument());

    // The timestamp still describes when the displayed numbers were obtained.
    expect(screen.getByTestId("opencode-go-freshness")).toHaveTextContent(before ?? "");
  });

  it("does not attribute our own request failure to OpenCode", async () => {
    // The failing response body says "boom"; that belongs to a different request
    // and must not be shown as the upstream's stale reason.
    mockThenFail();
    const { queryClient } = renderWithProviders(<OpenCodeGoQuotaCard />);
    await screen.findByText("42%");
    await queryClient.refetchQueries({ queryKey: QUOTA_KEY });

    await waitFor(() => expect(screen.getByTestId("opencode-go-degraded")).toBeInTheDocument());
    expect(screen.queryByText("boom")).not.toBeInTheDocument();
  });

  it("keeps cached values across a remount while the endpoint is failing", async () => {
    mockThenFail();
    // The shared test client uses gcTime: 0, which evicts on unmount and would
    // make this vacuous. A real dashboard keeps the cache, so model that.
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 5 * 60_000 } },
    });
    const { unmount } = renderWithProviders(<OpenCodeGoQuotaCard />, { queryClient });
    expect(await screen.findByText("42%")).toBeInTheDocument();

    unmount();
    // Remounting against the same client refetches, and that refetch fails.
    renderWithProviders(<OpenCodeGoQuotaCard />, { queryClient });

    // Cached values are painted immediately on remount, then the background
    // refetch fails and the snapshot is marked as not-current.
    expect(screen.getByText("42%")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByTestId("opencode-go-stale-badge")).toBeInTheDocument(),
    );
    expect(screen.getByText("42%")).toBeInTheDocument();
  });

  it("recovers to a clean current state once the endpoint reconnects", async () => {
    mockThenFail();
    const { queryClient } = renderWithProviders(<OpenCodeGoQuotaCard />);
    await screen.findByText("42%");
    await queryClient.refetchQueries({ queryKey: QUOTA_KEY });
    await waitFor(() => expect(screen.getByTestId("opencode-go-stale-badge")).toBeInTheDocument());

    // Endpoint comes back with fresh numbers.
    server.use(
      http.get(QUOTA_ROUTE, () =>
        HttpResponse.json(
          createOpenCodeGoQuota({
            windows: [
              {
                key: "five_hour",
                upstreamKey: "rolling",
                status: "ok",
                percentUsed: 9,
                resetsAt: null,
                limitReached: false,
              },
            ],
          }),
        ),
      ),
    );
    await queryClient.refetchQueries({ queryKey: QUOTA_KEY });

    await waitFor(() => expect(screen.getByText("9%")).toBeInTheDocument());
    expect(screen.queryByTestId("opencode-go-stale-badge")).not.toBeInTheDocument();
    expect(screen.queryByTestId("opencode-go-degraded")).not.toBeInTheDocument();
  });

  it("retains values when a route that worked starts returning 404", async () => {
    // A 404 *after* a success proves the route existed, so it cannot be read as
    // "this deployment has no Go endpoint". Hiding the card here would silently
    // delete real numbers from the page.
    let calls = 0;
    server.use(
      http.get(QUOTA_ROUTE, () => {
        calls += 1;
        if (calls === 1) return HttpResponse.json(createOpenCodeGoQuota());
        return HttpResponse.json({ error: { code: "not_found", message: "Not Found" } }, { status: 404 });
      }),
    );
    const { queryClient, container } = renderWithProviders(<OpenCodeGoQuotaCard />);
    await screen.findByText("42%");

    await queryClient.refetchQueries({ queryKey: QUOTA_KEY });

    await waitFor(() =>
      expect(screen.getByText("Go usage endpoint stopped responding")).toBeInTheDocument(),
    );
    expect(container).not.toBeEmptyDOMElement();
    expect(screen.getByText("42%")).toBeInTheDocument();
    expect(screen.getByTestId("opencode-go-stale-badge")).toBeInTheDocument();
  });

  it("still hides the card when the route 404s and nothing was ever read", async () => {
    // The no-data 404 case is unchanged and stays distinct from retention.
    server.use(
      http.get(QUOTA_ROUTE, () =>
        HttpResponse.json({ error: { code: "not_found", message: "Not Found" } }, { status: 404 }),
      ),
    );

    const { container } = renderWithProviders(<OpenCodeGoQuotaCard />);

    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("names a vanished endpoint differently from an ordinary refresh failure", async () => {
    mockThenFail(500);
    const { queryClient } = renderWithProviders(<OpenCodeGoQuotaCard />);
    await screen.findByText("42%");
    await queryClient.refetchQueries({ queryKey: QUOTA_KEY });

    await waitFor(() =>
      expect(screen.getByText("Could not reach codex-lb to refresh")).toBeInTheDocument(),
    );
    expect(screen.queryByText("Go usage endpoint stopped responding")).not.toBeInTheDocument();
  });

  it("reports a switched-off integration instead of showing old numbers", async () => {
    let calls = 0;
    server.use(
      http.get(QUOTA_ROUTE, () => {
        calls += 1;
        if (calls === 1) return HttpResponse.json(createOpenCodeGoQuota());
        return HttpResponse.json(createOpenCodeGoQuota({ status: "disabled", windows: [] }));
      }),
    );
    const { queryClient } = renderWithProviders(<OpenCodeGoQuotaCard />);
    await screen.findByText("42%");

    await queryClient.refetchQueries({ queryKey: QUOTA_KEY });

    await waitFor(() => {
      expect(screen.getByTestId("opencode-go-quota-notice")).toHaveAttribute("data-notice", "disabled");
    });
    expect(screen.queryByText("42%")).not.toBeInTheDocument();
  });
});
