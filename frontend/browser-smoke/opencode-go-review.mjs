/**
 * Live browser review of the OpenCode Go Accounts card.
 *
 * Drives a real Chromium against the isolated fixture preview server, in a
 * throwaway browser context (no existing profile, no stored credential), and
 * writes screenshots plus a machine-checked findings report.
 *
 * This is a review harness, not a test-suite assertion. It fails loudly on
 * things that would be dishonest or broken in the UI (an "in in" duplication, a
 * bar drawn for an unknown value, a horizontal overflow, a console error), so a
 * picky pass is reproducible rather than a matter of my own eyeballing.
 *
 * Usage: node browser-smoke/opencode-go-review.mjs <baseUrl> <outDir>
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { chromium } from "@playwright/test";

const baseUrl = process.argv[2] ?? "http://127.0.0.1:4599";
const outDir = process.argv[3] ?? "/tmp/go-review";
mkdirSync(outDir, { recursive: true });

const VIEWPORTS = [
  { name: "wide", width: 1440, height: 1000 },
  { name: "narrow", width: 390, height: 900 },
];

const SCENARIOS = [
  "default",
  "partial",
  "exhausted",
  "stale",
  "per_model",
  "disabled",
  "not_configured",
  "unauthorized",
  "rate_limited",
  "unavailable",
  "malformed",
  "absent",
  "loading",
];

const findings = [];
const record = (scenario, viewport, level, note) =>
  findings.push({ scenario, viewport, level, note });

const CARD = "[data-testid=opencode-go-quota-card]";

async function reviewScenario(page, scenario, viewport) {
  const tag = `${scenario}-${viewport.name}`;
  const consoleErrors = [];
  const onConsole = (m) => {
    if (m.type() === "error") consoleErrors.push(m.text());
  };
  const onPageError = (e) => consoleErrors.push(`pageerror: ${e.message}`);
  page.on("console", onConsole);
  page.on("pageerror", onPageError);

  await page.setViewportSize({ width: viewport.width, height: viewport.height });
  await page.goto(`${baseUrl}/codex/accounts?scenario=${scenario}`, {
    waitUntil: "domcontentloaded",
  });

  if (scenario === "loading") {
    await page.waitForSelector("[data-testid=opencode-go-quota-loading]", { timeout: 15_000 });
  } else if (scenario === "absent") {
    await page.waitForSelector("[data-testid=accounts-list-card]", { timeout: 15_000 });
    // The query retries once before settling, so the card is briefly in its
    // loading state. Wait for it to actually disappear rather than sampling too
    // early and mistaking "still loading" for "wrongly rendered".
    await page.waitForSelector(CARD, { state: "detached", timeout: 15_000 }).catch(() => {});
  } else {
    await page.waitForSelector(CARD, { timeout: 15_000 });
    await page.waitForTimeout(350);
  }

  const card = page.locator(CARD);
  const present = (await card.count()) > 0;

  if (scenario === "absent") {
    if (present) record(scenario, viewport.name, "FAIL", "card rendered despite a 404 quota route");
    else record(scenario, viewport.name, "ok", "no card rendered, Accounts page otherwise intact");
  } else if (!present) {
    record(scenario, viewport.name, "FAIL", "card missing");
  }

  if (present) {
    const text = (await card.innerText()).replace(/\s+/g, " ");

    // Honesty checks.
    if (/\bin in\b/.test(text)) record(scenario, viewport.name, "FAIL", `duplicated preposition: ${text.match(/.{0,30}in in.{0,20}/)}`);
    if (/NaN|undefined|null%/.test(text)) record(scenario, viewport.name, "FAIL", "placeholder leaked into copy");
    if (/account total/i.test(text)) record(scenario, viewport.name, "FAIL", "claims an account total");
    // A remaining *percentage* is the forbidden claim. Prose that merely uses the
    // word ("says nothing about your remaining model quota") is the opposite of a
    // claim, so match a number rather than the bare word.
    if (/\d\s*%\s*remaining|remaining[^.]{0,20}\d\s*%/i.test(text)) {
      record(scenario, viewport.name, "FAIL", "prints a remaining percentage");
    }

    // An unknown value must have no fill and no progress element.
    const unknownTracks = await card.locator("[data-testid=opencode-go-window-unknown-track]").count();
    const fills = await card.locator("[data-testid=opencode-go-window-fill]").count();
    const windows = await card.locator("[data-testid=opencode-go-window]").count();
    if (unknownTracks + fills !== windows) {
      record(scenario, viewport.name, "FAIL", `window/indicator mismatch: ${windows} windows, ${fills} fills, ${unknownTracks} unknown tracks`);
    }
    if (unknownTracks > 0 && /\b0%\b|\b100%\b/.test(text) && scenario === "partial") {
      record(scenario, viewport.name, "FAIL", "unknown window rendered as 0% or 100%");
    }

    // Every fill must be within 0-100% width and match its stated percent.
    const fillWidths = await card.locator("[data-testid=opencode-go-window-fill]").evaluateAll(
      (nodes) => nodes.map((n) => n.style.width),
    );
    for (const w of fillWidths) {
      const pct = Number.parseFloat(w);
      if (!Number.isFinite(pct) || pct < 0 || pct > 100) {
        record(scenario, viewport.name, "FAIL", `bar width out of range: ${w}`);
      }
    }

    // Accessible progress semantics for known values only.
    const progressCount = await card.locator("progress").count();
    if (progressCount !== fills) {
      record(scenario, viewport.name, "FAIL", `progress elements (${progressCount}) != fills (${fills})`);
    }

    // Layout: the card must not overflow its column, and nothing inside it may
    // overflow the card - this is what catches a long model id stretching a grid.
    const overflow = await card.evaluate((el) => {
      const cardRect = el.getBoundingClientRect();
      const bad = [];
      for (const node of el.querySelectorAll("*")) {
        const r = node.getBoundingClientRect();
        if (r.width === 0 && r.height === 0) continue;
        if (r.right > cardRect.right + 1.5 || r.left < cardRect.left - 1.5) {
          bad.push(`${node.tagName}.${String(node.className).slice(0, 40)} right=${r.right.toFixed(1)} cardRight=${cardRect.right.toFixed(1)}`);
        }
      }
      return {
        docOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
        cardScrollOverflow: el.scrollWidth > el.clientWidth + 1,
        bad: bad.slice(0, 4),
      };
    });
    if (overflow.docOverflow) record(scenario, viewport.name, "FAIL", "page scrolls horizontally");
    if (overflow.cardScrollOverflow) record(scenario, viewport.name, "FAIL", "card content overflows the card");
    for (const b of overflow.bad) record(scenario, viewport.name, "FAIL", `child escapes card bounds: ${b}`);

    // Tap-target sanity for the settings link on narrow screens.
    const link = card.getByRole("link").first();
    if ((await link.count()) > 0) {
      const box = await link.boundingBox();
      if (box && box.height < 24) {
        record(scenario, viewport.name, "WARN", `settings link only ${box.height.toFixed(0)}px tall`);
      }
    }
  }

  // Keyboard review of the model picker, wide viewport only.
  if (scenario === "per_model" && viewport.name === "wide") {
    const trigger = card.getByRole("combobox");
    await trigger.focus();
    const focused = await page.evaluate(() => document.activeElement?.getAttribute("role"));
    if (focused !== "combobox") record(scenario, viewport.name, "FAIL", `focus went to ${focused}`);
    await page.keyboard.press("Enter");
    await page.waitForSelector("[role=listbox]", { timeout: 5_000 });
    // Let the open animation finish so the evidence screenshot is not a
    // half-faded frame that looks like overlapping text.
    await page.waitForTimeout(400);
    await page.screenshot({ path: join(outDir, `${tag}-picker-open.png`) });
    const optionCount = await page.locator("[role=option]").count();
    if (optionCount !== 4) record(scenario, viewport.name, "FAIL", `expected 4 options (all + 3 models), got ${optionCount}`);
    // Option labels must not overflow the popover.
    const optOverflow = await page.locator("[role=listbox]").evaluate((el) => el.scrollWidth > el.clientWidth + 1);
    if (optOverflow) record(scenario, viewport.name, "FAIL", "listbox overflows horizontally");
    // A long model id must ellipsize, not be hard-clipped at the popover edge
    // with no visual cue that the text was cut.
    const clipped = await page.locator("[role=option]").evaluateAll((nodes) =>
      nodes
        .flatMap((n) => [...n.querySelectorAll("span")])
        .filter((s) => s.scrollWidth > s.clientWidth + 1)
        .filter((s) => getComputedStyle(s).textOverflow !== "ellipsis")
        .map((s) => s.textContent?.slice(0, 40)),
    );
    for (const c of clipped) {
      record(scenario, viewport.name, "FAIL", `option text clipped without ellipsis: ${c}`);
    }
    // Let the highlighted option settle, otherwise ArrowDown can land before
    // Radix has focused the first item.
    await page.waitForTimeout(250);
    await page.keyboard.press("ArrowDown");
    await page.waitForTimeout(120);
    await page.keyboard.press("Enter");
    await page.waitForSelector("[role=listbox]", { state: "detached", timeout: 5_000 }).catch(() => {});
    const rows = await card.locator("[data-testid=opencode-go-model-row]").count();
    if (rows !== 1) record(scenario, viewport.name, "FAIL", `filter left ${rows} rows, expected 1`);
    // Radix restores focus asynchronously after the popover unmounts, so poll
    // instead of sampling once.
    let refocused = null;
    for (let i = 0; i < 40; i += 1) {
      refocused = await page.evaluate(() => document.activeElement?.getAttribute("role"));
      if (refocused === "combobox") break;
      await page.waitForTimeout(50);
    }
    if (refocused !== "combobox") record(scenario, viewport.name, "FAIL", `focus not restored (${refocused})`);
    // Tab must continue into the page rather than stranding the user.
    await page.keyboard.press("Tab");
    if (await page.evaluate(() => document.activeElement === document.body)) {
      record(scenario, viewport.name, "FAIL", "Tab after selecting stranded focus on body");
    }
    await card.getByRole("combobox").focus();
    await page.screenshot({ path: join(outDir, `${tag}-picker-filtered.png`) });
    // Escape must close without changing the selection.
    await page.keyboard.press("Enter");
    await page.waitForSelector("[role=listbox]", { timeout: 5_000 });
    await page.keyboard.press("Escape");
    // Radix animates the popover out, so wait for removal instead of assuming a
    // fixed delay is long enough.
    const closed = await page
      .waitForSelector("[role=listbox]", { state: "detached", timeout: 5_000 })
      .then(() => true)
      .catch(() => false);
    if (!closed) {
      record(scenario, viewport.name, "FAIL", "Escape did not close the picker");
    }
    if ((await card.locator("[data-testid=opencode-go-model-row]").count()) !== 1) {
      record(scenario, viewport.name, "FAIL", "Escape changed the selection");
    }
  }

  const shotTarget = present ? card : page;
  await shotTarget.screenshot({ path: join(outDir, `${tag}.png`) }).catch(async () => {
    await page.screenshot({ path: join(outDir, `${tag}.png`) });
  });

  const realErrors = consoleErrors.filter((e) => {
    if (/favicon/i.test(e)) return false;
    // The absent scenario deliberately serves 404 for the quota route; the
    // browser always logs that, and handling it is the behaviour under review.
    if (scenario === "absent" && /404|Not Found/i.test(e)) return false;
    return true;
  });
  for (const e of realErrors) record(scenario, viewport.name, "FAIL", `console: ${e.slice(0, 160)}`);
  if (realErrors.length === 0 && present) record(scenario, viewport.name, "ok", "rendered clean");

  page.off("console", onConsole);
  page.off("pageerror", onPageError);
}

/**
 * Remount with the endpoint failing: the cached snapshot must stay on screen
 * rather than collapsing to an error notice.
 *
 * Note on scope. The app's query policy uses a 30s staleTime, so a remount this
 * soon after a success intentionally issues **no** request at all - which is why
 * no stale marker is expected here. What this check proves is the user-visible
 * half: leaving the page and coming back while the dashboard API is broken still
 * shows the real numbers, at their true measured time, with no error text
 * leaking in. The failed-refetch path itself (stale marker, refresh-failed copy,
 * freshness preserved, upstream not blamed) is asserted deterministically in the
 * component tests, where the refetch can be forced without waiting out staleTime.
 */
