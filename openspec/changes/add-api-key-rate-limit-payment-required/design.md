## Context

A 429 can leave codex-lb from many places: account selection failures on the
chat, Responses, compact, files, and HTTP-bridge paths, upstream Codex usage
errors relayed during stream startup, per-key limit enforcement, and sidecar
dispatchers. `app/modules/proxy/api.py` alone has 18 `ProxyResponseError`
handlers and more than 80 error-response call sites. Patching each one would be
fragile, and every new error path would have to remember the flag.

## Decision: rewrite the status line once, on the way out

1. The proxy auth dependencies (`validate_proxy_api_key`,
   `validate_required_proxy_api_key`) record the authenticated `ApiKeyData` on
   the ASGI scope state (`app/core/auth/request_api_key.py`, a leaf module so
   the dependency and the middleware do not import each other).
2. A pure ASGI middleware, installed innermost, wraps `send` for HTTP requests
   on proxy paths. At `http.response.start`, if the status is 429 and the
   recorded key has `rate_limit_as_payment_required`, it changes the status to
   402. Everything else passes through untouched, including streamed bodies.

The flag rides on `ApiKeyData`, which is already cached per key hash and
invalidated on update, so the middleware adds no database reads and no
buffering.

### Why every 429, not only usage-exhaustion codes

An earlier draft limited the rewrite to `usage_limit_reached`,
`rate_limit_exceeded`, and `insufficient_quota`, keeping 429 for local overload
codes that clear in seconds. That needed the body buffered and parsed. It
turned out to be unnecessary:

- The global overload gates (`BackpressureMiddleware`, `BulkheadMiddleware`)
  reject before the route runs, so no API key is recorded and their 429s are
  never rewritten.
- The only local overload code a route produced for the Kodus keys in the 30
  days before this change was `account_response_create_cap` (38 times), a
  per-account concurrency cap. For a client with its own fallback model,
  moving to the fallback at once beats a retry storm there too.

So the rule is "a flagged key never sees 429". It is simpler, needs no body
parsing, and matches why an operator sets the flag.

### Why a middleware instead of changing the response helpers

- One place owns the rule, so a new error path is covered automatically.
- The decision uses the final status, which is exactly what the client sees.
- Request logs, metrics recorded inside routes, and account health keep the
  real cause. Only the wire status changes, and only for keys that opted in.

## Alternatives considered

- **Per-call-site flag checks.** Rejected: dozens of sites, easy to miss one.
- **A global setting.** Rejected: 429 is correct for Codex CLI, Cursor, and
  every client that honors `Retry-After`. Only specific clients need 402.
- **Model alias pools with a Claude fallback.** Rejected for now: pools do not
  support native Codex targets.

## Risks

- A client that treats 402 as a billing problem may show an "out of credit"
  message while the pool is exhausted. That is the intended trade-off, and the
  flag is off by default and set per key.
- A client that honors `Retry-After` on a 429 loses that retry when flagged.
  The flag is meant for clients that fail over instead.
