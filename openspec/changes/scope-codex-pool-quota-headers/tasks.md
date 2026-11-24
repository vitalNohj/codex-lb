## 1. HTTP proxy responses

- [x] Confirm both failing bridge responses before changing them.
- [x] Scope and aggregate Codex usage headers by the eligible pool.
- [x] Separate a retryable account rejection from confirmed pool exhaustion.
- [x] Add regressions for failover, short retry, a missing short-window sample, sidecar isolation, and the earliest pool reset.
- [x] Match the full pool header deadline to the first returning account's blocking window.
- [x] Suppress full pool headers for ready automatic reset credits and streams with an unknown terminal outcome.
- [x] Add regressions for mixed windows, reset credits, and transient stream failures.
