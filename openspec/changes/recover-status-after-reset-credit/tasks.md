# Tasks

## 1. Specs

- [x] 1.1 Delta for `rate-limit-reset-credits`: successful consume recovers blocked status from post-reset usage.
- [x] 1.2 Delta for `account-routing`: reset-credit consume may recover before a persisted 429 deadline.

## 2. Recovery

- [x] 2.1 Thread `ignore_persisted_cooldown` through forced usage refresh into quota-status recovery.
- [x] 2.2 Pass that flag from dashboard, v1, Codex-identity, and auto-redeem reset-credit consume paths.
- [x] 2.3 Keep periodic refresh cooldown-gated.

## 3. Tests

- [x] 3.1 Recover a Plus `rate_limited` row with a future weekly deadline when post-reset usage is available.
- [x] 3.2 Keep `rate_limited` when the post-reset weekly window is still exhausted.
- [x] 3.3 Prove consume/refresh call sites pass `ignore_persisted_cooldown=True`.
