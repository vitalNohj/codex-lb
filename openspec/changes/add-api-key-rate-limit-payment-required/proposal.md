## Why

When every account that can serve a request is rate limited or out of usage,
codex-lb answers `429 usage_limit_reached` with a `Retry-After` of up to 300
seconds. That is the correct HTTP answer, but some clients react to it badly.

Kodus (the Kody code-review agent) is the concrete case. It runs a review as
dozens of separate model calls through the Vercel AI SDK:

- The AI SDK treats 429 as retryable and retries each agent step up to three
  more times, sleeping 2s, 4s, then 8s. It ignores any `Retry-After` longer
  than 60 seconds, so the 300s hint changes nothing.
- Kodus only fails over to its configured fallback model after those retries
  are exhausted, and it does not remember the outcome for the next call. Every
  call starts on the exhausted primary again.
- Kodus one-shot calls never fail over on a 429 at all, so those review steps
  degrade silently (for example severity classification falls back to
  "medium").

In the seven days ending 2026-09-25, 1,971 of 6,490 Kodus requests (30%) were
`usage_limit_reached` answers, and each agent step spent about 15 seconds
waiting on retries that could not succeed. Neither Kodus nor the AI SDK
exposes a setting for this, and the Kodus deployment is hosted, so the fix has
to come from codex-lb.

Both the AI SDK and Kodus treat HTTP 402 as terminal: the SDK does not retry
it, and Kodus classifies it as out of credit and moves to the fallback model on
the first attempt. Letting an operator mark specific API keys so their
rate-limit answers use 402 instead of 429 removes the retry storm for those
clients without changing anything for Codex CLI, Cursor, or any other key.

## What Changes

- Add a per-API-key boolean `rateLimitAsPaymentRequired` (default `false`)
  to the dashboard API, persistence model, and API-key create/edit dialogs.
- When the flag is on, any proxy response to that key that would be `429` is
  sent as `402` instead. The body is unchanged, and `Retry-After` and quota
  headers are kept, so the client still sees why and for how long.
- Keys without the flag, and unauthenticated requests, are unaffected.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `api-keys`: API keys can opt into receiving HTTP 402 instead of 429.

## Impact

- Database: one additive boolean column `api_keys.rate_limit_as_payment_required`
  with server default `false`, so existing keys keep today's behavior.
- Backend: API-key schemas, service, repository, and cache-facing data. The
  proxy auth dependency records the authenticated key on the request scope, and
  one pure ASGI middleware rewrites the status line for flagged keys.
- Dashboard: one checkbox in the API-key create and edit dialogs and one row in
  the key details panel. No new route, setting, env var, or navigation item.
- No new required setup step (PRINCIPLES P1). The feature is off until an
  operator enables it on a specific key.
