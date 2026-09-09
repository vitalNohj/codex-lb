# Reallocate Soft Sticky on Pre-Visible Usage Exhaustion

## Why

A Cursor `/v1/chat/completions` first turn with prompt-cache stickiness can select an
exhausted Codex seat, get `usage_limit_reached` before any tokens, and then both the
same request and the client's resume keep targeting that seat. Failover already
decides `failover_next`, but two other rules undo it:

1. A non-account-neutral body (Composer tools / chat history) is pinned as the
   dispatch owner even when the 429 happened before any downstream-visible output.
2. Soft prompt-cache stickiness preserves the original mapping on rate-limit so the
   next request returns to the warm cache. `usage_limit_reached` is classified as
   `rate_limit`, so that preserve path treats a dead quota window like a 30-second
   blip.

The operator model is: sticky until it fails, then go back to ordinary routing. This
is not a new dead-endpoint denylist.

## What Changes

- Treat `usage_limit_reached`, `insufficient_quota`, `quota_exceeded`, and
  `usage_not_included` as usage exhaustion.
- On a pre-visible usage-exhaustion failure of a request that is not hard-owned
  (no previous-response, turn-state, file, or single-account pin), do not record a
  dispatch owner, exclude the failed account, set `reallocate_sticky=True`, and
  retry ordinary routing with the same body.
- Keep today's fail-closed behavior for hard continuity and for mid-stream
  (downstream-visible) usage exhaustion.
- Keep prompt-cache preserve-on-fallback for short `rate_limit_exceeded` blips.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `responses-api-compat`
- `sticky-session-operations`

## Impact

No API, schema, or settings changes. Streaming retry is the failing surface
(`/v1/chat/completions` and `/v1/responses`). A live `codex-lb` restart is still
required to pick up the code; this change does not restart anything.
