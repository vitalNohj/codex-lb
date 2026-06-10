## ADDED Requirements

### Requirement: Dashboard settings persist Claude sidecar Management API key

The dashboard settings API MUST persist an optional CLIProxyAPI Management API key and a quota poll interval (seconds) on `dashboard_settings`, alongside the existing sidecar fields added by `add-claude-sidecar-routing`. The Management API key MUST be encrypted at rest. Dashboard settings responses MUST expose whether a Management API key is configured via a boolean flag and MUST NOT return the raw Management API key.

Operators MUST be able to clear a previously stored Management API key by sending a clear flag. The poll interval MUST be a positive number; the default value when unset MUST be 60 seconds.

#### Scenario: Save and reload Management key configuration

- **GIVEN** an authenticated dashboard operator saves a Claude sidecar Management API key and a poll interval of 90 seconds
- **WHEN** the operator reloads `GET /api/settings`
- **THEN** the response includes `claude_sidecar_management_key_configured=true`
- **AND** the response includes `claude_sidecar_quota_poll_interval_seconds=90`
- **AND** the response does not include the raw Management API key

#### Scenario: Clear the stored Management API key

- **GIVEN** a Claude sidecar Management API key is already configured
- **WHEN** an authenticated dashboard operator updates settings with a clear-Management-key request
- **THEN** the stored Management API key is removed
- **AND** future settings responses include `claude_sidecar_management_key_configured=false`

### Requirement: Background quota poller refreshes the snapshot

A background scheduler MUST poll CLIProxyAPI's `GET /v0/management/auth-files` endpoint with the configured Management Bearer key. The poller MUST run only while Claude sidecar routing is enabled AND a Management API key is configured. The poller MUST run on a single leader instance, MUST sleep for the configured `claude_sidecar_quota_poll_interval_seconds` between polls, and MUST never raise an exception out of its loop.

On every successful poll, the service MUST store a normalized snapshot (per-auth records plus a timestamp) on `dashboard_settings` (`claude_sidecar_quota_state_json` and `claude_sidecar_quota_checked_at`) and MUST invalidate the cached settings so other services see the new snapshot. The snapshot status MUST be classified as one of:

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

### Requirement: Synthetic Claude sidecar account exposes quota state

When a quota snapshot is stored, the synthetic `claude-sidecar` account returned by `GET /api/accounts` MUST reflect the latest snapshot.

- The account `status` MUST be:
  - `paused` when the snapshot status is not `healthy` (unauthorized/unreachable/error).
  - `quota_exceeded` when at least one Claude auth exists and ALL Claude auths report `quota.exceeded=true`.
  - `rate_limited` when at least one but not all Claude auths report `quota.exceeded=true`.
  - `active` when no Claude auth reports `quota.exceeded=true` and the sidecar is otherwise healthy.
- `reset_at_primary` MUST be the earliest non-null `next_recover_at` value among exceeded auths, or `null` if no auth is exceeded.
- `last_refresh_at` MUST be the snapshot's `checked_at` timestamp.
- A new field `sidecar_auths` (list) MUST include one entry per Claude auth with `name`, `email`, `status`, `quota_exceeded`, `next_recover_at`, `models_exceeded`, `success`, `failed`.

The synthetic account MUST remain read-only and MUST NOT be written to the `accounts` table.

#### Scenario: Some auths exceeded sets rate_limited

- **GIVEN** a stored snapshot has two Claude auths and exactly one reports `quota.exceeded=true` with `next_recover_at` set to 5 minutes from now
- **WHEN** an authenticated dashboard operator calls `GET /api/accounts`
- **THEN** the synthetic account `status` is `rate_limited`
- **AND** `reset_at_primary` equals the exceeded auth's `next_recover_at`
- **AND** `sidecar_auths` contains two entries with the exceeded auth's `quota_exceeded=true`

#### Scenario: All auths exceeded sets quota_exceeded

- **GIVEN** a stored snapshot has one Claude auth and that auth reports `quota.exceeded=true`
- **WHEN** an authenticated dashboard operator calls `GET /api/accounts`
- **THEN** the synthetic account `status` is `quota_exceeded`
- **AND** `reset_at_primary` equals the auth's `next_recover_at`

### Requirement: Dashboard overview includes the synthetic Claude sidecar account

`GET /api/dashboard/overview` MUST append the synthetic `claude-sidecar` account to its `accounts` list when the sidecar is configured or enabled. The synthetic account MUST be appended after Codex accounts are sorted so it always lands last and MUST NOT be included in Codex aggregate calculations such as average usage.

#### Scenario: Synthetic account appears in overview when configured

- **GIVEN** Claude sidecar configuration exists
- **WHEN** an authenticated dashboard operator calls `GET /api/dashboard/overview`
- **THEN** the response `accounts` array contains an entry with `account_id="claude-sidecar"` and `synthetic=true`
- **AND** that entry is positioned after all Codex accounts

### Requirement: Dashboard quota endpoint exposes the snapshot

The dashboard MUST provide an authenticated `GET /api/claude-sidecar/quota` endpoint returning the latest stored snapshot, including `status`, `checked_at`, an optional human-readable `message`, and a list of `accounts` matching the `sidecar_auths` shape used by `GET /api/accounts`. The endpoint MUST NOT include the Management API key in the response.

#### Scenario: Quota endpoint returns the stored snapshot

- **GIVEN** a stored snapshot exists with one healthy Claude auth
- **WHEN** an authenticated dashboard operator calls `GET /api/claude-sidecar/quota`
- **THEN** the response has `status="healthy"` and `checked_at` set
- **AND** the response `accounts` array contains the auth's `email`, `quota_exceeded=false`, and `next_recover_at=null`

#### Scenario: Quota endpoint when no snapshot exists

- **GIVEN** the sidecar has never been polled
- **WHEN** an authenticated dashboard operator calls `GET /api/claude-sidecar/quota`
- **THEN** the response `status` is `"unknown"`
- **AND** the response `accounts` array is empty
