import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { OpenCodeGoSidecarSettings } from "@/features/settings/components/opencode-go-sidecar-settings";
import type { DashboardSettings } from "@/features/settings/schemas";
import { createDashboardSettings } from "@/test/mocks/factories";
import { server } from "@/test/mocks/server";

const CONFIGURED_SETTINGS = createDashboardSettings({
  opencodeGoSidecarApiKeyConfigured: true,
});

const ENABLED_SETTINGS = createDashboardSettings({
  opencodeGoSidecarEnabled: true,
  opencodeGoSidecarApiKeyConfigured: true,
});

const UNCONFIGURED_SETTINGS = createDashboardSettings();

function renderSettings(settings: DashboardSettings, onSave = vi.fn().mockResolvedValue(undefined)) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const utils = render(
    <QueryClientProvider client={queryClient}>
      <OpenCodeGoSidecarSettings settings={settings} busy={false} onSave={onSave} />
    </QueryClientProvider>,
  );
  return { ...utils, onSave };
}

/** Replaces the status route for one test. */
function useStatus(body: Record<string, unknown> | null, status = 200) {
  server.use(
    http.get("*/api/opencode-go-sidecar/status", () =>
      body === null ? new HttpResponse(null, { status }) : HttpResponse.json(body),
    ),
  );
}

async function openDiscoveredModels(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: /Discovered models/i }));
}

