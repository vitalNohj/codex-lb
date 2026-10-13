# Hold continuity-bound requests while the required owner is only transiently drained

## Why

When an OpenAI upstream incident (service restarts, `server_error`, `server_is_overloaded`) marks an account as transiently drained, the account enters bounded error backoff for up to a few minutes. Any continuity-bound follow-up whose `previous_response_id` is owned by that account then fails **instantly** with HTTP 502 `previous_response_owner_unavailable` ("retry later") — even though the owner usually recovers well within a minute. In three days of production logs this produced 81 such 502s, all avoidable: the client could not distinguish "owner is gone" from "owner is briefly recovering", and a client-side retry loop burns requests while still losing the turn.

## What Changes

- When a required continuity owner fails selection and the owner is unavailable **only** because it is transiently drained/probing (bounded error backoff after repeated transient upstream errors, or the DRAINING/PROBING health tier), the proxy holds the request for a short bounded wait (default 10 s, `proxy_continuity_owner_hold_seconds`, 0 disables), re-checking the owner selection on a poll interval.
- If the owner becomes selectable during the hold, the request proceeds normally on that **same** owner. The hard-continuity invariant is unchanged: the continuation is never routed to a different account.
- If the hold expires, the service responds with HTTP **503** plus a `Retry-After` header (15 s) carrying the **same** `previous_response_owner_unavailable` error body/code, instead of the instant 502. SSE and websocket surfaces keep the stable code and mark the failure retryable (SSE `response.failed` event carries the retry hint; websocket connect failure frame uses status 503).
- The hold never waits on permanent unavailability (owner removed, deactivated, paused, re-auth required, rate-limited, quota-exhausted, cooldown, outside the eligible policy, or lookup miss) — those keep today's instant fail-closed behavior.
- While waiting, the request holds no account lease or stream slot, and client disconnect/cancel propagates immediately.
- Affected paths: `app/modules/proxy/service.py` (`_select_account_with_budget` hold wiring), new `app/modules/proxy/owner_drain.py` (pure transient-drain classification), new `app/modules/proxy/_service/selection_hold.py` (bounded hold), `app/modules/proxy/_service/http_bridge/{helpers,mixin}.py`, `app/modules/proxy/_service/streaming/retry.py`, `app/modules/proxy/_service/websocket/mixin.py`, `app/modules/proxy/selection_errors.py` (shared 503/Retry-After helpers), `app/core/config/settings.py`.

## Capabilities

### New capability: none (extends existing behavior)

This change refines the fail-closed continuity behavior described by `sticky-session-operations`; no new capability is introduced.

## Impact

- Affected specs: `sticky-session-operations` (adds a bounded-hold requirement alongside the existing owner-bound fail-closed requirement; the stable `previous_response_owner_unavailable` code and the never-reroute invariant are unchanged)
- Affected backend code: as listed in What Changes
- No frontend changes, no migrations, no new default-off setup steps (the hold is zero-config with a working default)