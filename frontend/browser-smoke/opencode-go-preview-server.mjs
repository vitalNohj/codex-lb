/**
 * Isolated fixture server for the OpenCode Go Accounts-card visual review.
 *
 * Serves the built dashboard plus a hand-written, entirely local API surface.
 * There is no database, no account auth directory, no upstream call and no
 * credential of any kind: every response below is a literal in this file.
 *
 * Not part of the test suite and not a claim about upstream behaviour - it
 * exists so the card's states can be inspected in a real browser on a private
 * port. Scenario is chosen with ?scenario= on any dashboard URL.
 *
 * Usage: node browser-smoke/opencode-go-preview-server.mjs <port> <dist-dir>
 */
import { createReadStream, existsSync, realpathSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, resolve, sep } from "node:path";

const port = Number(process.argv[2] ?? 4599);
const distDir = process.argv[3] ?? "../app/static";

/**
 * Real path of the served root, resolved once. Every static response must live
 * under it. See `resolveStaticFile` for why this is checked after realpath
 * rather than only after normalize.
 */
const DIST_ROOT = realpathSync(resolve(distDir));

/**
 * Resolve a request path to a file, or null if it would escape the served root.
 *
 * Two distinct escapes are possible and only one of them is closed by string
 * normalization:
 *
 * 1. **Dot segments** (`/../../etc/passwd`, `%2e%2e`, backslashes). These do not
 *    actually reach the filesystem here: `new URL()` resolves and collapses dot
 *    segments while parsing, so `url.pathname` is already normalized before it
 *    is joined. Verified empirically against a synthetic canary outside the
 *    root - 14 encoded/raw variants all fell through to the SPA fallback.
 * 2. **Symlinks inside the root pointing out of it.** Pure path arithmetic
 *    cannot see these: the joined path is textually inside the root, and only
 *    resolving the link reveals it is not. This one is real, so the containment
 *    check below is done on the *realpath* of the candidate.
 *
 * The check is belt-and-braces on purpose. This harness only ever serves a
 * build directory on a loopback port, but "it is only local" is not a
 * containment argument, and a fixture server should not be the thing that
 * makes an arbitrary file readable.
 */
function resolveStaticFile(requestPath) {
  const candidate = resolve(DIST_ROOT, `.${requestPath === "/" ? "/index.html" : requestPath}`);
  if (!existsSync(candidate)) {
    return null;
  }
  let real;
  try {
    real = realpathSync(candidate);
  } catch {
    return null;
  }
  if (real !== DIST_ROOT && !real.startsWith(DIST_ROOT + sep)) {
    return null;
  }
  return statSync(real).isFile() ? real : null;
}

const iso = (minutesFromNow) =>
  new Date(Date.now() + minutesFromNow * 60_000).toISOString();

const window_ = (key, upstreamKey, percentUsed, resetsAt, extra = {}) => ({
  key,
  upstreamKey,
  status: "ok",
  percentUsed,
  resetsAt,
  limitReached: false,
  ...extra,
});

