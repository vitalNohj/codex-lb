import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { CliproxyCredentials } from "@/features/settings/components/cliproxy-credentials";
import { server } from "@/test/mocks/server";

const TOKEN = "cliproxy-test-access-token";

function renderCredentials(enabled: boolean) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <CliproxyCredentials enabled={enabled} />
    </QueryClientProvider>,
  );
}

describe("CliproxyCredentials", () => {
  it("asks for a management key and does not fetch while disabled", () => {
    renderCredentials(false);

    expect(screen.getByText(/Add a management key to list CLIProxyAPI credentials/)).toBeInTheDocument();
    expect(screen.queryByText("grok@example.com")).not.toBeInTheDocument();
  });

  it("lists health, models, and provider badges without token fields", async () => {
    server.use(
      http.get("*/api/cliproxy/accounts", () =>
        HttpResponse.json({
          status: "healthy",
          message: null,
          providers: [
            {
              provider: "claude",
              credentials: [
                {
                  name: "claude-a.json",
                  authIndex: "c1",
                  email: "claude@example.com",
                  provider: "claude",
                  health: "active",
                  disabled: false,
                  unavailable: false,
                  quotaExceeded: false,
                  prefix: null,
                  models: ["claude-opus-5"],
                  modelsError: null,
                },
              ],
            },
            {
              provider: "xai",
              credentials: [
                {
                  name: "grok-a.json",
                  authIndex: "x1",
                  email: "grok@example.com",
                  provider: "xai",
                  health: "quota_exceeded",
                  disabled: false,
                  unavailable: false,
                  quotaExceeded: true,
                  prefix: "acct2",
                  models: ["grok-4", "grok-4-fast"],
                  modelsError: null,
                  access_token: TOKEN,
                },
              ],
            },
          ],
        }),
      ),
    );

    renderCredentials(true);

    expect(await screen.findByText("claude@example.com")).toBeInTheDocument();
    expect(screen.getByText("grok@example.com")).toBeInTheDocument();
    expect(screen.getByText("Healthy")).toBeInTheDocument();
    expect(screen.getByText("Quota exceeded")).toBeInTheDocument();
    expect(screen.getByText("claude-opus-5")).toBeInTheDocument();
    expect(screen.getByText("grok-4")).toBeInTheDocument();
    expect(screen.getByText("grok-4-fast")).toBeInTheDocument();
    expect(screen.getAllByText("claude").length).toBeGreaterThan(0);
    expect(screen.getAllByText("xai").length).toBeGreaterThan(0);
    expect(screen.getByText("acct2")).toBeInTheDocument();
    expect(screen.getByText("grok-a.json")).toBeInTheDocument();
    expect(screen.queryByText(TOKEN)).not.toBeInTheDocument();
    expect(screen.queryByText(/access_token/)).not.toBeInTheDocument();
  });

  it("shows grok quota windows, prepaid credits, and this-window usage", async () => {
    server.use(
      http.get("*/api/cliproxy/accounts", () =>
        HttpResponse.json({
          status: "healthy",
          message: null,
          providers: [
            {
              provider: "xai",
              credentials: [
                {
                  name: "grok-a.json",
                  authIndex: "x1",
                  email: "grok@example.com",
                  provider: "xai",
                  health: "rate_limited",
                  disabled: true,
                  unavailable: false,
                  quotaExceeded: false,
                  prefix: "acct2",
                  models: ["grok-4"],
                  modelsError: null,
                  quotaWindows: [
                    {
                      id: "credits",
                      label: "week",
                      kind: "weekly",
                      percentRemaining: 50,
                      resetsAt: "2099-01-01T00:00:00Z",
                    },
                  ],
                  prepaidCredits: 42,
                  usageTokens: 1200,
                  usageRequests: 3,
                },
              ],
            },
          ],
        }),
      ),
    );

    renderCredentials(true);

    expect(await screen.findByLabelText("Quota for grok@example.com")).toBeInTheDocument();
    expect(screen.getByText("week")).toBeInTheDocument();
    expect(screen.getByText(/50% left/)).toBeInTheDocument();
    expect(screen.getByText(/resets/)).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText(/3 requests/)).toBeInTheDocument();
    expect(screen.getByText(/1,200 tokens|1200 tokens/)).toBeInTheDocument();
    expect(screen.getByText("Rate limited")).toBeInTheDocument();
  });

  it("shows the management error without a credential list", async () => {
    server.use(
      http.get("*/api/cliproxy/accounts", () =>
        HttpResponse.json({
          status: "unauthorized",
          message: "CLIProxyAPI management key was rejected",
          providers: [],
        }),
      ),
    );

    renderCredentials(true);

    expect(await screen.findByText("CLIProxyAPI management key was rejected")).toBeInTheDocument();
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
  });

  it("confirms a tag change and turning off the last enabled account", async () => {
    const user = userEvent.setup();
    const fieldBodies: unknown[] = [];
    const statusBodies: unknown[] = [];
    server.use(
      http.get("*/api/cliproxy/accounts", () =>
        HttpResponse.json({
          status: "healthy",
          message: null,
          providers: [
            {
              provider: "xai",
              credentials: [
                {
                  name: "grok-a.json",
                  authIndex: "x1",
                  email: "grok@example.com",
                  provider: "xai",
                  health: "active",
                  disabled: false,
                  unavailable: false,
                  quotaExceeded: false,
                  prefix: null,
                  weight: null,
                  priority: null,
                  excludedModels: [],
                  excludedModelsState: "available",
                  models: ["grok-4"],
                  modelsError: null,
                },
              ],
            },
          ],
        }),
      ),
      http.patch("*/api/cliproxy/accounts/grok-a.json/fields", async ({ request }) => {
        fieldBodies.push(await request.json());
        return HttpResponse.json({
          name: "grok-a.json",
          prefix: "acct1",
          weight: null,
          priority: null,
          excludedModels: [],
          excludedModelsState: "available",
          disabled: false,
        });
      }),
      http.patch("*/api/cliproxy/accounts/grok-a.json/status", async ({ request }) => {
        statusBodies.push(await request.json());
        return HttpResponse.json({ name: "grok-a.json", disabled: true });
      }),
    );

    renderCredentials(true);

    const prefix = await screen.findByRole("textbox", { name: "Prefix for grok@example.com" });
    await user.type(prefix, "acct1");
    await user.click(screen.getByRole("button", { name: "Save tag for grok@example.com" }));
    expect(fieldBodies).toEqual([]);
    await user.click(screen.getByRole("button", { name: "Change tag" }));
    await waitFor(() => {
      expect(fieldBodies).toEqual([{ prefix: "acct1", confirm: true }]);
    });

    const enabled = screen.getByRole("switch", { name: "Enabled for grok@example.com" });
    await waitFor(() => expect(enabled).toBeEnabled());
    await user.click(enabled);
    expect(statusBodies).toEqual([]);
    expect(screen.getByRole("heading", { name: "Turn off the last enabled account?" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Turn off" }));
    await waitFor(() => {
      expect(statusBodies).toEqual([{ disabled: true, confirm: true }]);
    });
  });

  it("keeps an unsaved tag when weight autosave refreshes the card", async () => {
    const user = userEvent.setup();
    let weight: number | null = null;
    let reads = 0;
    server.use(
      http.get("*/api/cliproxy/accounts", () => {
        reads += 1;
        return HttpResponse.json({
          status: "healthy",
          message: null,
          providers: [
            {
              provider: "xai",
              credentials: [
                {
                  name: "grok-a.json",
                  authIndex: "x1",
                  email: "grok@example.com",
                  provider: "xai",
                  health: "active",
                  disabled: false,
                  unavailable: false,
                  quotaExceeded: false,
                  prefix: "acct2",
                  weight,
                  priority: null,
                  excludedModels: [],
                  excludedModelsState: "available",
                  models: ["grok-4"],
                  modelsError: null,
                },
              ],
            },
          ],
        });
      }),
      http.patch("*/api/cliproxy/accounts/grok-a.json/fields", async ({ request }) => {
        const body = (await request.json()) as { weight?: number };
        weight = body.weight ?? weight;
        return HttpResponse.json({
          name: "grok-a.json",
          prefix: "acct2",
          weight,
          priority: null,
          excludedModels: [],
          excludedModelsState: "available",
          disabled: false,
        });
      }),
    );

    renderCredentials(true);
    const prefix = await screen.findByRole("textbox", { name: "Prefix for grok@example.com" });
    await user.type(prefix, "acct9");
    const weightInput = screen.getByRole("textbox", { name: "Weight for grok@example.com" });
    await user.type(weightInput, "4");
    weightInput.blur();
    await waitFor(() => expect(reads).toBeGreaterThan(1));
    expect(screen.getByRole("textbox", { name: "Prefix for grok@example.com" })).toHaveValue("acct2acct9");
    expect(screen.getByRole("textbox", { name: "Weight for grok@example.com" })).toHaveValue("4");
    expect(screen.getByRole("button", { name: "Save tag for grok@example.com" })).toBeEnabled();
  });

  it("saves weight, priority, and excluded-model chips without confirmation", async () => {
    const user = userEvent.setup();
    const fieldBodies: unknown[] = [];
    const statusBodies: unknown[] = [];
    server.use(
      http.get("*/api/cliproxy/accounts", () =>
        HttpResponse.json({
          status: "healthy",
          message: null,
          providers: [
            {
              provider: "xai",
              credentials: [
                {
                  name: "grok-a.json",
                  authIndex: "x1",
                  email: "grok@example.com",
                  provider: "xai",
                  health: "active",
                  disabled: false,
                  unavailable: false,
                  quotaExceeded: false,
                  prefix: "acct2",
                  weight: null,
                  priority: null,
                  excludedModels: ["keep-me"],
                  excludedModelsState: "available",
                  models: ["grok-4"],
                  modelsError: null,
                },
                {
                  name: "grok-b.json",
                  authIndex: "x2",
                  email: "other@example.com",
                  provider: "xai",
                  health: "active",
                  disabled: false,
                  unavailable: false,
                  quotaExceeded: false,
                  prefix: "acct3",
                  weight: 1,
                  priority: 0,
                  excludedModels: [],
                  excludedModelsState: "available",
                  models: [],
                  modelsError: null,
                },
              ],
            },
          ],
        }),
      ),
      http.patch("*/api/cliproxy/accounts/:name/fields", async ({ request }) => {
        fieldBodies.push(await request.json());
        return HttpResponse.json({
          name: "grok-a.json",
          prefix: "acct2",
          weight: 4,
          priority: -2,
          excludedModels: [],
          excludedModelsState: "available",
          disabled: false,
        });
      }),
      http.patch("*/api/cliproxy/accounts/:name/status", async ({ request }) => {
        statusBodies.push(await request.json());
        return HttpResponse.json({ name: "grok-a.json", disabled: true });
      }),
    );

    renderCredentials(true);

    const weight = await screen.findByRole("textbox", { name: "Weight for grok@example.com" });
    await user.type(weight, "4");
    weight.blur();
    await waitFor(() => {
      expect(fieldBodies).toEqual([{ weight: 4 }]);
    });

    const priority = screen.getByRole("textbox", { name: "Priority for grok@example.com" });
    await user.type(priority, "-2");
    priority.blur();
    await waitFor(() => {
      expect(fieldBodies).toEqual([{ weight: 4 }, { priority: -2 }]);
    });

    await user.click(screen.getByRole("button", { name: "Remove keep-me from grok@example.com" }));
    await waitFor(() => {
      expect(fieldBodies).toEqual([{ weight: 4 }, { priority: -2 }, { excludedModels: [] }]);
    });

    const pattern = screen.getByRole("textbox", { name: "Add excluded model pattern for grok@example.com" });
    await user.type(pattern, "grok-extra-*");
    await user.click(screen.getByRole("button", { name: "Add excluded model pattern to grok-a.json" }));
    await waitFor(() => {
      expect(fieldBodies.at(-1)).toEqual({ excludedModels: ["keep-me", "grok-extra-*"] });
    });

    const enabled = screen.getByRole("switch", { name: "Enabled for grok@example.com" });
    await waitFor(() => expect(enabled).toBeEnabled());
    await user.click(enabled);
    expect(screen.queryByRole("heading", { name: "Turn off the last enabled account?" })).not.toBeInTheDocument();
    await waitFor(() => {
      expect(statusBodies).toEqual([{ disabled: true, confirm: false }]);
    });
  });

  it("deletes with one confirmation and does not send a separate disable", async () => {
    const user = userEvent.setup();
    const statusBodies: unknown[] = [];
    const deleteBodies: unknown[] = [];
    server.use(
      http.get("*/api/cliproxy/accounts", () =>
        HttpResponse.json({
          status: "healthy",
          message: null,
          providers: [
            {
              provider: "xai",
              credentials: [
                {
                  name: "grok-a.json",
                  authIndex: "x1",
                  email: "grok@example.com",
                  provider: "xai",
                  health: "active",
                  disabled: false,
                  unavailable: false,
                  quotaExceeded: false,
                  prefix: "acct2",
                  models: ["grok-4"],
                  modelsError: null,
                  excludedModels: [],
                  excludedModelsState: "available",
                },
              ],
            },
          ],
        }),
      ),
      http.patch("*/api/cliproxy/accounts/grok-a.json/status", async ({ request }) => {
        statusBodies.push(await request.json());
        return HttpResponse.json({ name: "grok-a.json", disabled: true });
      }),
      http.delete("*/api/cliproxy/accounts/grok-a.json", async ({ request }) => {
        deleteBodies.push(await request.json());
        return HttpResponse.json({ name: "grok-a.json", disabled: true, deleted: true });
      }),
    );

    renderCredentials(true);
    await user.click(await screen.findByRole("button", { name: "Delete grok@example.com" }));
    expect(deleteBodies).toEqual([]);
    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(deleteBodies).toEqual([{ confirm: true }]);
    expect(statusBodies).toEqual([]);
  });

  it("shows refresh status as the poll moves from pending to ok", async () => {
    const user = userEvent.setup();
    let polls = 0;
    server.use(
      http.get("*/api/cliproxy/accounts", () =>
        HttpResponse.json({
          status: "healthy",
          message: null,
          providers: [
            {
              provider: "claude",
              credentials: [
                {
                  name: "claude-a.json",
                  authIndex: "c1",
                  email: "claude@example.com",
                  provider: "claude",
                  health: "active",
                  disabled: false,
                  unavailable: false,
                  quotaExceeded: false,
                  prefix: null,
                  models: [],
                  modelsError: null,
                  excludedModels: [],
                  excludedModelsState: "available",
                },
              ],
            },
          ],
        }),
      ),
      http.post("*/api/cliproxy/accounts/claude-a.json/refresh", () =>
        HttpResponse.json({ name: "claude-a.json", status: "pending", message: null }),
      ),
      http.get("*/api/cliproxy/accounts/claude-a.json/refresh", () => {
        polls += 1;
        const status = polls === 1 ? "pending" : "ok";
        return HttpResponse.json({ name: "claude-a.json", status, message: null });
      }),
    );

    renderCredentials(true);
    await user.click(await screen.findByRole("button", { name: "Refresh claude@example.com" }));
    expect(await screen.findByText("Refreshing")).toBeInTheDocument();
    expect(await screen.findByText("Refreshed", {}, { timeout: 4000 })).toBeInTheDocument();
    expect(polls).toBeGreaterThan(1);
  });

  it("shows a device sign-in code and then success", async () => {
    const user = userEvent.setup();
    let statusPolls = 0;
    server.use(
      http.get("*/api/cliproxy/accounts", () =>
        HttpResponse.json({ status: "healthy", message: null, providers: [] }),
      ),
      http.get("*/api/cliproxy/oauth/providers", () =>
        HttpResponse.json({
          providers: [{ provider: "xai", method: "device" }],
        }),
      ),
      http.post("*/api/cliproxy/oauth/xai/authorize", () =>
        HttpResponse.json({
          state: "xai-device-state",
          provider: "xai",
          method: "device",
          authorizationUrl: null,
          verificationUrl: "https://auth.example/device",
          userCode: "ABCD-1234",
          intervalSeconds: 1,
          expiresInSeconds: null,
        }),
      ),
      http.get("*/api/cliproxy/oauth/status", () => {
        statusPolls += 1;
        return HttpResponse.json(
          statusPolls === 1
            ? { status: "pending", errorMessage: null }
            : { status: "success", errorMessage: null },
        );
      }),
    );

    renderCredentials(true);
    await user.click(await screen.findByRole("button", { name: "Sign in" }));
    await user.click(await screen.findByRole("button", { name: /xAI/ }));
    await user.click(screen.getByRole("button", { name: "Start sign-in" }));
    expect(await screen.findByText("ABCD-1234")).toBeInTheDocument();
    expect(await screen.findByText("Sign-in complete", {}, { timeout: 3000 })).toBeInTheDocument();
    expect(screen.queryByText(/access_token/)).not.toBeInTheDocument();
    expect(statusPolls).toBeGreaterThan(1);
  });

  it("cancels a pending device sign-in", async () => {
    const user = userEvent.setup();
    const cancels: string[] = [];
    server.use(
      http.get("*/api/cliproxy/accounts", () =>
        HttpResponse.json({ status: "healthy", message: null, providers: [] }),
      ),
      http.get("*/api/cliproxy/oauth/providers", () =>
        HttpResponse.json({
          providers: [{ provider: "xai", method: "device" }],
        }),
      ),
      http.post("*/api/cliproxy/oauth/xai/authorize", () =>
        HttpResponse.json({
          state: "xai-device-state",
          provider: "xai",
          method: "device",
          authorizationUrl: null,
          verificationUrl: "https://auth.example/device",
          userCode: "ABCD-1234",
          intervalSeconds: 30,
          expiresInSeconds: null,
        }),
      ),
      http.get("*/api/cliproxy/oauth/status", () => HttpResponse.json({ status: "pending", errorMessage: null })),
      http.delete("*/api/cliproxy/oauth/session", ({ request }) => {
        cancels.push(request.url);
        return HttpResponse.json({ status: "ok", cancelled: true });
      }),
    );

    renderCredentials(true);
    await user.click(await screen.findByRole("button", { name: "Sign in" }));
    await user.click(await screen.findByRole("button", { name: /xAI/ }));
    await user.click(screen.getByRole("button", { name: "Start sign-in" }));
    expect(await screen.findByText("ABCD-1234")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(cancels).toHaveLength(1);
    expect(cancels[0]).toContain("state=xai-device-state");
  });

  it("cancels a sign-in that finishes after the dialog closes", async () => {
    const user = userEvent.setup();
    const cancels: string[] = [];
    server.use(
      http.get("*/api/cliproxy/accounts", () =>
        HttpResponse.json({ status: "healthy", message: null, providers: [] }),
      ),
      http.get("*/api/cliproxy/oauth/providers", () =>
        HttpResponse.json({
          providers: [{ provider: "xai", method: "device" }],
        }),
      ),
      http.post("*/api/cliproxy/oauth/xai/authorize", async () => {
        await new Promise((resolve) => setTimeout(resolve, 200));
        return HttpResponse.json({
          state: "xai-late-state",
          provider: "xai",
          method: "device",
          authorizationUrl: null,
          verificationUrl: "https://auth.example/device",
          userCode: "LATE-1111",
          intervalSeconds: 30,
          expiresInSeconds: null,
        });
      }),
      http.delete("*/api/cliproxy/oauth/session", ({ request }) => {
        cancels.push(request.url);
        return HttpResponse.json({ status: "ok", cancelled: true });
      }),
    );

    renderCredentials(true);
    await user.click(await screen.findByRole("button", { name: "Sign in" }));
    await user.click(await screen.findByRole("button", { name: /xAI/ }));
    await user.click(screen.getByRole("button", { name: "Start sign-in" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await screen.findByRole("button", { name: "Sign in" });
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(screen.queryByText("LATE-1111")).not.toBeInTheDocument();
    expect(cancels).toHaveLength(1);
    expect(cancels[0]).toContain("state=xai-late-state");
  });
});
