## 1. Transient drain classification

- [x] 1.1 Add the `proxy_continuity_owner_hold_seconds` setting (default 10 s, 0 disables) and the pure owner-drain classifier in `app/modules/proxy/owner_drain.py`: bounded error backoff after repeated transient upstream errors, or the DRAINING/PROBING health tier, counts as transient; removed, deactivated, paused, re-auth-required, rate-limited, quota-exhausted, cooldown, or policy-conflict owners are permanent.

## 2. Bounded hold inside account selection

- [x] 2.1 Hold the required-owner failure in `app/modules/proxy/_service/selection_hold.py`: re-check the same-owner selection on a poll interval bounded by the hold and the request budget; recovery proceeds on that same owner and never reroutes; a poll-acquired lease is released immediately; waits use plain `asyncio.sleep` so client cancellation propagates; expiry marks the failure `owner_hold_expired`.

## 3. Retryable hold-expiry responses

- [x] 3.1 Serve hold-expired failures as HTTP 503 + `Retry-After` (15 s) with the stable `previous_response_owner_unavailable` error body/code on the HTTP streaming and websocket surfaces; SSE and websocket failures carry the retry hint; instant-502 paths keep the legacy message and body.

## 4. Validation

- [x] 4.1 Regression tests: owner recovers within the hold (same owner), hold expiry → 503 + Retry-After, permanent unavailability skips the hold, owner turning permanent mid-hold aborts unmarked, client cancel during hold, hold-expired websocket connect frame and stream events.
- [x] 4.2 Delta spec matches the repo's existing change format (ADDED Requirements + Scenario blocks); `openspec validate --strict` could not run because the CLI is unavailable in this environment.