/** Every state the card can render, as the quota contract would produce it. */
const SCENARIOS = {
  // Today's real shape: three unlabelled windows, scope unknown, no breakdown.
  default: {
    status: "ok",
    scope: "unknown",
    message: null,
    checkedAt: iso(-3),
    refreshedAt: iso(-3),
    stale: false,
    staleReason: null,
    modelBreakdownAvailable: false,
    models: [],
    windows: [
      window_("five_hour", "rolling", 42, iso(95)),
      window_("weekly", "weekly", 68, iso(3 * 24 * 60)),
      window_("monthly", "monthly", 51, iso(19 * 24 * 60)),
    ],
  },
  // Partial data plus an unknown value: neither 0% nor 100%.
  partial: {
    status: "ok",
    scope: "unknown",
    checkedAt: iso(-8),
    refreshedAt: iso(-8),
    stale: false,
    modelBreakdownAvailable: false,
    models: [],
    windows: [
      window_("five_hour", "rolling", 7, iso(240)),
      {
        key: "weekly",
        upstreamKey: "weekly",
        status: "unknown",
        percentUsed: null,
        resetsAt: null,
        limitReached: null,
      },
    ],
  },
  exhausted: {
    status: "ok",
    scope: "unknown",
    checkedAt: iso(-1),
    refreshedAt: iso(-1),
    stale: false,
    modelBreakdownAvailable: false,
    models: [],
    windows: [
      window_("five_hour", "rolling", 100, iso(42), { limitReached: true }),
      window_("weekly", "weekly", 93, iso(2 * 24 * 60)),
    ],
  },
  stale: {
    status: "stale",
    scope: "unknown",
    message: null,
    checkedAt: iso(-95),
    refreshedAt: iso(-1),
    stale: true,
    staleReason: "upstream read timed out after 8.0s",
    modelBreakdownAvailable: false,
    models: [],
    windows: [
      window_("five_hour", "rolling", 30, iso(150)),
      window_("weekly", "weekly", 74, iso(4 * 24 * 60)),
    ],
  },
  // Hypothetical future upstream that grows a model dimension, including a
  // deliberately long id to check truncation and grid alignment.
  per_model: {
    status: "ok",
    scope: "per_model",
    checkedAt: iso(-2),
    refreshedAt: iso(-2),
    stale: false,
    modelBreakdownAvailable: true,
    windows: [window_("five_hour", "rolling", 38, iso(120))],
    models: [
      {
        modelId: "claude-sonnet-4.5",
        displayName: "Claude Sonnet 4.5",
        windows: [
          window_("five_hour", "rolling", 22, iso(120)),
          window_("weekly", "weekly", 61, iso(4 * 24 * 60)),
        ],
      },
      {
        modelId: "qwen3.8-max-preview-with-an-unusually-long-upstream-identifier-for-layout-testing",
        displayName: null,
        windows: [
          window_("five_hour", "rolling", 96, iso(35), {
            status: "rate_limited",
            limitReached: null,
          }),
        ],
      },
      {
        modelId: "glm-5.3",
        displayName: "GLM 5.3",
        windows: [window_("weekly", "weekly", 12, iso(5 * 24 * 60))],
      },
    ],
  },
  disabled: {
    status: "disabled",
    scope: "unknown",
    checkedAt: null,
    refreshedAt: null,
    stale: false,
    modelBreakdownAvailable: false,
    models: [],
    windows: [],
  },
  not_configured: {
    status: "not_configured",
    scope: "unknown",
    checkedAt: null,
    refreshedAt: null,
    stale: false,
    modelBreakdownAvailable: false,
    models: [],
    windows: [],
  },
  unauthorized: {
    status: "unauthorized",
    scope: "unknown",
    message: "OpenCode rejected the stored key (HTTP 401)",
    checkedAt: null,
    refreshedAt: iso(-1),
    stale: false,
    modelBreakdownAvailable: false,
    models: [],
    windows: [],
  },
  rate_limited: {
    status: "rate_limited",
    scope: "unknown",
    message: "usage endpoint returned HTTP 429",
    checkedAt: null,
    refreshedAt: iso(-1),
    stale: false,
    modelBreakdownAvailable: false,
    models: [],
    windows: [],
  },
  unavailable: {
    status: "unavailable",
    scope: "unknown",
    message: "connection reset by peer",
    checkedAt: null,
    refreshedAt: iso(-1),
    stale: false,
    modelBreakdownAvailable: false,
    models: [],
    windows: [],
  },
};

/** Non-scenario responses: malformed body, absent route, and a slow read. */
const SPECIAL = new Set(["malformed", "absent", "loading", "flaky"]);

/**
 * `flaky` serves one good snapshot then fails every later request, which is the
 * refetch/remount path where cached values must survive.
 */
let flakyCalls = 0;

const account = (over = {}) => ({
  accountId: "acc_primary",
  chatgptAccountId: "chatgpt_acc_primary",
  email: "primary@example.com",
  displayName: "primary@example.com",
  planType: "plus",
  routingPolicy: "normal",
  status: "active",
  usage: {
    primaryRemainingPercent: 82,
    secondaryRemainingPercent: 67,
    monthlyRemainingPercent: null,
  },
  resetAtPrimary: iso(60),
  resetAtSecondary: iso(24 * 60),
  windowMinutesPrimary: 300,
  windowMinutesSecondary: 10_080,
  additionalQuotas: [],
  limitWarmupEnabled: false,
  sidecarAuths: [],
  ...over,
});

