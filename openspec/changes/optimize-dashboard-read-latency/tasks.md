## 1. Request-log filter options

- [x] 1.1 Wrap the baseline facet conditions in unary `+` on SQLite so each
      skip-scan probe seeks the facet column's index.
- [x] 1.2 Add a SQLite query-plan regression test that fails on the previous
      code (`deleted_at` index chosen) and passes with the fix.

## 2. Claude quota estimates

- [x] 2.1 Add the process-wide usage-event window cache with id-watermark
      appends, count/max-id fingerprint validation, full reload on mismatch,
      and a slack below the window for concurrent readers.
- [x] 2.2 Route the dashboard overview, accounts list, sidecar quota panel, and
      pooled OAuth usage through it; refresh it after each collector drain.
- [x] 2.3 Replace per-window history scans in the estimator with sorted arrays
      and bisection; verify identical output against the previous
      implementation on production data and fuzzed inputs.
- [x] 2.4 Integration tests for ordering, append-only fetches, slack reuse,
      reload after deletes, and clear; collector test for the refresh.

## 3. Summary and history caches

- [x] 3.1 Cache per-source request-usage summaries under the request-usage
      summary cache key space, sharing its TTL and invalidation; test it.
- [x] 3.2 Prune the SQLite bulk usage-history cache entry once the requested
      window slides past the prune slack; test pruning and continued
      correction detection.

## 4. Verification

- [x] 4.1 Ruff, format, architecture check, ty (no new diagnostics), and the
      dashboard/accounts/sidecar/request-log/usage test suites.
- [x] 4.2 Benchmark the dashboard page-load request sequence against a
      snapshot of the production store before and after.
- [ ] 4.3 Deploy to the shared instance and confirm the refresh in the
      browser.
