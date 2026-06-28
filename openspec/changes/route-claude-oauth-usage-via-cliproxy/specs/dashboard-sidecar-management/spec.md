# dashboard-sidecar-management (delta)

## MODIFIED Requirements

### Requirement: Background quota poller refreshes the snapshot

A background scheduler MUST poll CLIProxyAPI's `GET /v0/management/auth-files` endpoint with the configured Management Bearer key. The poller MUST run only while Claude sidecar routing is enabled AND a Management API key is configured. The poller MUST run on a single leader instance, MUST sleep for the configured `claude_sidecar_quota_poll_interval_seconds` between polls, and MUST never raise an exception out of its loop.

On every successful poll, the service MUST store a normalized snapshot (per-auth records plus a timestamp) on `dashboard_settings` (`claude_sidecar_quota_state_json` and `claude_sidecar_quota_checked_at`) and MUST invalidate the cached settings so other services see the new snapshot.

When a Claude auth-file entry includes an `auth_index`, the poller SHOULD fetch Anthropic's OAuth usage through CLIProxyAPI's `POST /v0/management/api-call` passthrough using that `auth_index`, sending `Authorization: Bearer $TOKEN$` and `anthropic-beta: oauth-2025-04-20` so CLIProxyAPI substitutes the account token and routes the request through the account's configured proxy. codex-lb MUST NOT read credential files, MUST NOT call Anthropic directly, and MUST NOT store the access token. OAuth usage failures MUST NOT prevent storing hard auth-files status. The snapshot status MUST be classified as one of:

- `healthy` when the Management API returns a parseable response.
- `unauthorized` when the Management API returns HTTP 401 or 403.
- `unreachable` when the HTTP transport fails (connection refused, DNS, timeout).
- `error` for any other failure.

#### Scenario: Poll succeeds and writes a healthy snapshot

- **GIVEN** the sidecar is enabled and a Management API key is configured
- **AND** CLIProxyAPI returns a valid `/v0/management/auth-files` response with one Claude entry that is not exceeded
- **WHEN** the poller runs
- **THEN** `dashboard_settings.claude_sidecar_quota_state_json` contains a snapshot with `status="healthy"` and one account
- **AND** `dashboard_settings.claude_sidecar_quota_checked_at` is set to the poll time

#### Scenario: Poll enriches OAuth usage through CLIProxyAPI

- **GIVEN** the sidecar is enabled and a Management API key is configured
- **AND** CLIProxyAPI returns a Claude auth-file entry with an `auth_index`
- **WHEN** the poller runs and issues `POST /v0/management/api-call` with `auth_index`, `Authorization: Bearer $TOKEN$`, and `anthropic-beta: oauth-2025-04-20` against the Anthropic OAuth usage URL
- **AND** CLIProxyAPI returns five-hour and seven-day utilization buckets in the wrapped body
- **THEN** the stored auth snapshot includes normalized 5-hour and weekly remaining percentages and reset timestamps
- **AND** codex-lb never reads the credential file nor calls Anthropic directly
- **AND** the stored snapshot does not include the OAuth access token

#### Scenario: Poll classifies unauthorized

- **GIVEN** the sidecar is enabled and a Management API key is configured
- **AND** CLIProxyAPI returns HTTP 401 for `/v0/management/auth-files`
- **WHEN** the poller runs
- **THEN** the stored snapshot status is `unauthorized`
- **AND** the snapshot includes no per-auth entries

#### Scenario: Poller is gated off without configuration

- **GIVEN** the sidecar is enabled but no Management API key is configured
- **WHEN** the poller wakes up
- **THEN** no Management API call is made
- **AND** any previously stored snapshot is left unchanged
