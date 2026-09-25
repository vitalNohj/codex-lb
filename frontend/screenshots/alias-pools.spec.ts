import { readFile } from "node:fs/promises";
import { expect, test, type Page } from "@playwright/test";

import { authSession, models, settings, upstreamProxyAdmin } from "./fixtures";

/**
 * Captures the Routing settings alias section for the PR body (PRINCIPLES P5).
 *
 * The API is fully mocked: one pooled alias with two targets, one of which is
 * cooling after a 402, plus one ordinary single-target alias so both row
 * shapes appear in the same frame.
 */

const ALIAS = "pooled/glm-5.3";
const ORCA = "orcarouter/z-ai/glm-5.3";
const OPENROUTER = "or/z-ai/glm-5.3";

const POOL_SETTINGS = {
  ...settings,
  orcarouterSidecarEnabled: true,
  openrouterSidecarEnabled: true,
  modelAliases: {
    [ALIAS]: { targets: [ORCA, OPENROUTER] },
    "fast-code": { targets: ["gpt-5.4-mini"] },
  },
  customAliasCatalog: {},
};

const HEALTH = {
  aliases: {
    [ALIAS]: {
      [ORCA]: {
        state: "cooling",
        until: new Date(Date.now() + 25 * 60_000).toISOString(),
        lastStatus: 402,
        lastError: "Insufficient credits",
      },
      [OPENROUTER]: { state: "healthy", until: null, lastStatus: null, lastError: null },
    },
    "fast-code": {
      "gpt-5.4-mini": { state: "healthy", until: null, lastStatus: null, lastError: null },
    },
  },
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

async function mockApi(page: Page) {
  await page.route("**/api/**", async (route) => {
    const p = new URL(route.request().url()).pathname.replace(/^\/codex/, "");
    let body: unknown = {};
    if (p === "/api/dashboard-auth/session") body = authSession;
    else if (p === "/api/settings") body = POOL_SETTINGS;
    else if (p === "/api/settings/alias-pools/health") body = HEALTH;
    else if (p === "/api/settings/upstream-proxy") body = upstreamProxyAdmin;
    else if (p === "/api/settings/telemetry")
      body = { consent: "undecided", instanceId: null, lastSentAt: null, preview: null };
    else if (p === "/api/models") body = { models };
    else if (p === "/api/claude-sidecar/routing")
      body = { status: "healthy", message: null, strategy: "fill_first", accounts: [] };
    else if (p.endsWith("-sidecar/status")) body = emptySidecar("https://example.invalid/v1");
    else if (p.endsWith("/models")) body = { models: [] };
    else if (p === "/api/accounts") body = { accounts: [] };
    else if (p === "/api/api-keys" || p === "/api/api-keys/") body = { apiKeys: [] };
    await route.fulfill({ json: body });
  });
  // The SPA route (with or without a query string) is served from index.html.
  await page.route("http://localhost:4175/codex/settings**", async (route) =>
    route.fulfill({
      contentType: "text/html",
      body: await readFile(new URL("../.alias-pools-build/codex/index.html", import.meta.url), "utf8"),
    }),
  );
}

test("routing alias pools render targets with health", async ({ page }) => {
  const evidence = process.env.ALIAS_POOLS_EVIDENCE_DIR;
  await mockApi(page);
  await page.emulateMedia({ reducedMotion: "reduce" });

  await page.goto("http://localhost:4175/codex/settings?advanced=1#model-aliases");

  const section = page.locator("#model-aliases");
  await expect(section).toBeVisible();
  const row = page.getByTestId(`alias-row-${ALIAS}`);
  await expect(row.getByText(/cooling until .* \(last: 402\)/)).toBeVisible();
  await expect(row.getByRole("button", { name: `Move ${OPENROUTER} up` })).toBeEnabled();
  await expect(page.getByTestId("alias-row-fast-code").getByRole("button", { name: "Remove target gpt-5.4-mini" })).toBeDisabled();

  // Element screenshots scroll the target to the top edge, under the sticky
  // header; nudge it down so the section title is not covered.
  await section.evaluate((element) => {
    element.scrollIntoView({ block: "start" });
    window.scrollBy(0, -96);
  });
  if (evidence) {
    await section.screenshot({ path: `${evidence}/routing-alias-pools-after.png` });
  }
});
