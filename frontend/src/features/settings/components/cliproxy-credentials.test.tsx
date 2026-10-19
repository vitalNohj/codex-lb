import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { CliproxyCredentials } from "@/features/settings/components/cliproxy-credentials";
import { createDashboardSettings } from "@/test/mocks/factories";
import { server } from "@/test/mocks/server";

const TOKEN = "cliproxy-test-access-token";

async function expandModelLists(user: ReturnType<typeof userEvent.setup>) {
  for (const toggle of await screen.findAllByRole("button", { name: /^Models \(/ })) {
    await user.click(toggle);
  }
}

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

    expect(screen.getByText(/Save a CLIProxyAPI management key above/)).toBeInTheDocument();
    expect(screen.queryByText("grok@example.com")).not.toBeInTheDocument();
  });

  it("lists health, models, and provider badges without token fields", async () => {
    const user = userEvent.setup();
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
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByText("Quota exhausted")).toBeInTheDocument();
    expect(screen.queryByText("grok-4-fast")).not.toBeInTheDocument();
    await expandModelLists(user);
    expect(screen.getAllByText("claude-opus-5").length).toBeGreaterThan(0);
    expect(screen.getAllByText("grok-4").length).toBeGreaterThan(0);
    expect(screen.getAllByText("grok-4-fast").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Claude").length).toBeGreaterThan(0);
    expect(screen.getAllByText("xAI").length).toBeGreaterThan(0);
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
    expect(screen.getByText("50%")).toBeInTheDocument();
    expect(screen.getByText(/^Resets /)).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText(/3 req · (1,200|1200) tok/)).toBeInTheDocument();
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

  it("confirms turning off the last enabled account", async () => {
    const user = userEvent.setup();
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
      http.patch("*/api/cliproxy/accounts/grok-a.json/status", async ({ request }) => {
        statusBodies.push(await request.json());
        return HttpResponse.json({ name: "grok-a.json", disabled: true });
      }),
    );

    renderCredentials(true);

    expect(await screen.findByText("acct2")).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Prefix for grok@example.com" })).not.toBeInTheDocument();
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

  it("adds an API-key account and a discovered model without showing the key", async () => {
    const user = userEvent.setup();
    const created: unknown[] = [];
    const catalog: unknown[] = [];
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
                },
              ],
            },
          ],
          apiKeys: [
            {
              id: "key-openrouter",
              kind: "openai-compatibility",
              index: 0,
              name: "openrouter",
              baseUrl: "https://openrouter.ai/api/v1",
              disabled: false,
              supportsDisable: true,
              hasApiKey: true,
              models: [{ name: "grok-4", alias: "grok-4" }],
              discoveredModels: ["grok-4"],
              modelsError: null,
              authIndex: "k1",
              prefix: "keep-me",
              apiKey: "sk-should-not-render",
            },
          ],
          sharedModelIds: ["grok-4"],
        }),
      ),
      http.get("*/api/settings", () =>
        HttpResponse.json(createDashboardSettings({ claudeSidecarFullModels: [] })),
      ),
      http.post("*/api/cliproxy/api-keys", async ({ request }) => {
        created.push(await request.json());
        return HttpResponse.json({
          id: "key-second",
          kind: "openai-compatibility",
          index: 1,
          name: "second",
          baseUrl: "https://example.test/v1",
          disabled: false,
          supportsDisable: true,
          hasApiKey: true,
          models: [{ name: "openai/gpt-4o", alias: "openai/gpt-4o" }],
          discoveredModels: [],
          prefix: null,
          apiKey: "sk-created-secret",
        });
      }),
      http.post("*/api/cliproxy/catalog/models", async ({ request }) => {
        catalog.push(await request.json());
        return HttpResponse.json({ model: "grok-4", fullModels: ["grok-4"] });
      }),
    );

    renderCredentials(true);

    expect(await screen.findByText(/Shared models are served by more than one account/)).toBeInTheDocument();
    expect(screen.getByText("keep-me")).toBeInTheDocument();
    expect(screen.getAllByText("Not reported").length).toBeGreaterThan(0);
    expect(screen.queryByText("sk-should-not-render")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Prefix for grok@example.com" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Add API key" }));
    await user.selectOptions(await screen.findByLabelText("Provider"), "openai-compatibility");
    const [accountName] = screen.getAllByLabelText("Name");
    const [baseUrl] = screen.getAllByLabelText("Base URL");
    const [models] = screen.getAllByLabelText("Models");
    await user.type(accountName, "second");
    await user.type(baseUrl, "https://example.test/v1");
    await user.type(screen.getByLabelText("API key"), "sk-created-secret");
    await user.type(models, "openai/gpt-4o");
    await user.click(screen.getByRole("button", { name: "Add account" }));
    await waitFor(() => {
      expect(created).toEqual([
        {
          kind: "openai-compatibility",
          name: "second",
          baseUrl: "https://example.test/v1",
          apiKey: "sk-created-secret",
          models: ["openai/gpt-4o"],
        },
      ]);
    });
    expect(screen.queryByDisplayValue("sk-created-secret")).not.toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

    await expandModelLists(user);
    expect(screen.getAllByText("shared").length).toBeGreaterThan(0);
    const addButtons = screen.getAllByRole("button", { name: "Add grok-4 to codex-lb" });
    await user.click(addButtons[0]);
    await waitFor(() => {
      expect(catalog).toEqual([{ model: "grok-4" }]);
    });
  });

  it("forgets a typed API key when the add dialog is canceled", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("*/api/cliproxy/accounts", () =>
        HttpResponse.json({ status: "healthy", message: null, providers: [], apiKeys: [], sharedModelIds: [] }),
      ),
    );

    renderCredentials(true);

    await user.click(await screen.findByRole("button", { name: "Add API key" }));
    await user.type(await screen.findByLabelText("API key"), "sk-canceled-secret");
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Add API key" }));
    expect(await screen.findByLabelText("API key")).toHaveValue("");
    expect(screen.queryByDisplayValue("sk-canceled-secret")).not.toBeInTheDocument();
  });

  it("keeps model mappings and spaced names out of unrelated saves", async () => {
    const user = userEvent.setup();
    const updates: unknown[] = [];
    server.use(
      http.get("*/api/cliproxy/accounts", () =>
        HttpResponse.json({
          status: "healthy",
          message: null,
          providers: [],
          apiKeys: [
            {
              id: "spaced-name",
              kind: "openai-compatibility",
              index: 0,
              name: "My OpenRouter",
              baseUrl: "https://openrouter.ai/api/v1",
              disabled: false,
              supportsDisable: true,
              hasApiKey: true,
              models: [{ name: "upstream-model", alias: "friendly-model" }],
              discoveredModels: ["friendly-model"],
              modelsError: null,
              prefix: null,
            },
          ],
        }),
      ),
      http.get("*/api/settings", () => HttpResponse.json(createDashboardSettings({ claudeSidecarFullModels: [] }))),
      http.patch("*/api/cliproxy/api-keys/openai-compatibility/0", async ({ request }) => {
        updates.push(await request.json());
        return HttpResponse.json({
          id: "spaced-name",
          kind: "openai-compatibility",
          index: 0,
          name: "My OpenRouter",
          baseUrl: "https://openrouter.ai/api/v1",
          disabled: true,
          supportsDisable: true,
          hasApiKey: true,
          models: [{ name: "upstream-model", alias: "friendly-model" }],
          discoveredModels: ["friendly-model"],
        });
      }),
    );

    renderCredentials(true);
    await user.click(await screen.findByRole("switch", { name: "Enabled for My OpenRouter" }));
    await waitFor(() => {
      expect(updates).toEqual([
        {
          kind: "openai-compatibility",
          accountId: "spaced-name",
          baseUrl: "https://openrouter.ai/api/v1",
          disabled: true,
        },
      ]);
    });

    await user.click(screen.getByRole("button", { name: "Edit My OpenRouter" }));
    const url = document.getElementById("cliproxy-api-key-url-spaced-name");
    if (!(url instanceof HTMLInputElement)) {
      throw new Error("missing base URL field");
    }
    await user.clear(url);
    await user.type(url, "https://proxy.example/v1");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(updates[1]).toEqual({
        kind: "openai-compatibility",
        accountId: "spaced-name",
        baseUrl: "https://proxy.example/v1",
      });
    });
    expect(updates[1]).not.toHaveProperty("name");
    expect(updates[1]).not.toHaveProperty("models");
  });

  it("toggles the prompt cache key on an OpenAI-compatible group and shows key groups", async () => {
    const user = userEvent.setup();
    const updates: unknown[] = [];
    const compat = {
      id: "nv-group",
      kind: "openai-compatibility",
      index: 0,
      name: "nv",
      baseUrl: "https://integrate.api.nvidia.com/v1",
      disabled: false,
      supportsDisable: true,
      hasApiKey: true,
      keyCount: 2,
      models: [],
      discoveredModels: [],
      supportPromptCacheKey: false,
    };
    server.use(
      http.get("*/api/cliproxy/accounts", () =>
        HttpResponse.json({
          status: "healthy",
          message: null,
          providers: [],
          apiKeys: [
            compat,
            {
              id: "pool-b",
              kind: "claude",
              index: 1,
              name: "Claude API key 2",
              group: "shared-pool",
              baseUrl: "https://api.anthropic.com",
              supportsDisable: false,
              hasApiKey: true,
              models: [],
              discoveredModels: [],
              supportPromptCacheKey: null,
            },
          ],
        }),
      ),
      http.get("*/api/settings", () => HttpResponse.json(createDashboardSettings({ claudeSidecarFullModels: [] }))),
      http.patch("*/api/cliproxy/api-keys/openai-compatibility/0", async ({ request }) => {
        updates.push(await request.json());
        return HttpResponse.json({ ...compat, supportPromptCacheKey: true });
      }),
    );

    renderCredentials(true);
    const pool = await screen.findByRole("article", { name: "Claude API-key account Claude API key 2" });
    expect(within(pool).getByText("Group")).toBeInTheDocument();
    expect(within(pool).getByText("shared-pool")).toBeInTheDocument();
    expect(screen.getByText(/Routing pins this group, not one of its 2 keys/)).toBeInTheDocument();
    expect(screen.queryByRole("switch", { name: "Send prompt cache key for Claude API key 2" })).toBeNull();
    await user.click(screen.getByRole("switch", { name: "Send prompt cache key for nv" }));
    await waitFor(() => {
      expect(updates).toEqual([
        {
          kind: "openai-compatibility",
          accountId: "nv-group",
          baseUrl: "https://integrate.api.nvidia.com/v1",
          supportPromptCacheKey: true,
        },
      ]);
    });
  });

  it("drops a deleted account's drafts instead of saving them onto the next account", async () => {
    const user = userEvent.setup();
    const updates: unknown[] = [];
    const removed: unknown[] = [];
    let accounts = [
      {
        id: "account-a",
        kind: "openai-compatibility",
        index: 0,
        name: "first",
        baseUrl: "https://first.example/v1",
        disabled: false,
        supportsDisable: true,
        hasApiKey: true,
        models: [{ name: "one", alias: "one" }],
        discoveredModels: ["one"],
        modelsError: null,
        prefix: null,
      },
      {
        id: "account-b",
        kind: "openai-compatibility",
        index: 1,
        name: "second",
        baseUrl: "https://kept.example/v1",
        disabled: false,
        supportsDisable: true,
        hasApiKey: true,
        models: [{ name: "two", alias: "two" }],
        discoveredModels: ["two"],
        modelsError: null,
        prefix: null,
      },
    ];
    server.use(
      http.get("*/api/cliproxy/accounts", () =>
        HttpResponse.json({
          status: "healthy",
          message: null,
          providers: [],
          apiKeys: accounts,
        }),
      ),
      http.get("*/api/settings", () => HttpResponse.json(createDashboardSettings({ claudeSidecarFullModels: [] }))),
      http.delete("*/api/cliproxy/api-keys/openai-compatibility/0", async ({ request }) => {
        removed.push(await request.json());
        accounts = [{ ...accounts[1], index: 0 }];
        return HttpResponse.json({ kind: "openai-compatibility", index: 0, deleted: true });
      }),
      http.patch("*/api/cliproxy/api-keys/openai-compatibility/:index", async ({ request }) => {
        updates.push(await request.json());
        return HttpResponse.json(accounts[0]);
      }),
    );

    renderCredentials(true);
    await user.click(await screen.findByRole("button", { name: "Edit first" }));
    const leakedUrl = await screen.findByDisplayValue("https://first.example/v1");
    const leakedSecret = document.getElementById("cliproxy-api-key-secret-account-a");
    if (!(leakedSecret instanceof HTMLInputElement)) {
      throw new Error("missing first account editor");
    }
    await user.clear(leakedUrl);
    await user.type(leakedUrl, "https://deleted.example/v1");
    await user.type(leakedSecret, "leaked-secret");
    await user.click(await screen.findByRole("button", { name: "Delete first" }));
    await user.click(screen.getByRole("button", { name: "Remove" }));
    await waitFor(() => {
      expect(removed).toEqual([{ confirm: true, accountId: "account-a" }]);
    });

    await waitFor(() => expect(screen.queryByText("first")).not.toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Edit second" }));
    const keptUrl = await screen.findByDisplayValue("https://kept.example/v1");
    expect(keptUrl).toBeInTheDocument();
    expect(screen.queryByDisplayValue("https://deleted.example/v1")).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue("leaked-secret")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(updates).toEqual([
        {
          kind: "openai-compatibility",
          accountId: "account-b",
          baseUrl: "https://kept.example/v1",
        },
      ]);
    });
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

    await user.click(await screen.findByRole("button", { name: "Routing settings for grok@example.com" }));
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

  it("saves a replacement prefix and leaves an emptied prefix unchanged", async () => {
    const user = userEvent.setup();
    const fieldBodies: unknown[] = [];
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
      http.patch("*/api/cliproxy/accounts/:name/fields", async ({ request }) => {
        fieldBodies.push(await request.json());
        return HttpResponse.json({
          name: "grok-a.json",
          prefix: "newpin",
          weight: null,
          priority: null,
          excludedModels: [],
          excludedModelsState: "available",
          disabled: false,
        });
      }),
    );

    renderCredentials(true);

    expect(await screen.findByText("acct2")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Routing settings for grok@example.com" }));
    const prefix = screen.getByRole("textbox", { name: "Prefix for grok@example.com" });
    await user.clear(prefix);
    prefix.blur();
    expect(fieldBodies).toEqual([]);
    await user.type(prefix, "newpin");
    prefix.blur();
    await waitFor(() => {
      expect(fieldBodies).toEqual([{ prefix: "newpin" }]);
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
    expect(await screen.findByText("Refreshing...")).toBeInTheDocument();
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
