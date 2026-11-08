## Implementation

- [x] Include account concurrency caps in the pre-lock dashboard settings snapshot and both locked reacquisition calls.
- [x] Resolve missing caps from the dashboard for lock-free callers, including unkeyed sessions and callers with an existing fair-share threshold.
- [x] Audit all production callers of direct lease, selection, opportunistic admission, and HTTP streaming cap fallbacks.

## Verification

- [x] Reproduce startup-default rejection with dashboard unlimited using the real load balancer.
- [x] Cover unlimited, stricter-full, and stricter-available dashboard limits for keyed and unkeyed sessions, through submit and lock-free reacquisition.
- [x] Verify snapshot callers never refresh settings under `pending_lock`, stalled settings leave the lock free, and held-lease submissions need no settings read.
- [x] Run affected HTTP bridge and load-balancer test files plus changed-file lint/type checks (1,512 tests pass; Ruff and ty pass).
- [x] Validate this OpenSpec change and all main specs (68 specs pass).

The optional architecture and timing-seam checks expose existing baseline violations in unchanged `streaming/mixin.py` (1,101 lines; limit 1,100) and `cliproxy_account_routing.py` (8 raw clock reads; allowance 7). Cancellation-safety and settings-tier checks pass. These unrelated baseline violations are outside this fix.
