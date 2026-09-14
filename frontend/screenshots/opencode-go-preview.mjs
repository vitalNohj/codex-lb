/**
 * Throwaway local preview server for the OpenCode Go settings review.
 *
 * Serves the built dashboard with a fully mocked, in-memory API on an isolated
 * port. There is no database, no upstream provider call, no credential, and no
 * shared state: every response below is a literal fixture. Run it only for a
 * local visual review.
 *
 *   bun run build
 *   node screenshots/opencode-go-preview.mjs [--port 4188] [--scenario configured]
 */
import { createReadStream, existsSync, statSync } from "node:fs";
import { createServer } from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// vite builds into app/static (see frontend/vite.config.ts outDir).
const DIST = path.resolve(__dirname, "../../app/static");

function arg(name, fallback) {
  const index = process.argv.indexOf(`--${name}`);
  return index === -1 ? fallback : process.argv[index + 1];
}

const PORT = Number(arg("port", "4188"));
const SCENARIO = arg("scenario", "configured");

const MODELS = [
  { id: "kimi-k3", created: 523, ownedBy: "moonshotai", protocol: "chat_completions", routable: true, unavailableReason: null, privacySensitive: false, privacyNote: null },
  { id: "glm-5.3", created: 524, ownedBy: "zai", protocol: "chat_completions", routable: true, unavailableReason: null, privacySensitive: false, privacyNote: null },
  { id: "deepseek-v4-flash", created: 525, ownedBy: "deepseek", protocol: "chat_completions", routable: true, unavailableReason: null, privacySensitive: false, privacyNote: null },
  { id: "muse-spark-1.3-contributor", created: 526, ownedBy: "meta", protocol: "responses", routable: true, unavailableReason: null, privacySensitive: true, privacyNote: "Trains on prompts, not ZDR" },
  { id: "qwen3.8-max", created: 527, ownedBy: "alibaba", protocol: "messages", routable: false, unavailableReason: "Messages protocol not implemented", privacySensitive: false, privacyNote: null },
  { id: "hy4-preview", created: 528, ownedBy: "opencode", protocol: null, routable: false, unavailableReason: "Protocol unknown", privacySensitive: false, privacyNote: null },
];

const SCENARIOS = {
  unconfigured: { enabled: false, configured: false, status: "missing_api_key", message: null, models: [] },
  configured: { enabled: false, configured: true, status: "healthy", message: "OpenCode Go reachable", models: MODELS },
  enabled: { enabled: true, configured: true, status: "healthy", message: "OpenCode Go reachable", models: MODELS },
  unauthorized: { enabled: true, configured: true, status: "unauthorized", message: "Invalid API key", models: [] },
  unreachable: { enabled: true, configured: true, status: "unreachable", message: "Connection to opencode.ai timed out", models: [] },
};

const scenario = SCENARIOS[SCENARIO] ?? SCENARIOS.configured;

const SETTINGS = {
  stickyThreadsEnabled: true,
  upstreamStreamTransport: "default",
  httpDownstreamTransportPolicy: "smart",
  upstreamProxyRoutingEnabled: false,
  upstreamProxyDefaultPoolId: null,
  preferEarlierResetAccounts: false,
  preferEarlierResetWindow: "secondary",
  showResetCreditBadges: true,
  autoRedeemResetCreditsBeforeExpiry: false,
  showResetCreditExpiryBadge: true,
  routingStrategy: "usage_weighted",
  relativeAvailabilityPower: 2,
  relativeAvailabilityTopK: 5,
  singleAccountId: null,
  prohibitFastMode: false,
  proxyAccountResponseCreateLimit: 4,
  proxyAccountStreamLimit: 8,
  proxyAccountStreamRecoveryReserve: 1,
  weeklyPaceWorkingDays: "0,1,2,3,4,5,6",
  weeklyPaceSmoothingMinutes: 30,
  openaiCacheAffinityMaxAgeSeconds: 300,
  dashboardSessionTtlSeconds: 31536000,
  warmupModel: "gpt-5.4-mini",
  importWithoutOverwrite: false,
  totpRequiredOnLogin: false,
  totpConfigured: true,
  apiKeyAuthEnabled: true,
  hideUpstreamQuotaFromApiKeys: false,
  limitWarmupEnabled: false,
  limitWarmupWindows: "both",
  limitWarmupModel: "auto",
  limitWarmupPrompt: "Say OK.",
  limitWarmupCooldownSeconds: 3600,
  limitWarmupExhaustedThresholdPercent: 99,
  limitWarmupIdleThresholdPercent: 1,
  limitWarmupMinAvailablePercent: 100,
  limitWarmupStaggeredIdleEnabled: false,
  claudeSidecarAuthPlans: [],
  claudeSidecarUsagePollIntervalSeconds: 15,
  claudeSidecarUsageQueueBatchSize: 100,
  claudeSidecarUsageCollectionEnabled: true,
  guestAccessEnabled: false,
  guestPasswordConfigured: false,
  requestLogRetentionDays: 0,
  usageHistoryRetentionDays: 0,
  requestLogRetentionOverrideDays: null,
  usageHistoryRetentionOverrideDays: null,
  opencodeGoSidecarEnabled: scenario.enabled,
  opencodeGoSidecarBaseUrl: "https://opencode.ai/zen/go/v1",
  opencodeGoSidecarApiKeyConfigured: scenario.configured,
  opencodeGoSidecarModelPrefixes: [{ prefix: "opencode-go/", strip: true }],
  opencodeGoSidecarFullModels: scenario.enabled ? ["kimi-k3"] : [],
  opencodeGoSidecarConnectTimeoutSeconds: 8,
  opencodeGoSidecarRequestTimeoutSeconds: 600,
  opencodeGoSidecarModelsCacheTtlSeconds: 60,
  opencodeGoSidecarLastHealthStatus: scenario.status,
  opencodeGoSidecarLastHealthMessage: scenario.message,
  opencodeGoSidecarLastCheckedAt: "2026-01-01T00:00:00Z",
  opencodeGoSidecarLastModelCount: scenario.models.length,
  version: 1,
};