describe("OpenCodeGoSidecarSettings", () => {
  it("labels the section as the OpenCode Go integration", () => {
    renderSettings(CONFIGURED_SETTINGS);

    expect(screen.getByRole("heading", { name: "OpenCode Go Integration" })).toBeInTheDocument();
  });

  it("starts disabled and does not enable itself when models are discovered", async () => {
    const user = userEvent.setup();
    // Enabled settings so discovery actually runs; enabling must still be a
    // separate deliberate act, never a consequence of discovering models.
    const { onSave } = renderSettings(ENABLED_SETTINGS);

    await openDiscoveredModels(user);
    await screen.findAllByText("glm-5.3");

    onSave.mockClear();
    expect(onSave).not.toHaveBeenCalled();
  });

  it("does not discover models while the integration is disabled, and says so honestly", async () => {
    const user = userEvent.setup();
    renderSettings(CONFIGURED_SETTINGS);

    await openDiscoveredModels(user);

    expect(screen.getByRole("switch", { name: "Enable OpenCode Go Integration" })).not.toBeChecked();
    expect(screen.queryByText("glm-5.3")).not.toBeInTheDocument();
    // The backend returns an empty catalogue without an upstream call while
    // disabled, so the UI must not report that as "no models exist".
    expect(
      await screen.findByText(/not discovered while the integration is disabled/i),
    ).toBeInTheDocument();
    expect(screen.queryByText("No models returned by OpenCode Go.")).not.toBeInTheDocument();
  });

  it("enables the integration only from the deliberate toggle", async () => {
    const user = userEvent.setup();
    const { onSave } = renderSettings(CONFIGURED_SETTINGS);

    await user.click(screen.getByRole("switch", { name: "Enable OpenCode Go Integration" }));

    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith({ opencodeGoSidecarEnabled: true }),
    );
  });

  describe("secret handling", () => {
    it("never renders the stored key and shows only its configured state", () => {
      renderSettings(CONFIGURED_SETTINGS);

      const field = screen.getByLabelText(/API key/);
      expect(field).toHaveValue("");
      expect(field).toHaveAttribute("type", "password");
      expect(field).toHaveAttribute("placeholder", "Configured");
    });

    it("adds a key and runs the connection test after saving", async () => {
      const user = userEvent.setup();
      const testSpy = vi.fn();
      server.use(
        http.post("*/api/opencode-go-sidecar/test", () => {
          testSpy();
          return HttpResponse.json({
            enabled: true,
            configured: true,
            status: "healthy",
            message: "OpenCode Go reachable",
            baseUrl: "https://opencode.ai/zen/go/v1",
            modelCount: 0,
            lastCheckedAt: "2026-01-01T00:00:00Z",
            models: [],
          });
        }),
      );
      const { onSave } = renderSettings(UNCONFIGURED_SETTINGS);

      await user.type(screen.getByLabelText(/API key/), "sk-go-secret");
      await user.click(screen.getByRole("button", { name: "Add API key" }));

      await waitFor(() =>
        expect(onSave).toHaveBeenLastCalledWith(
          expect.objectContaining({ opencodeGoSidecarApiKey: "sk-go-secret" }),
        ),
      );
      expect(screen.getByLabelText(/API key/)).toHaveValue("");
      await waitFor(() => expect(testSpy).toHaveBeenCalledTimes(1));
    });

    it("does not send a key field when an unrelated field is saved", async () => {
      const user = userEvent.setup();
      const { onSave } = renderSettings(CONFIGURED_SETTINGS);

      const baseUrl = screen.getByLabelText("Base URL");
      await user.clear(baseUrl);
      await user.type(baseUrl, "https://opencode.ai/zen/go/v1{Enter}");

      await waitFor(() => expect(onSave).toHaveBeenCalled());
      for (const [patch] of onSave.mock.calls) {
        expect(patch).not.toHaveProperty("opencodeGoSidecarApiKey");
        expect(patch).not.toHaveProperty("opencodeGoSidecarClearApiKey");
      }
    });

    it("clears the stored key only after an explicit confirmation", async () => {
      const user = userEvent.setup();
      const { onSave } = renderSettings(CONFIGURED_SETTINGS);

      await user.click(screen.getByRole("button", { name: "Remove stored key" }));
      expect(onSave).not.toHaveBeenCalledWith({ opencodeGoSidecarClearApiKey: true });

      await user.click(screen.getByRole("button", { name: "Remove key" }));

      await waitFor(() =>
        expect(onSave).toHaveBeenCalledWith({ opencodeGoSidecarClearApiKey: true }),
      );
    });

    it("offers no key removal when no key is stored", () => {
      renderSettings(UNCONFIGURED_SETTINGS);

      expect(screen.queryByRole("button", { name: "Remove stored key" })).not.toBeInTheDocument();
    });

    it("keeps the key out of every rendered surface", async () => {
      const user = userEvent.setup();
      const { container } = renderSettings(ENABLED_SETTINGS);

      await user.type(screen.getByLabelText(/API key/), "sk-go-should-not-leak");
      await openDiscoveredModels(user);
      await screen.findAllByText("glm-5.3");

      expect(container.textContent).not.toContain("sk-go-should-not-leak");
    });
  });

  describe("connection states", () => {
    it("asks for a key before claiming any connection state", async () => {
      renderSettings(UNCONFIGURED_SETTINGS);

      expect(await screen.findByText(/No API key stored/i)).toBeInTheDocument();
    });

    it("reports an upstream auth failure as an auth failure", async () => {
      useStatus({
        enabled: true,
        configured: true,
        status: "unauthorized",
        message: "Invalid API key",
        baseUrl: "https://opencode.ai/zen/go/v1",
        modelCount: null,
        lastCheckedAt: "2026-01-01T00:00:00Z",
      });
      renderSettings(ENABLED_SETTINGS);

      expect(await screen.findByText(/rejected the stored key/i)).toBeInTheDocument();
    });

    it("reports an unreachable provider without claiming a routing state", async () => {
      useStatus({
        enabled: true,
        configured: true,
        status: "unreachable",
        message: "Connection timed out",
        baseUrl: "https://opencode.ai/zen/go/v1",
        modelCount: null,
        lastCheckedAt: null,
      });
      renderSettings(ENABLED_SETTINGS);

      expect(await screen.findByText("Connection timed out")).toBeInTheDocument();
    });

    it("says routing state is unknown when the status endpoint itself fails", async () => {
      useStatus(null, 500);
      renderSettings(ENABLED_SETTINGS);

      expect(await screen.findByText(/Routing state is unknown/i)).toBeInTheDocument();
    });

    it("does not imply traffic flows while healthy but disabled", async () => {
      renderSettings(CONFIGURED_SETTINGS);

      expect(await screen.findByText(/the integration is still disabled/i)).toBeInTheDocument();
    });
  });

  describe("discovered models", () => {
    it("shows the supported count alongside the discovered total", async () => {
      renderSettings(ENABLED_SETTINGS);

      // Six advertised, three of which the backend marks supported.
      expect(
        await screen.findByRole("button", { name: /Discovered models \(6\).*3 supported/ }),
      ).toBeInTheDocument();
    });

    it("labels each model with the protocol the backend advertises", async () => {
      const user = userEvent.setup();
      renderSettings(ENABLED_SETTINGS);

      await openDiscoveredModels(user);

      const row = (await screen.findByText("qwen3.8-max")).closest("li");
      expect(row).not.toBeNull();
      expect(within(row as HTMLElement).getByText("Messages")).toBeInTheDocument();
    });

    it("refuses to offer a model whose protocol is unknown", async () => {
      const user = userEvent.setup();
      renderSettings(ENABLED_SETTINGS);

      await openDiscoveredModels(user);

      const row = (await screen.findByText("some-unlisted-preview")).closest("li");
      expect(within(row as HTMLElement).getByText("Protocol unknown")).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: "Unavailable some-unlisted-preview" }),
      ).toBeDisabled();
    });

    it("refuses to offer a known protocol the backend does not dispatch", async () => {
      const user = userEvent.setup();
      renderSettings(ENABLED_SETTINGS);

      await openDiscoveredModels(user);

      expect(await screen.findByText(/Messages routing not supported yet/)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Unavailable qwen3.8-max" })).toBeDisabled();
    });

    it("adds a supported model as a full model and persists it", async () => {
      const user = userEvent.setup();
      const { onSave } = renderSettings(ENABLED_SETTINGS);

      await openDiscoveredModels(user);
      await user.click(await screen.findByRole("button", { name: "Add full model kimi-k3" }));

      expect(
        within(
          screen.getByLabelText("Configured full models for OpenCode Go Integration"),
        ).getByText("kimi-k3"),
      ).toBeInTheDocument();
      await waitFor(() =>
        expect(onSave).toHaveBeenLastCalledWith(
          expect.objectContaining({ opencodeGoSidecarFullModels: ["kimi-k3"] }),
        ),
      );
    });

    it("keeps a privacy-sensitive /responses model unavailable at this milestone", async () => {
      const user = userEvent.setup();
      renderSettings(ENABLED_SETTINGS);

      await openDiscoveredModels(user);

      // muse-spark-1.3-contributor trains on prompts and is not ZDR. It is
      // /responses-only, so the backend marks it unsupported and it cannot be
      // selected here at all.
      expect(
        await screen.findByRole("button", { name: "Unavailable muse-spark-1.3-contributor" }),
      ).toBeDisabled();
      expect(
        within(
          screen.getByLabelText("Configured full models for OpenCode Go Integration"),
        ).queryByText("muse-spark-1.3-contributor"),
      ).not.toBeInTheDocument();
    });

    it("explains an empty catalog differently before a key is stored", async () => {
      const user = userEvent.setup();
      server.use(
        http.get("*/api/opencode-go-sidecar/models", () => HttpResponse.json({ models: [] })),
      );
      renderSettings(UNCONFIGURED_SETTINGS);

      await openDiscoveredModels(user);

      expect(await screen.findByText(/add an API key to discover models/i)).toBeInTheDocument();
    });

    it("distinguishes a configured-but-empty catalog from a missing key", async () => {
      const user = userEvent.setup();
      server.use(
        http.get("*/api/opencode-go-sidecar/models", () => HttpResponse.json({ models: [] })),
      );
      renderSettings(ENABLED_SETTINGS);

      await openDiscoveredModels(user);

      expect(await screen.findByText("No models returned by OpenCode Go.")).toBeInTheDocument();
    });
  });

  describe("routing controls", () => {
    it("renders the server's prefixes without inventing one on upgrade", () => {
      // The server seeds `opencode-go/` on fresh install only, so an upgraded
      // deployment sends an empty list and the UI must not fabricate an entry.
      renderSettings(CONFIGURED_SETTINGS);

      expect(screen.getByText("No prefixes configured.")).toBeInTheDocument();
      expect(
        screen.queryByRole("checkbox", { name: /Remove prefix .* before forwarding/ }),
      ).not.toBeInTheDocument();
    });

    it("renders a server-seeded prefix with its strip flag", () => {
      renderSettings(
        createDashboardSettings({
          opencodeGoSidecarApiKeyConfigured: true,
          opencodeGoSidecarModelPrefixes: [{ prefix: "opencode-go/", strip: true }],
        }),
      );

      expect(
        screen.getByText("opencode-go/", { selector: "span.font-mono" }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("checkbox", { name: "Remove prefix opencode-go/ before forwarding" }),
      ).toBeChecked();
    });

    it("persists prefix edits immediately", async () => {
      const user = userEvent.setup();
      const { onSave } = renderSettings(CONFIGURED_SETTINGS);

      await user.type(
        screen.getByLabelText("New prefix for OpenCode Go Integration"),
        "opencode-go/",
      );
      await user.click(screen.getByRole("button", { name: "Add prefix" }));

      await waitFor(() =>
        expect(onSave).toHaveBeenLastCalledWith(
          expect.objectContaining({
            opencodeGoSidecarModelPrefixes: [{ prefix: "opencode-go/", strip: false }],
          }),
        ),
      );
    });

    it("tells the operator the hyphen spelling is the one that routes", () => {
      renderSettings(CONFIGURED_SETTINGS);

      // Backend contract: prefix_variants' -/_ interchange applies only when the
      // separator is the final character, so `opencode_go/` does not resolve.
      expect(screen.getByText(/does not route/)).toBeInTheDocument();
    });

    it("rejects a prefix another integration already owns", async () => {
      const user = userEvent.setup();
      const { onSave } = renderSettings(
        createDashboardSettings({
          opencodeGoSidecarApiKeyConfigured: true,
          orcarouterSidecarModelPrefixes: [{ prefix: "shared/", strip: false }],
        }),
      );

      await user.type(
        screen.getByLabelText("New prefix for OpenCode Go Integration"),
        "shared/",
      );
      await user.click(screen.getByRole("button", { name: "Add prefix" }));

      expect(screen.getByText("Prefix shared/ is already used by OrcaRouter.")).toBeInTheDocument();
      expect(onSave).not.toHaveBeenCalled();
    });

    it("blocks a save while a required field is empty", async () => {
      const user = userEvent.setup();
      const { onSave } = renderSettings(CONFIGURED_SETTINGS);

      await user.clear(screen.getByLabelText("Base URL"));
      await user.tab();

      expect(onSave).not.toHaveBeenCalled();
    });
  });

  describe("provider-side balance setting", () => {
    it("describes Use balance without offering a control codex-lb cannot honour", () => {
      renderSettings(CONFIGURED_SETTINGS);

      expect(screen.getByText(/Use balance/)).toBeInTheDocument();
      expect(screen.getByText(/this page cannot read it or change it/i)).toBeInTheDocument();
      expect(screen.queryByRole("switch", { name: /balance/i })).not.toBeInTheDocument();
      expect(screen.queryByRole("checkbox", { name: /balance/i })).not.toBeInTheDocument();
    });
  });

  describe("server errors", () => {
    it("surfaces a save failure inline", async () => {
      const user = userEvent.setup();
      const onSave = vi.fn().mockRejectedValue(new Error("Settings were modified since load"));
      renderSettings(CONFIGURED_SETTINGS, onSave);

      await user.type(
        screen.getByLabelText("New prefix for OpenCode Go Integration"),
        "ocgo/",
      );
      await user.click(screen.getByRole("button", { name: "Add prefix" }));

      expect(await screen.findByText("Settings were modified since load")).toBeInTheDocument();
    });

    it("surfaces a key-removal failure instead of implying success", async () => {
      const user = userEvent.setup();
      const onSave = vi.fn().mockRejectedValue(new Error("Key removal rejected"));
      renderSettings(CONFIGURED_SETTINGS, onSave);

      await user.click(screen.getByRole("button", { name: "Remove stored key" }));
      await user.click(screen.getByRole("button", { name: "Remove key" }));

      expect(await screen.findByText("Key removal rejected")).toBeInTheDocument();
    });
  });
});
