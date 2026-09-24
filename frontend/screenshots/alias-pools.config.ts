import { defineConfig } from "@playwright/test";

/**
 * Isolated local preview for the Routing settings alias pool editor.
 *
 * Mirrors opencode-go-deeplink.config.ts: its own build directory, its own
 * port, a static server, and fully mocked API routes. The `.alias-pools-build/`
 * directory is a throwaway artifact of this run and is not committed.
 *
 * `ALIAS_POOLS_EVIDENCE_DIR` selects where the screenshots land.
 */
export default defineConfig({
  testDir: ".",
  testMatch: "alias-pools.spec.ts",
  outputDir: (process.env.ALIAS_POOLS_EVIDENCE_DIR ?? ".") + "/playwright-output",
  use: {
    viewport: { width: 1440, height: 1000 },
    deviceScaleFactor: 2,
  },
  webServer: {
    command:
      "cd .. && bun x vite build --outDir .alias-pools-build/codex && ../.venv/bin/python -m http.server 4175 --directory .alias-pools-build",
    port: 4175,
    reuseExistingServer: false,
  },
});
