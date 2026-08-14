## ADDED Requirements

### Requirement: GET /api/oauth/usage returns Anthropic-shaped Claude pool utilization

The system MUST expose `GET /api/oauth/usage` that returns Anthropic OAuth usage JSON for a single pooled Claude estimate across non-paused Claude auths, without revealing account identity.

The success response MUST be HTTP 200 with exactly these top-level keys: `five_hour`, `seven_day`, `seven_day_opus`, `seven_day_sonnet`, `extra_usage`.

When a window estimate exists, `five_hour` and `seven_day` MUST be objects with:
- `utilization` (float): used percent in `[0, 100]` derived as `100 - remaining_percent` from the existing Claude usage aggregate (rounded to one decimal)
- `resets_at` (string or null): ISO-8601 UTC reset time from the aggregate, or null when unknown

When a window estimate does not exist, that bucket MUST be JSON `null`.

`seven_day_opus`, `seven_day_sonnet`, and `extra_usage` MUST be JSON `null`.

The response MUST NOT include account names, emails, auth indexes, plan types, token budgets, confidence, or per-auth arrays.

Paused/disabled Claude auths MUST be excluded from the pool. The endpoint MUST NOT call Anthropic live; it MUST read the polled quota snapshot and local usage estimates.

When the Claude sidecar is disabled, not configured, or has no usable estimate, the endpoint MUST still return HTTP 200 with `five_hour` and `seven_day` set to `null` (and the other keys `null`).

When `hide_upstream_quota_from_api_keys` is enabled, the endpoint MUST return HTTP 200 with `five_hour` and `seven_day` set to `null`.

#### Scenario: Pooled utilization for active Claude auths

- **WHEN** a valid API key calls `GET /api/oauth/usage`
- **AND** the pooled Claude aggregate has primary remaining 67.0% and secondary remaining 87.0%
- **THEN** the response is 200 with `five_hour.utilization` equal to 33.0 and `seven_day.utilization` equal to 13.0
- **AND** `seven_day_opus`, `seven_day_sonnet`, and `extra_usage` are null

#### Scenario: Paused auths excluded from pool

- **WHEN** a valid API key calls `GET /api/oauth/usage`
- **AND** one Claude auth is paused/disabled and another is active with remaining utilization data
- **THEN** the pooled `five_hour` / `seven_day` values are computed from the active auth only

#### Scenario: No Claude estimate available

- **WHEN** a valid API key calls `GET /api/oauth/usage`
- **AND** the Claude sidecar is disabled or no quota snapshot/estimate exists
- **THEN** the response is 200 with `five_hour` and `seven_day` null

#### Scenario: Upstream quota hidden from API keys

- **WHEN** a valid API key calls `GET /api/oauth/usage`
- **AND** `hide_upstream_quota_from_api_keys` is enabled
- **THEN** the response is 200 with `five_hour` and `seven_day` null

### Requirement: GET /api/oauth/usage requires a Bearer API key

The system MUST require a valid Bearer API key for `GET /api/oauth/usage` even when global API key auth is disabled, using the same always-required auth dependency as `GET /v1/usage`.

Missing or invalid credentials MUST fail with the existing proxy authentication error envelope (not an Anthropic-shaped error body).

#### Scenario: Missing API key rejected

- **WHEN** a client calls `GET /api/oauth/usage` without an Authorization Bearer token
- **THEN** the response is 401 using the proxy auth error format
