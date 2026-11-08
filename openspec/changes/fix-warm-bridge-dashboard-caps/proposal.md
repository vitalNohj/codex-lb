# Change: Honor dashboard account caps on warm HTTP bridge turns

## Why

An idle HTTP bridge releases its stream lease between turns. Its next turn reacquires a lease without passing account concurrency caps, so the balancer checks startup defaults instead of the dashboard override. This incorrectly rejects an unlimited dashboard configuration and can admit work above a stricter dashboard limit.

## What Changes

- Include dashboard-derived account caps in the existing pre-lock reacquisition snapshot for keyed and unkeyed sessions.
- Use one cached dashboard row for missing caps, fair-share threshold, and routing tunables in the lock-free fallback, even when the threshold is already supplied.
- Preserve the no-settings-read path for sessions that already hold a stream lease, along with existing cap partitioning, fair-share accounting, and local-cap error envelopes.
- Audit the other direct lease, account selection, opportunistic admission, and HTTP streaming callers; their existing dashboard cap propagation needs no changes.

## Capabilities

### Modified Capabilities

- `proxy-admission-control`: require dashboard cap precedence on warm HTTP bridge reacquisition.

## Impact

Only HTTP bridge lease admission and its tests change. No settings, defaults, migrations, dashboard UI, or other admission policies change. Settings-cache refreshes remain outside `pending_lock`.
