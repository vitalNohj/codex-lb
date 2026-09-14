import { expect, test } from "@playwright/test";
import { readFile } from "node:fs/promises";

import { authSession, settings, upstreamProxyAdmin } from "./fixtures";

/**
 * End-user path for the Accounts card's "Configure" link.
 *
 * The Accounts page links to `/settings#opencode-go-sidecar`. The integration
 * lives inside a tab, and inactive tab panels are unmounted, so arriving by
 * that link must still select the OpenCode Go tab and reveal its controls.
 *
 * Everything is mocked and local: a static build on its own port, no backend,
 * no credential, no outbound request.
 */

const OPENCODE_GO_MODELS = [
  { id: "glm-5.3", created: 1789353162, ownedBy: "opencode", protocol: "chat_completions", supported: true },
  { id: "qwen3.8-max", created: 1789353165, ownedBy: "opencode", protocol: "messages", supported: false },
  { id: "some-unlisted-preview", created: 1789353167, ownedBy: "opencode", protocol: "unknown", supported: false },
];

const GO_SETTINGS = {
  ...settings,
  // Another integration is enabled as well, so arriving at the Go anchor must
  // work because of the hash - not because Go happens to be the only enabled
  // integration and the "first enabled" default already picked it.
  orcarouterSidecarEnabled: true,
  orcarouterSidecarApiKeyConfigured: true,
  opencodeGoSidecarEnabled: true,
  opencodeGoSidecarApiKeyConfigured: true,
  opencodeGoSidecarBaseUrl: "https://opencode.ai/zen/go/v1",
  opencodeGoSidecarModelPrefixes: [{ prefix: "opencode-go/", strip: true }],
  opencodeGoSidecarFullModels: [],
  opencodeGoSidecarConnectTimeoutSeconds: 8,
  opencodeGoSidecarRequestTimeoutSeconds: 600,
  opencodeGoSidecarModelsCacheTtlSeconds: 60,
  opencodeGoSidecarLastHealthStatus: "healthy",
  opencodeGoSidecarLastHealthMessage: "OpenCode Go reachable",
  opencodeGoSidecarLastCheckedAt: "2026-09-14T00:00:00Z",
  opencodeGoSidecarLastModelCount: OPENCODE_GO_MODELS.length,
};

const goStatus = {
  enabled: true,
  configured: true,
  status: "healthy",
  message: "OpenCode Go reachable",
  baseUrl: "https://opencode.ai/zen/go/v1",
  modelCount: OPENCODE_GO_MODELS.length,
  lastCheckedAt: "2026-09-14T00:00:00Z",
};

const emptySidecar = (baseUrl: string) => ({
  enabled: false,
  configured: false,
  status: "disabled",
  message: null,
  baseUrl,
  modelCount: 0,
  lastCheckedAt: null,
});

async function mockApi(page: import("@playwright/test").Page) {
  await page.route("**/api/**", async (route) => {
    const p = new URL(route.request().url()).pathname.replace(/^\/codex/, "");
    let body: unknown = {};
    if (p === "/api/dashboard-auth/session") body = authSession;
    else if (p === "/api/settings") body = GO_SETTINGS;
    else if (p === "/api/settings/upstream-proxy") body = upstreamProxyAdmin;
    else if (p === "/api/settings/telemetry") body = { consent: "undecided", instanceId: null, lastSentAt: null, preview: null };
    else if (p === "/api/opencode-go-sidecar/status") body = goStatus;
    else if (p === "/api/opencode-go-sidecar/models") body = { models: OPENCODE_GO_MODELS };
    else if (p === "/api/opencode-go-sidecar/test") body = { ...goStatus, models: OPENCODE_GO_MODELS };
    else if (p === "/api/claude-sidecar/status") body = emptySidecar("http://127.0.0.1:8317");
    else if (p === "/api/openrouter-sidecar/status") body = emptySidecar("https://openrouter.ai/api/v1");
    else if (p === "/api/orcarouter-sidecar/status") body = emptySidecar("https://api.orcarouter.ai/v1");
    else if (p === "/api/ollama-sidecar/status") body = emptySidecar("https://ollama.com");
    else if (p.endsWith("/models")) body = { models: [] };
    else if (p === "/api/claude-sidecar/routing") body = { status: "healthy", message: null, strategy: "fill_first", accounts: [] };
    else if (p === "/api/accounts") body = { accounts: [] };
    else if (p === "/api/api-keys" || p === "/api/api-keys/") body = { apiKeys: [] };
    await route.fulfill({ json: body });
  });
  await page.route("http://localhost:4174/codex/settings", async (route) =>
    route.fulfill({
      contentType: "text/html",
      body: await readFile(new URL("../.opencode-go-build/codex/index.html", import.meta.url), "utf8"),
    }),
  );
}

