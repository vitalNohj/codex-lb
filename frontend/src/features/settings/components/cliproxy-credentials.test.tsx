import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
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
    expect(screen.getByText("prefix acct2")).toBeInTheDocument();
    expect(screen.getByText("grok-a.json")).toBeInTheDocument();
    expect(screen.queryByText(TOKEN)).not.toBeInTheDocument();
    expect(screen.queryByText(/access_token/)).not.toBeInTheDocument();
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
});
