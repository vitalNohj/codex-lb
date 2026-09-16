import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { FreeModelDiscoveryPanel } from "@/features/settings/components/free-model-discovery-panel";
import type { DashboardSettings } from "@/features/settings/schemas";
import { server } from "@/test/mocks/server";

const SETTINGS = {
  openrouterSidecarEnabled: true,
  openrouterSidecarApiKeyConfigured: true,
  orcarouterSidecarEnabled: false,
  orcarouterSidecarApiKeyConfigured: false,
} as DashboardSettings;

function renderPanel(settings: DashboardSettings = SETTINGS) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <FreeModelDiscoveryPanel settings={settings} />
    </QueryClientProvider>,
  );
}

function runFixture(overrides: Record<string, unknown> = {}) {
  return {
    id: "run-1",
    status: "running",
    startedAt: "2026-01-01T00:00:00Z",
    finishedAt: null,
    deadlineAt: "2026-01-02T00:00:00Z",
    cancelRequested: false,
    pacingFloorSeconds: 20,
    pacingCapSeconds: 600,
    maxAttemptsPerItem: 12,
    errorMessage: null,
    counts: { total: 2, queued: 1, passed: 1, failed: 0, unresolved: 0, added: 1 },
    providers: [
      {
        provider: "openrouter",
        counts: { total: 2, queued: 1, passed: 1, failed: 0, unresolved: 0, added: 1 },
        currentIntervalSeconds: 40,
        nextProbeAt: "2026-01-01T00:01:00Z",
      },
    ],
    items: [
      {
        provider: "openrouter",
        modelId: "deepseek/deepseek-r1:free",
        group: "new",
        state: "passed",
        attempts: 1,
        lastHttpStatus: 200,
        lastOutcome: "200 with content",
        contentChars: 2,
        contentOkMatch: true,
        reasoningChars: 0,
        addedToFullModels: true,
        resolvedAt: "2026-01-01T00:00:30Z",
      },
      {
        provider: "openrouter",
        modelId: "qwen/qwen3-coder:free",
        group: "new",
        state: "queued",
        attempts: 1,
        nextAttemptAt: "2026-01-01T00:02:00Z",
        lastHttpStatus: 429,
        lastOutcome: "http 429: slow down",
        addedToFullModels: false,
      },
    ],
    ...overrides,
  };
}

