import { expect, test } from "@playwright/test";
import { readFile, writeFile } from "node:fs/promises";
import { authSession, settings, upstreamProxyAdmin } from "./fixtures";

test("operator adds, reloads, and removes per-account exclusions", async ({ page }) => {
  const evidence = process.env.EXCLUSION_EVIDENCE_DIR;
  let stored: string[] = [];
  const writes: unknown[] = [];
  const account = () => ({ name: "claude-a@example.com.json", authIndex: "0", email: "a@example.com", priority: 0, paused: false, excludedModels: stored, excludedModelsState: "available" });
  const routing = () => ({ status: "healthy", message: null, strategy: "fill_first", accounts: [account()] });
  await page.route("**/api/**", async route => {
    const p = new URL(route.request().url()).pathname.replace(/^\/codex/, "");
    let body: unknown = {};
    if (p === "/api/dashboard-auth/session") body = authSession;
    else if (p === "/api/settings") body = { ...settings, claudeSidecarEnabled: true, claudeSidecarManagementKeyConfigured: true };
    else if (p === "/api/settings/upstream-proxy") body = upstreamProxyAdmin;
    else if (p === "/api/claude-sidecar/routing") body = routing();
    else if (p === "/api/claude-sidecar/routing/excluded-models") {
      const request = route.request().postDataJSON();
      writes.push(request);
      stored = request.excludedModels;
      body = { ...routing(), savedAccount: account() };
    }
    await route.fulfill({ json: body });
  });
  await page.route("http://localhost:4173/codex/settings", async route => route.fulfill({ contentType: "text/html", body: await readFile(new URL("../.excluded-models-build/codex/index.html", import.meta.url), "utf8") }));
  await page.goto("http://localhost:4173/codex/settings");
  const input = page.getByRole("textbox", { name: "Add excluded model pattern for a@example.com" });
  await input.fill("claude-opus-4-*");
  await input.press("Enter");
  const remove = page.getByRole("button", { name: "Remove claude-opus-4-* from a@example.com" });
  await expect(remove).toBeVisible();
  expect(stored).toEqual(["claude-opus-4-*"]);
  await page.reload();
  await expect(remove).toBeVisible();
  await page.getByRole("switch", { name: "Exclude Fable on a@example.com" }).click();
  await expect(page.getByRole("switch", { name: "Exclude Fable on a@example.com" })).toBeChecked();
  expect(stored).toEqual(["claude-opus-4-*", "claude-fable-*"]);
  await expect(input).toBeEnabled();
  await input.scrollIntoViewIfNeeded();
  if (evidence) await page.screenshot({ path: `${evidence}/excluded-models-settings.png` });
  await remove.click();
  await expect(remove).toHaveCount(0);
  expect(stored).toEqual(["claude-fable-*"]);
  if (evidence) await writeFile(`${evidence}/browser-api-transcript.json`, JSON.stringify({ context: "Real settings UI with stateful mocked management API", writes, finalRoutingResponse: routing() }, null, 2));
});