async function reviewCachedRetention(page) {
  const viewport = { name: "wide", width: 1440, height: 1000 };
  await page.setViewportSize({ width: viewport.width, height: viewport.height });
  await page.goto(`${baseUrl}/codex/accounts?scenario=default`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector(CARD, { timeout: 15_000 });
  const card = page.locator(CARD);
  await page.waitForSelector("[data-testid=opencode-go-window-value]", { timeout: 15_000 });
  const firstValue = await card.locator("[data-testid=opencode-go-window-value]").first().innerText();
  const firstFreshness = await card.locator("[data-testid=opencode-go-freshness]").innerText();

  // Break the endpoint, then remount the card via client-side navigation. This
  // keeps the app (and its query cache) alive, which is the real user path:
  // leave the page, come back, and the dashboard API is now failing.
  await page.route("**/api/opencode-go/quota*", (route) =>
    route.fulfill({
      status: 500,
      contentType: "application/json",
      body: JSON.stringify({ error: { code: "boom", message: "boom" } }),
    }),
  );
  await page.getByRole("link", { name: "Settings" }).first().click();
  await page.waitForTimeout(400);
  await page.getByRole("link", { name: "Accounts" }).first().click();
  await page.waitForSelector(CARD, { timeout: 15_000 });
  await page.waitForTimeout(1500);

  const after = await page.evaluate(() => {
    const c = document.querySelector("[data-testid=opencode-go-quota-card]");
    if (!c) return { present: false };
    return {
      present: true,
      value: c.querySelector("[data-testid=opencode-go-window-value]")?.textContent,
      freshness: c.querySelector("[data-testid=opencode-go-freshness]")?.textContent,
      stale: !!c.querySelector("[data-testid=opencode-go-stale-badge]"),
      notice: c.querySelector("[data-testid=opencode-go-quota-notice]")?.getAttribute("data-notice"),
      degraded: c.querySelector("[data-testid=opencode-go-degraded]")?.innerText,
      text: c.innerText,
    };
  });

  const s = "cached-retention";
  if (!after.present) {
    record(s, viewport.name, "FAIL", "card vanished instead of retaining cached values");
  } else if (after.notice) {
    record(s, viewport.name, "FAIL", `discarded cached values for notice "${after.notice}"`);
  } else {
    if (after.value !== firstValue) {
      record(s, viewport.name, "FAIL", `retained value changed: ${firstValue} -> ${after.value}`);
    }
    if (after.freshness !== firstFreshness) {
      record(s, viewport.name, "FAIL", `freshness drifted: ${firstFreshness} -> ${after.freshness}`);
    }
    if (/\bboom\b/.test(after.text)) {
      record(s, viewport.name, "FAIL", "our own request error attributed to OpenCode");
    }
    record(
      s,
      viewport.name,
      "ok",
      `retained cached values across remount with a failing endpoint, freshness preserved${after.stale ? ", marked stale" : ""}`,
    );
  }
  await (after.present ? card : page).screenshot({ path: join(outDir, `${s}.png`) });
}

const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader"] });
// Fresh throwaway context: no existing profile, no persisted state.
const context = await browser.newContext({ deviceScaleFactor: 2, locale: "en-US" });
const page = await context.newPage();

for (const scenario of SCENARIOS) {
  for (const viewport of VIEWPORTS) {
    try {
      await reviewScenario(page, scenario, viewport);
    } catch (error) {
      record(scenario, viewport.name, "FAIL", `threw: ${error.message.slice(0, 200)}`);
    }
  }
}

await reviewCachedRetention(page).catch((error) =>
  record("cached-retention", "wide", "FAIL", `threw: ${error.message.slice(0, 200)}`),
);
await page.unroute("**/api/opencode-go/quota*").catch(() => {});

await context.close();
await browser.close();

const fails = findings.filter((f) => f.level === "FAIL");
const warns = findings.filter((f) => f.level === "WARN");
const lines = [
  "# OpenCode Go Accounts card - live browser review",
  "",
  `Chromium via Playwright, throwaway context, isolated fixture server at ${baseUrl}.`,
  `Scenarios: ${SCENARIOS.length}. Viewports: ${VIEWPORTS.map((v) => `${v.name} ${v.width}x${v.height}`).join(", ")}.`,
  "",
  `**${fails.length} failures, ${warns.length} warnings.**`,
  "",
];
for (const level of ["FAIL", "WARN", "ok"]) {
  const rows = findings.filter((f) => f.level === level);
  if (rows.length === 0) continue;
  lines.push(`## ${level} (${rows.length})`, "");
  for (const r of rows) lines.push(`- \`${r.scenario}\` / ${r.viewport}: ${r.note}`);
  lines.push("");
}
writeFileSync(join(outDir, "review.md"), lines.join("\n"));
console.log(lines.join("\n"));
process.exit(fails.length > 0 ? 1 : 0);