const JSON_ROUTES = {
  "/api/dashboard-auth/session": {
    authenticated: true,
    passwordRequired: false,
    totpRequiredOnLogin: false,
    totpConfigured: false,
    bootstrapRequired: false,
    bootstrapTokenConfigured: false,
    authMode: "standard",
    passwordManagementEnabled: true,
    passwordSessionActive: true,
    role: "admin",
    permissions: ["read", "write"],
    guestAccessEnabled: false,
    guestPasswordRequired: false,
  },
  "/api/accounts": {
    accounts: [
      account(),
      account({
        accountId: "acc_secondary",
        email: "secondary@example.com",
        displayName: "secondary@example.com",
        status: "paused",
        usage: { primaryRemainingPercent: 45, secondaryRemainingPercent: 12 },
      }),
    ],
  },
  "/api/settings": {
    version: 1,
    showResetCreditBadges: true,
    showResetCreditExpiryBadge: true,
  },
  "/api/settings/telemetry": { enabled: false, environmentManaged: false },
  "/api/runtime/version": { version: "1.24.0-preview" },
  "/health": { status: "ok" },
  "/health/ready": { status: "ok" },
};

function sendJson(res, body, status = 200) {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    "content-type": "application/json",
    "cache-control": "no-store",
    "content-length": Buffer.byteLength(payload),
  });
  res.end(payload);
}

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
  ".json": "application/json",
  ".woff2": "font/woff2",
};

const server = createServer(async (req, res) => {
  const url = new URL(req.url, `http://127.0.0.1:${port}`);
  // Strip the deployed /codex base path the built bundle uses.
  const path = url.pathname.replace(/^\/codex/, "") || "/";
  // The dashboard fetches the bare API path, so the scenario travels on the
  // document URL and is recovered from the Referer. Without this the card would
  // silently always receive the default fixture.
  const refererScenario = (() => {
    try {
      return new URL(req.headers.referer ?? "").searchParams.get("scenario");
    } catch {
      return null;
    }
  })();
  const scenario = url.searchParams.get("scenario") ?? refererScenario ?? "default";

  if (path === "/api/opencode-go/quota") {
    if (scenario === "absent") {
      return sendJson(res, { error: { code: "not_found", message: "Not Found" } }, 404);
    }
    if (scenario === "malformed") {
      return sendJson(res, { totallyUnexpected: true, windows: "nope" });
    }
    if (scenario === "loading") {
      await new Promise((r) => setTimeout(r, 60_000));
      return sendJson(res, SCENARIOS.default);
    }
    if (scenario === "flaky") {
      flakyCalls += 1;
      if (flakyCalls === 1) return sendJson(res, SCENARIOS.default);
      return sendJson(res, { error: { code: "boom", message: "boom" } }, 500);
    }
    if (scenario === "reset-flaky") {
      flakyCalls = 0;
      return sendJson(res, { ok: true });
    }
    return sendJson(res, SCENARIOS[scenario] ?? SCENARIOS.default);
  }

  if (path in JSON_ROUTES) {
    return sendJson(res, JSON_ROUTES[path]);
  }
  if (path.startsWith("/api/") && path.endsWith("/trends")) {
    return sendJson(res, { accountId: "acc_primary", primary: [], secondary: [], secondaryScheduled: [] });
  }
  if (path.startsWith("/api/") && path.endsWith("/usage-reset-credits")) {
    return sendJson(res, {
      accountId: "acc_primary",
      rateLimitResetCredits: { availableCount: 0 },
    });
  }
  // Anything else under /api is deliberately an empty success, so an unrelated
  // panel cannot block the page this review is about.
  if (path.startsWith("/api/")) {
    return sendJson(res, {});
  }

  // Anything that does not resolve to a real file inside the served root falls
  // back to the SPA entry point, which is also what an unknown client-side
  // route needs.
  const file = resolveStaticFile(path) ?? join(DIST_ROOT, "index.html");
  res.writeHead(200, {
    "content-type": MIME[extname(file)] ?? "application/octet-stream",
    "cache-control": "no-store",
  });
  createReadStream(file).pipe(res);
});

server.listen(port, "127.0.0.1", () => {
  console.log(`opencode-go preview on http://127.0.0.1:${port}/codex/accounts`);
  console.log(`scenarios: ${[...Object.keys(SCENARIOS), ...SPECIAL].join(", ")}`);
});
