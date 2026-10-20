## 1. Native route

- [x] 1.1 Add `responses()` / `stream_responses()` to the CLIProxyAPI client for its `/v1/responses`.
- [x] 1.2 Route `/v1/responses` for plain xAI wire models to the native path behind `CODEX_LB_CLIPROXY_XAI_NATIVE_RESPONSES_ENABLED`; keep every other model on the chat bridge.
- [x] 1.3 Forward the body with only `model`, `prompt_cache_key` and an absent-effort default changed; relay the response unchanged.
- [x] 1.4 Refuse with 503 `cliproxy_not_configured`, sending nothing, when the CLIProxyAPI API key is unusable; reject `previous_response_id`, `conversation` and `store: true` before reserving quota.
- [x] 1.5 Always send `prompt_cache_key`, equal to the sticky pin identity, or a random key when there is none.

## 2. Routing, limits and accounting

- [x] 2.1 Reuse account selection, sticky pins, cooldown waits and 401/403/429 rebind from the chat route.
- [x] 2.2 Enforce the API key's service tier and reserve usage like the chat route; settle or release on every outcome.
- [x] 2.3 Map cached and reasoning tokens from Responses usage; record `cost_in_usd_ticks / 1e10` as the upstream-billed cost for streaming and non-streaming.
- [x] 2.4 Log `response.failed`, `error` and truncated streams as errors; end a truncated stream with `response.failed`.

## 3. Session affinity guard

- [x] 3.1 Read `routing.session-affinity` on each quota poll; publish a gauge and warn when it is off; never fail the poll on the read.
- [x] 3.2 Show a warning on the dashboard toggle when affinity is off.

## 4. Verification

- [x] 4.1 Unit and integration tests for each behavior above, each failing without its change.
- [x] 4.2 Opt-in end-to-end test against a real CLIProxyAPI v8 binary and a fake xAI upstream: encrypted reasoning round-trips byte-for-byte across turns and the cache key, conv id and credential stay stable.
