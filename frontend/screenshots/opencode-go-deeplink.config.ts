import { defineConfig } from "@playwright/test";

/**
 * Isolated local preview for the OpenCode Go settings deep link.
 *
 * Mirrors excluded-models.config.ts: its own build directory, its own port, a
 * static server, and fully mocked API routes. No production server, profile, or
 * credential is involved, and the page makes no external request.
 *
 * The `.opencode-go-build/` directory is a throwaway artifact of this run; like
 * `.excluded-models-build/` it is not committed.
 */
export default defineConfig({
  testDir: ".",
  testMatch: "opencode-go-deeplink.spec.ts",
  outputDir: (process.env.OPENCODE_GO_EVIDENCE_DIR ?? ".") + "/playwright-output",
  use: { viewport: { width: 1440, height: 1000 } },
  webServer: {
    command:
      "cd .. && bun x vite build --outDir .opencode-go-build/codex && ../.venv/bin/python -m http.server 4174 --directory .opencode-go-build",
    port: 4174,
    reuseExistingServer: false,
  },
});
