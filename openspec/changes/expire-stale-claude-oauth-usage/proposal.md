## Why

The Claude sidecar quota poller keeps the last-known OAuth usage for an auth when a fresh fetch fails, for example on HTTP 429. That sample describes only the window it was read in. Once its `resets_at` passes, `build_claude_usage_estimates` still reports the old remaining percentage and the past reset time as authoritative (`usage_source="oauth_usage"`, `confidence="oauth"`). An auth that had 2% weekly left before the weekly reset keeps showing 2% after the reset, on the quota panel, the accounts list, the dashboard overview, and the pooled `/api/oauth/usage` payload, until an OAuth fetch succeeds again.

The usage-queue fallback is wrong in the same case. It chains windows from the oldest retained event, so tokens spent before the reset still count against the new window.

## What Changes

- An OAuth bucket whose `resets_at` is at or before now is no longer used for that window's remaining percentage or reset time.
- For an expired window, the usage-queue estimate starts at the first successful event at or after the known reset. Events before the reset no longer count against the new window.
- When either bucket has expired, the auth reports `usage_source="usage_queue"` and `confidence="estimated"` (or `"unknown"` without a plan budget). The bucket that has not expired still supplies its OAuth percentage and reset time.
- Buckets without a `resets_at` are kept as before.

## Capabilities

### New Capabilities

- none

### Modified Capabilities

- `dashboard-sidecar-management`: retained OAuth usage stops being authoritative after its window resets.

## Impact

- Code: `app/modules/claude_sidecar/usage_estimates.py`
- Tests: `tests/unit/test_claude_sidecar_usage_estimates.py`, `tests/unit/test_claude_sidecar_oauth_usage_endpoint.py`, `tests/integration/test_claude_sidecar_dashboard_api.py`
- No API shape, schema, setting, or frontend changes
