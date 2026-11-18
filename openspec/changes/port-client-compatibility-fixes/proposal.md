## Why

The dashboard uses the forwarded client address for proxy assertion trust, and several upstream client and plan identifiers are rejected or misinterpreted. The expired-limit sweep can stall after a guarded update misses.

## What changes

- Authenticate dashboard proxy assertions from the captured socket peer. Keep drain authorization, reachability, firewall defaults, and API-key requirements unchanged.
- Accept the encrypted output include selector, preserve the Chat Completions non-strict function default, and recognize current Pro-family plans.
- Page through expired API-key limits by ID without retrying guarded misses in the same sweep. Continue to exclude lifetime budgets.

## Impact

No new settings or data migration. The selected fixes come from https://github.com/Soju06/codex-lb/pull/2729.