test("the Accounts Configure deep link opens the OpenCode Go controls", async ({ page }) => {
  const evidence = process.env.OPENCODE_GO_EVIDENCE_DIR;
  await mockApi(page);

  // Exactly what the Accounts card's Configure button navigates to.
  await page.goto("http://localhost:4174/codex/settings#opencode-go-sidecar");

  // The tab must be selected, not merely present, and its controls mounted.
  await expect(page.getByRole("tab", { name: /OpenCode Go/ })).toHaveAttribute(
    "data-state",
    "active",
  );
  const enableToggle = page.getByRole("switch", { name: "Enable OpenCode Go Integration" });
  await expect(enableToggle).toBeVisible();
  await expect(page.locator("#opencode-go-sidecar")).toBeVisible();

  // The anchor target is scrolled into view rather than left off-screen.
  const inViewport = await page.locator("#opencode-go-sidecar").evaluate((element) => {
    const rect = element.getBoundingClientRect();
    return rect.top < window.innerHeight && rect.bottom > 0;
  });
  expect(inViewport).toBe(true);

  if (evidence) {
    await page.screenshot({ path: `${evidence}/08-deeplink-opencode-go.png` });
  }
});

test("a deep link to another integration still selects that integration", async ({ page }) => {
  await mockApi(page);

  // Regression guard: the Go deep link must not hijack the other anchors.
  await page.goto("http://localhost:4174/codex/settings#orcarouter-sidecar");

  await expect(page.getByRole("tab", { name: /OrcaRouter/ })).toHaveAttribute(
    "data-state",
    "active",
  );
  await expect(
    page.getByRole("switch", { name: "Enable OrcaRouter Integration" }),
  ).toBeVisible();
});

test("without a hash the default tab selection is unchanged", async ({ page }) => {
  await mockApi(page);

  await page.goto("http://localhost:4174/codex/settings");

  // No hash: the pre-existing "first enabled integration" rule still applies,
  // and OrcaRouter comes before OpenCode Go in the tab order.
  await expect(page.getByRole("tab", { name: /OrcaRouter/ })).toHaveAttribute(
    "data-state",
    "active",
  );
});

test("a retained catalogue stops being selectable once the integration is disabled", async ({ page }) => {
  const evidence = process.env.OPENCODE_GO_EVIDENCE_DIR;
  // Same page/session: discover successfully, then flip the integration off and
  // re-render from the retained React Query data, as a real operator would.
  let enabled = true;
  await page.route("**/api/**", async (route) => {
    const p = new URL(route.request().url()).pathname.replace(/^\/codex/, "");
    let body: unknown = {};
    if (p === "/api/dashboard-auth/session") body = authSession;
    else if (p === "/api/settings") body = { ...GO_SETTINGS, opencodeGoSidecarEnabled: enabled };
    else if (p === "/api/settings/upstream-proxy") body = upstreamProxyAdmin;
    else if (p === "/api/opencode-go-sidecar/status") body = goStatus;
    else if (p === "/api/opencode-go-sidecar/models") body = { models: OPENCODE_GO_MODELS };
    else if (p.endsWith("/status")) body = emptySidecar("https://example.invalid");
    else if (p.endsWith("/models")) body = { models: [] };
    else if (p === "/api/accounts") body = { accounts: [] };
    else if (p === "/api/api-keys" || p === "/api/api-keys/") body = { apiKeys: [] };
    await route.fulfill({ json: body });
  });
  await page.route("http://localhost:4174/codex/settings", async (route) =>
    route.fulfill({
      contentType: "text/html",
      body: await readFile(new URL("../.opencode-go-build/codex/index.html", import.meta.url), "utf8"),
    }),
  );

  await page.goto("http://localhost:4174/codex/settings#opencode-go-sidecar");
  await page.getByRole("button", { name: /Discovered models/ }).click();
  await expect(page.getByRole("button", { name: "Add full model glm-5.3" })).toBeEnabled();

  // Operator switches the integration off.
  enabled = false;
  await page.getByRole("switch", { name: "Enable OpenCode Go Integration" }).click();

  const unavailable = page.getByRole("button", { name: "Unavailable glm-5.3" });
  await expect(unavailable).toBeVisible();
  await expect(unavailable).toBeDisabled();
  await expect(page.getByRole("button", { name: "Add full model glm-5.3" })).toHaveCount(0);
  // The header names the reason, so the state is not silent.
  await expect(page.getByRole("button", { name: /Discovered models.*Integration disabled/ })).toBeVisible();
  if (evidence) {
    await unavailable.scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${evidence}/09-retained-rows-disabled.png` });
  }
});
