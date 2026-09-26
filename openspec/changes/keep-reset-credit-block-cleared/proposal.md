## Why

A successful reset-credit consume clears persisted `blocked_at`, but account selection still holds the pre-reset 429 in process memory. The next selection writes that marker back onto the row. Later usage refreshes then honor the old `reset_at` and leave the account rate-limited until that deadline, even after `/wham/usage` shows the window was reset.

## What Changes

- Account selection MUST NOT persist a runtime 429 block marker onto a row whose persisted `blocked_at` is already null.
- The reset-credit forced usage refresh MUST drop that account's in-process rate-limit runtime markers after it clears persisted `blocked_at`.
- A later periodic refresh that sees available quota MUST still be able to mark the account active before the pre-reset `reset_at` elapses.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `account-routing`: Selection must not resurrect a reset-credit-cleared 429 marker from runtime state.

## Impact

- Load balancer account-state persistence.
- Reset-credit forced usage refresh.
- No schema, migration, or dashboard contract change.
