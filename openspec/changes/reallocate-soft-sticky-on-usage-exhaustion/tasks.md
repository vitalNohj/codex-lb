# Tasks

- [x] 1. Add `is_usage_exhaustion_code` next to the existing rate-limit / quota code
      sets in `app/modules/proxy/helpers.py` covering `usage_limit_reached` plus
      `_QUOTA_CODES`.
- [x] 2. In `_stream_with_retry`, skip dispatch-owner pinning when a pre-visible
      `ProxyResponseError` is usage exhaustion and the request is not hard-owned.
- [x] 3. On `failover_next` for that same class (pre-visible and post-refresh),
      exclude the failed account, clear the soft preferred pin, and set
      `reallocate_sticky=True` so the replacement mapping is persisted.
- [x] 4. Add a streaming regression: non-account-neutral first-turn payload,
      first account raises 429 `usage_limit_reached` before any yield, second
      account completes; assert exclusion, `reallocate_sticky`, and no client 429.
- [x] 5. Keep existing mid-stream `usage_limit_reached` and previous-response
      owner fail-closed tests green.
- [x] 6. Run focused pytest, ruff, and `openspec validate <change> --strict`.