const GO_STATUS = {
  enabled: scenario.enabled,
  configured: scenario.configured,
  status: scenario.status,
  message: scenario.message,
  baseUrl: "https://opencode.ai/zen/go/v1",
  modelCount: scenario.models.length,
  lastCheckedAt: "2026-01-01T00:00:00Z",
};

const EMPTY_SIDECAR = (baseUrl) => ({
  enabled: false,
  configured: false,
  status: "disabled",
  message: null,
  baseUrl,
  modelCount: 0,
  lastCheckedAt: null,
});

const ROUTES = {
  "/api/dashboard-auth/session": { authenticated: true, authMode: "password", canWrite: true, passwordManagementEnabled: true, passwordSessionActive: true, guestAccessEnabled: false, passwordConfigured: true },
  "/api/runtime/version": { version: "preview", commit: "preview" },
  "/api/settings": SETTINGS,
  "/api/settings/upstream-proxy": { routingEnabled: false, defaultPoolId: null, endpoints: [], pools: [], bindings: [] },
  "/api/settings/telemetry": { consent: "undecided", instanceId: null, lastSentAt: null, preview: null },
  "/api/accounts": { accounts: [] },
  "/api/models": { models: [] },
  "/api/api-keys": { apiKeys: [] },
  "/api/api-keys/": { apiKeys: [] },
  "/api/dashboard/overview": { accounts: [], totals: null, generatedAt: "2026-01-01T00:00:00Z" },
  "/health/ready": { status: "ok" },
  "/api/opencode-go-sidecar/status": GO_STATUS,
  "/api/opencode-go-sidecar/models": { models: scenario.models },
  "/api/opencode-go-sidecar/test": { ...GO_STATUS, models: scenario.models },
  "/api/claude-sidecar/status": EMPTY_SIDECAR("http://127.0.0.1:8317"),
  "/api/claude-sidecar/models": { models: [] },
  "/api/claude-sidecar/routing": { strategy: "round_robin", accounts: [], status: "healthy", message: null },
  "/api/claude-sidecar/quota": { accounts: [], status: "healthy", message: null },
  "/api/openrouter-sidecar/status": EMPTY_SIDECAR("https://openrouter.ai/api/v1"),
  "/api/openrouter-sidecar/models": { models: [] },
  "/api/orcarouter-sidecar/status": EMPTY_SIDECAR("https://api.orcarouter.ai/v1"),
  "/api/orcarouter-sidecar/models": { models: [] },
  "/api/ollama-sidecar/status": EMPTY_SIDECAR("https://ollama.com"),
  "/api/ollama-sidecar/models": { models: [] },
  "/api/model-sources": { sources: [] },
  "/api/firewall/rules": { rules: [] },
  "/api/quota-planner/settings": { policies: [] },
  "/api/sticky-sessions": { sessions: [] },
  "/health": { status: "ok" },
};

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
  ".woff2": "font/woff2",
  ".json": "application/json; charset=utf-8",
};

function json(res, body, status = 200) {
  const payload = JSON.stringify(body);
  res.writeHead(status, { "Content-Type": "application/json; charset=utf-8", "Content-Length": Buffer.byteLength(payload) });
  res.end(payload);
}

createServer((req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);
  const apiPath = url.pathname.replace(/^\/codex/, "") || "/";

  if (apiPath.startsWith("/api/") || apiPath.startsWith("/health")) {
    const body = ROUTES[apiPath];
    if (body !== undefined) {
      // Writes are accepted and echoed so the UI's optimistic flow works, but
      // nothing is persisted: the preview is stateless by design.
      if (req.method === "PUT" && apiPath === "/api/settings") {
        return json(res, { ...SETTINGS, version: SETTINGS.version + 1 });
      }
      return json(res, body);
    }
    return json(res, { error: { code: "not_found", message: `No preview fixture for ${apiPath}` } }, 404);
  }

  let filePath = path.join(DIST, url.pathname.replace(/^\/codex/, "") || "/index.html");
  if (!existsSync(filePath) || statSync(filePath).isDirectory()) {
    filePath = path.join(DIST, "index.html");
  }
  res.writeHead(200, { "Content-Type": MIME[path.extname(filePath)] ?? "application/octet-stream" });
  createReadStream(filePath).pipe(res);
}).listen(PORT, "127.0.0.1", () => {
  console.log(`OpenCode Go preview [${SCENARIO}] -> http://127.0.0.1:${PORT}/codex/settings`);
});
