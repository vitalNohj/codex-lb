## 1. Estimates

- [x] 1.1 Treat an OAuth bucket whose `resets_at` has passed as expired: skip its remaining percentage and reset time
- [x] 1.2 Start the expired window's usage-queue estimate at the first successful event at or after the reset (`_active_window_start(..., not_before=...)`)
- [x] 1.3 Report `usage_source="usage_queue"` and a non-OAuth confidence when either bucket has expired

## 2. Verification

- [x] 2.1 Unit tests: expired weekly bucket ignores pre-reset events (aware, naive, and exact-now reset times); expired bucket without new usage reports a full window; expired bucket without a budget stays null; buckets without `resets_at` are kept
- [x] 2.2 Integration test: with OAuth usage fetches rate-limited across polls, the quota endpoint, `/api/accounts`, and `/api/dashboard/overview` report the post-reset estimate
- [x] 2.3 The new tests fail on `main` and pass with the change
