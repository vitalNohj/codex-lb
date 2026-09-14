/**
 * Browser user path against the ACTUAL codex-lb backend.
 *
 * Distinct from `opencode-go-review.mjs`, which serves JSON fixtures from the
 * preview server. That harness proves rendering; it cannot prove that the
 * dashboard talks to the real settings and quota routes, because no backend is
 * involved. This one drives a real uvicorn-hosted codex-lb with an isolated
 * SQLite database and a synthetic loopback Go upstream.
 *
 * Flow, in one browser session:
 *   1. Settings -> enable OpenCode Go, save a write-only API key.
 *   2. Confirm the key is reported configured and never echoed back.
 *   3. Accounts -> the Go card renders from the REAL mounted quota route,
 *      served from the synthetic upstream.
 *   4. Force the quota endpoint to 500, reload -> cached values retained and
 *      marked stale (a real refetch failure, not a remount with no prior fetch).
 *   5. Force 404 -> known-good values still retained, endpoint-unavailable
 *      labelling rather than deletion.
 *   6. Restore -> the card reconnects and drops the stale marker.
 *   7. Settings anchor `/settings#opencode-go-sidecar` -> the Go section is
 *      reached and expanded.
 *
 * Usage: node browser-smoke/opencode-go-real-backend-flow.mjs <baseUrl> <outDir>
 *
 * No real credential is used anywhere: the API key written here is a synthetic
 * literal and the upstream is a local fake.
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { chromium } from "@playwright/test";

const baseUrl = process.argv[2];
const outDir = process.argv[3];
if (!baseUrl || !outDir) {
  throw new Error("usage: opencode-go-real-backend-flow.mjs <baseUrl> <outDir>");
}
mkdirSync(outDir, { recursive: true });

const SYNTHETIC_KEY = "sk-go-browser-Zq7SvT2pLm9KdR4xHn8B";
const findings = [];
const ok = (name, detail) => findings.push({ level: "ok", name, detail });
const fail = (name, detail) => findings.push({ level: "fail", name, detail });

async function shot(page, name) {
  await page.screenshot({ path: join(outDir, `${name}.png`), fullPage: true });
}

const browser = await chromium.launch();
// Throwaway context: no existing profile, no stored credential.
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();

const consoleErrors = [];
page.on("console", (message) => {
  if (message.type() === "error") consoleErrors.push(message.text());
});

/** Route override for the quota endpoint, so a real failure can be forced. */
let quotaOverride = null;
await page.route("**/api/opencode-go/quota", async (route) => {
  if (quotaOverride === null) return route.continue();
  await route.fulfill({
    status: quotaOverride,
    contentType: "application/json",
    body: JSON.stringify({ error: { code: "forced", message: `forced ${quotaOverride}` } }),
  });
});

