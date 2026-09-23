## Why

Redeeming a rate-limit reset credit already force-refreshes usage, but recovery still honors the pre-reset 429 `blocked_at`/`reset_at` cooldown. A Plus account can sit at 0%/0% after a successful reset while the dashboard keeps the Rate limited label and routing skips it until the old weekly deadline.

## What Changes

- After a successful reset-credit consume, the forced usage refresh MUST ignore that persisted 429 cooldown and recover `rate_limited`/`quota_exceeded` to `active` when post-reset windows have available quota.
- The consume clears persisted `blocked_at` even when that forced snapshot is still exhausted, so a later periodic refresh recovers once usage catches up, including after restart.
- Periodic usage refresh keeps honoring the cooldown while `blocked_at` is still set. Exhausted post-reset windows stay blocked.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `rate-limit-reset-credits`: Successful consume recovers blocked account status from the post-reset usage snapshot.
- `account-routing`: Reset-credit consume is an exception to the future-`reset_at` peer cooldown hold.

## Impact

- Dashboard, v1, Codex-identity, and auto-redeem consume paths.
- Usage recovery compare-and-set writes.
- No schema, migration, or dashboard contract change.