describe("FreeModelDiscoveryPanel", () => {
  it("disables the button when no router is usable", async () => {
    renderPanel({
      ...SETTINGS,
      openrouterSidecarEnabled: false,
    } as DashboardSettings);

    expect(screen.getByRole("button", { name: "Discover free models" })).toBeDisabled();
    expect(screen.getByText(/Enable OpenRouter or OrcaRouter with an API key/)).toBeInTheDocument();
  });

  it("opens the plan dialog with grouped defaults and starts a run from the selection", async () => {
    const user = userEvent.setup();
    let startBody: unknown = null;
    server.use(
      http.post("*/api/free-model-discovery/runs", async ({ request }) => {
        startBody = await request.json();
        return HttpResponse.json(runFixture(), { status: 201 });
      }),
    );
    renderPanel();

    await user.click(screen.getByRole("button", { name: "Discover free models" }));

    const dialog = await screen.findByRole("dialog", { name: "Discover free models" });
    const openrouter = await within(dialog).findByRole("region", { name: "OpenRouter candidates" });
    expect(within(openrouter).getByText(/2 free of 3 listed, 1 already pinned/)).toBeInTheDocument();
    expect(within(dialog).getByText("Integration is disabled.")).toBeInTheDocument();

    const candidate = within(openrouter).getByRole("checkbox", { name: "Probe deepseek/deepseek-r1:free" });
    expect(candidate).toHaveAttribute("data-state", "checked");
    expect(within(dialog).getByRole("button", { name: "Start run (1)" })).toBeEnabled();

    await user.click(candidate);
    expect(within(dialog).getByRole("button", { name: "Start run (0)" })).toBeDisabled();
    await user.click(within(openrouter).getByRole("checkbox", { name: /Select all new openrouter models/ }));
    expect(within(dialog).getByRole("button", { name: "Start run (1)" })).toBeEnabled();

    await user.click(within(dialog).getByRole("button", { name: "Start run (1)" }));

    await waitFor(() => {
      expect(startBody).toEqual({
        selections: [{ provider: "openrouter", modelId: "deepseek/deepseek-r1:free" }],
      });
    });
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
  });

  it("keeps the dialog open and shows why when the server rejects the start", async () => {
    const user = userEvent.setup();
    server.use(
      http.post("*/api/free-model-discovery/runs", () =>
        HttpResponse.json(
          {
            error: {
              code: "discovery_execution_disabled",
              message:
                "Free model discovery cannot start because background automations are disabled. Enable the automations scheduler and try again.",
            },
          },
          { status: 409 },
        ),
      ),
    );
    renderPanel();

    await user.click(screen.getByRole("button", { name: "Discover free models" }));
    const dialog = await screen.findByRole("dialog", { name: "Discover free models" });
    const openrouter = await within(dialog).findByRole("region", { name: "OpenRouter candidates" });
    // `new` candidates are checked by default, so this one is already
    // selected; clicking it would DESELECT it and `handleStart` would return
    // early without ever calling the server, which is not what this test is
    // about. Assert the default selection instead and start from it.
    expect(within(openrouter).getByRole("checkbox", { name: "Probe deepseek/deepseek-r1:free" })).toBeChecked();
    await user.click(within(dialog).getByRole("button", { name: /^Start run/ }));

    // The rejection is actionable and the dialog does not silently close.
    expect(await within(dialog).findByText(/background automations are disabled/i)).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("renders the current run with progress, provider pacing and per-model outcomes", async () => {
    server.use(
      http.get("*/api/free-model-discovery/runs/current", () => HttpResponse.json(runFixture())),
    );
    renderPanel();

    const run = await screen.findByTestId("free-model-discovery-run");
    expect(within(run).getByText("Running")).toBeInTheDocument();
    expect(within(run).getByText("1/2 resolved")).toBeInTheDocument();
    expect(within(run).getByRole("progressbar", { name: "Discovery run progress" })).toHaveAttribute(
      "aria-valuenow",
      "1",
    );
    expect(within(run).getByText(/OpenRouter: 1 queued, pace 40s/)).toBeInTheDocument();
    const passedRow = within(run).getByText("deepseek/deepseek-r1:free").closest("li");
    expect(passedRow).not.toBeNull();
    expect(within(passedRow as HTMLElement).getByText("pinned")).toBeInTheDocument();
    expect(within(passedRow as HTMLElement).getByText("Passed")).toBeInTheDocument();
    expect(within(run).getByText(/HTTP 429/)).toBeInTheDocument();
    expect(within(run).getByText(/http 429: slow down/)).toBeInTheDocument();

    // While a run is active the start control both blocks and says why, so a
    // repeated click cannot start a second sweep and does not look broken.
    const startButton = screen.getByRole("button", { name: "Run in progress" });
    expect(startButton).toBeDisabled();
    expect(startButton).toHaveAttribute("title", "A discovery run is already in progress");
    expect(screen.queryByRole("button", { name: "Discover free models" })).toBeNull();
    expect(screen.getByRole("button", { name: "Cancel run" })).toBeEnabled();
  });

  it("keeps the start control blocked across repeated clicks while a run is active", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("*/api/free-model-discovery/runs/current", () => HttpResponse.json(runFixture())),
      http.post("*/api/free-model-discovery/runs", () =>
        HttpResponse.json({ error: { code: "discovery_run_active" } }, { status: 409 }),
      ),
    );
    renderPanel();

    const startButton = await screen.findByRole("button", { name: "Run in progress" });
    await user.click(startButton);
    await user.click(startButton);
    await user.click(startButton);

    // No dialog opens, so no second run can be confirmed from this panel.
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(startButton).toBeDisabled();
  });

  it("requests cancellation of the running run", async () => {
    const user = userEvent.setup();
    let cancelled = false;
    server.use(
      http.get("*/api/free-model-discovery/runs/current", () =>
        HttpResponse.json(runFixture({ cancelRequested: cancelled })),
      ),
      http.post("*/api/free-model-discovery/runs/run-1/cancel", () => {
        cancelled = true;
        return HttpResponse.json(runFixture({ cancelRequested: true }));
      }),
    );
    renderPanel();

    await user.click(await screen.findByRole("button", { name: "Cancel run" }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Cancelling..." })).toBeDisabled();
    });
    expect(cancelled).toBe(true);
  });

  it("shows a finished run and re-enables discovery", async () => {
    server.use(
      http.get("*/api/free-model-discovery/runs/current", () =>
        HttpResponse.json(
          runFixture({
            status: "completed",
            finishedAt: "2026-01-01T01:00:00Z",
            counts: { total: 2, queued: 0, passed: 1, failed: 1, unresolved: 0, added: 1 },
            providers: [],
          }),
        ),
      ),
    );
    renderPanel();

    const run = await screen.findByTestId("free-model-discovery-run");
    expect(within(run).getByText("Completed")).toBeInTheDocument();
    expect(within(run).getByText("2/2 resolved")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Discover free models" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Cancel run" })).toBeNull();
  });
});