try {
  // -- 1/2. Settings: enable, save a write-only key ------------------------
  await page.goto(`${baseUrl}/settings#opencode-go-sidecar`, { waitUntil: "networkidle" });
  const anchored = await page.locator("text=/OpenCode Go/i").first().isVisible();
  anchored
    ? ok("settings-anchor", "deep link reached the OpenCode Go section")
    : fail("settings-anchor", "the Go section was not visible after the deep link");
  await shot(page, "01-settings-anchor");

  // Write the settings through the real API from inside the page, so the
  // browser session and the backend agree on state.
  const saved = await page.evaluate(async (key) => {
    const response = await fetch("/api/settings", {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        opencodeGoSidecarEnabled: true,
        opencodeGoSidecarBaseUrl: "https://opencode.ai/zen/go/v1",
        opencodeGoSidecarApiKey: key,
      }),
    });
    return { status: response.status, body: await response.text() };
  }, SYNTHETIC_KEY);

  saved.status === 200
    ? ok("settings-save", "enabled Go and stored a key through the real settings API")
    : fail("settings-save", `PUT /api/settings returned ${saved.status}: ${saved.body.slice(0, 200)}`);
  saved.body.includes(SYNTHETIC_KEY)
    ? fail("key-write-only", "the settings response echoed the API key back")
    : ok("key-write-only", "the stored key was never echoed in the response");

  const settingsAfter = await page.evaluate(async () => {
    const response = await fetch("/api/settings");
    return await response.text();
  });
  settingsAfter.includes(SYNTHETIC_KEY)
    ? fail("key-never-returned", "GET /api/settings returned the stored key")
    : ok("key-never-returned", "GET /api/settings reports configured-ness only");

  // -- 3. Accounts card from the REAL quota route --------------------------
  await page.goto(`${baseUrl}/accounts`, { waitUntil: "networkidle" });
  await page.waitForTimeout(1200);
  const cardVisible = await page.locator("text=/OpenCode Go/i").first().isVisible();
  cardVisible
    ? ok("accounts-card", "the Go card rendered against the real backend")
    : fail("accounts-card", "no OpenCode Go card appeared on Accounts");
  await shot(page, "02-accounts-live");

  const liveText = await page.locator("body").innerText();
  liveText.includes(SYNTHETIC_KEY)
    ? fail("card-no-key", "the Accounts page rendered the API key")
    : ok("card-no-key", "no credential appears in the rendered card");

  // -- 4. Forced 500 after a successful read -> stale retention ------------
  quotaOverride = 500;
  await page.reload({ waitUntil: "networkidle" });
  await page.waitForTimeout(1500);
  const afterFailure = await page.locator("body").innerText();
  const retained = /\d+%/.test(afterFailure);
  const staleMarked = /stale/i.test(afterFailure);
  retained && staleMarked
    ? ok("cached-retention-500", "values retained and marked stale after a real 500")
    : fail(
        "cached-retention-500",
        `retained=${retained} staleMarked=${staleMarked} after a forced 500`,
      );
  await shot(page, "03-accounts-500-stale");

  // -- 5. Forced 404 -> retention, not deletion ---------------------------
  quotaOverride = 404;
  await page.reload({ waitUntil: "networkidle" });
  await page.waitForTimeout(1500);
  const after404 = await page.locator("body").innerText();
  const stillVisible = await page.locator("text=/OpenCode Go/i").first().isVisible();
  const zeroed = /\b0%/.test(after404) && !/\d{1,3}%/.test(after404.replace(/\b0%/g, ""));
  stillVisible && !zeroed
    ? ok("cached-retention-404", "a 404 did not delete known-good values or fabricate zeros")
    : fail("cached-retention-404", `visible=${stillVisible} zeroed=${zeroed} after a forced 404`);
  await shot(page, "04-accounts-404-retained");

  // -- 6. Reconnect -------------------------------------------------------
  quotaOverride = null;
  await page.reload({ waitUntil: "networkidle" });
  await page.waitForTimeout(1500);
  const reconnected = await page.locator("body").innerText();
  /stale/i.test(reconnected)
    ? fail("reconnect", "the stale marker survived a successful refetch")
    : ok("reconnect", "the card reconnected and dropped the stale marker");
  await shot(page, "05-accounts-reconnected");

  // -- 7. Console hygiene -------------------------------------------------
  consoleErrors.length === 0
    ? ok("console", "no console errors across the flow")
    : fail("console", `console errors: ${consoleErrors.slice(0, 3).join(" | ")}`);
} finally {
  await context.close();
  await browser.close();
}

const failures = findings.filter((entry) => entry.level === "fail");
const lines = [
  "# OpenCode Go - browser flow against the REAL backend",
  "",
  `Chromium via Playwright, throwaway context, live codex-lb at ${baseUrl}.`,
  "Isolated database, synthetic loopback Go upstream, synthetic API key.",
  "",
  `**${failures.length} failures, ${findings.length - failures.length} ok.**`,
  "",
  ...findings.map((entry) => `- \`${entry.level}\` **${entry.name}**: ${entry.detail}`),
];
writeFileSync(join(outDir, "real-backend-flow.md"), `${lines.join("\n")}\n`);
console.log(lines.join("\n"));
if (failures.length > 0) process.exitCode = 1;
