## 1. Mapper

- [x] 1.1 Add pure mapper module converting aggregate remaining % to Anthropic oauth usage JSON
- [x] 1.2 Unit-test utilization inversion, null buckets, and absence of account fields

## 2. Service assembly

- [x] 2.1 Add service method that loads snapshot/events/plans, excludes paused auths, builds aggregate, maps payload
- [x] 2.2 Honor hide_upstream_quota_from_api_keys by returning null buckets
- [x] 2.3 Unit-test paused exclusion and empty/disabled sidecar null response

## 3. HTTP route

- [x] 3.1 Mount GET /api/oauth/usage with validate_usage_api_key
- [x] 3.2 HTTP tests for 401 without key, 200 Anthropic body, hide-upstream nulls

## 4. Verify

- [x] 4.1 Run openspec validate add-anthropic-oauth-usage-endpoint --strict
- [x] 4.2 Run focused pytest for mapper/service/route