describe("FreeModelDiscoveryPanel rate-limit reporting", () => {
  function serveRun(run: Record<string, unknown>) {
    server.use(
      http.get("*/api/free-model-discovery/runs/current", () => HttpResponse.json(run)),
    );
  }

  it("explains a provider-wide pause instead of looking like a stopped run", async () => {
    serveRun(
      runFixture({
        counts: {
          total: 3, queued: 3, passed: 0, failed: 0, unresolved: 0, added: 0,
          awaitingFirstAttempt: 2, retrying: 1,
        },
        providers: [
          {
            provider: "openrouter",
            counts: {
              total: 3, queued: 3, passed: 0, failed: 0, unresolved: 0, added: 0,
              awaitingFirstAttempt: 2, retrying: 1,
            },
            currentIntervalSeconds: 40,
            nextProbeAt: "2026-01-01T01:00:00Z",
            waitingReason: "Provider-wide limit reached; provider asked to wait 1h",
            limitScope: "shared",
            providerPaused: true,
          },
        ],
      }),
    );
    renderPanel();

    // The operator is told WHY nothing is moving, not left with a 0% bar.
    expect(await screen.findByText(/Provider-wide limit reached/)).toBeInTheDocument();
    expect(screen.getByText(/OpenRouter paused/)).toBeInTheDocument();
    // A retried item is distinguished from an untouched one. Shown in both the
    // run summary and the per-provider line, so assert on all matches.
    expect(screen.getAllByText(/1 retrying/).length).toBeGreaterThan(0);
  });

  it("reports an unknown-scope rate limit without claiming the account is exhausted", async () => {
    serveRun(
      runFixture({
        counts: {
          total: 1, queued: 1, passed: 0, failed: 0, unresolved: 0, added: 0,
          awaitingFirstAttempt: 0, retrying: 1,
        },
        providers: [],
        items: [
          {
            provider: "openrouter",
            modelId: "vendor/model:free",
            group: "new",
            state: "queued",
            attempts: 1,
            nextAttemptAt: "2026-01-01T00:02:00Z",
            lastHttpStatus: 429,
            lastOutcome: "http 429: Provider returned error",
            limitScope: "unknown",
            addedToFullModels: false,
          },
        ],
      }),
    );
    renderPanel();

    expect(await screen.findByText(/rate limited, scope unknown/)).toBeInTheDocument();
    // Must not assert a provider-wide block from an ambiguous rejection.
    expect(screen.queryByText(/provider-wide limit/i)).not.toBeInTheDocument();
  });

  it("does not present a run that evaluated nothing as a successful sweep", async () => {
    serveRun(
      runFixture({
        status: "completed",
        finishedAt: "2026-01-01T02:00:00Z",
        counts: {
          total: 2, queued: 0, passed: 0, failed: 0, unresolved: 2, added: 0,
          awaitingFirstAttempt: 0, retrying: 0,
        },
        providers: [],
        items: [],
      }),
    );
    renderPanel();

    expect(await screen.findByText(/ended without evaluating any model/)).toBeInTheDocument();
    expect(screen.getByText(/were not tested/)).toBeInTheDocument();
  });
});
