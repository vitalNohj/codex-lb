## ADDED Requirements

### Requirement: Dashboard settings persist Claude sidecar Management API key

The dashboard settings API MUST persist an optional CLIProxyAPI Management API key and a quota poll interval (seconds) on `dashboard_settings`, alongside the existing sidecar fields added by `add-claude-sidecar-routing`. The Management API key MUST be encrypted at rest. Dashboard settings responses MUST expose whether a Management API key is configured via a boolean flag and MUST NOT return the raw Management API key.

Operators MUST be able to clear a previously stored Management API key by sending a clear flag. The poll interval MUST be a positive number; the default value when unset MUST be 60 seconds.

The dashboard settings API MUST also persist Claude sidecar usage collection controls and per-auth plan budget settings. Usage collection controls MUST include whether collection is enabled, the usage queue polling interval in seconds, and the maximum queue batch size per drain request. Per-auth plan settings MUST be keyed by Claude auth identity, using `auth_index` when available and an email/source fallback when it is not. Each plan setting MUST support a `plan_type` of `pro`, `max5`, `max20`, or `custom`; custom plans MUST include explicit 5-hour and weekly token budgets.

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

#### Scenario: Save per-auth Claude plan settings

- **GIVEN** the dashboard has observed a Claude auth with `auth_index="auth-1"`
- **WHEN** an authenticated dashboard operator saves that auth with `plan_type="max5"` and explicit 5-hour and weekly token budgets
- **THEN** future settings responses include that auth plan entry
- **AND** the response does not include any CLIProxyAPI Management API secret

### Requirement: Background usage collector drains CLIProxyAPI usage telemetry

A background scheduler MUST drain CLIProxyAPI's `GET /v0/management/usage-queue` endpoint with the configured Management Bearer key. The collector MUST run only while Claude sidecar routing is enabled, a Management API key is configured, and usage collection is enabled. The collector MUST run on a single leader instance, MUST sleep for the configured usage collection interval between drain attempts, and MUST never raise an exception out of its loop.

The collector MUST treat `/usage-queue` as a destructive single-consumer queue. Dashboard request handlers MUST NOT call `/usage-queue` directly. The collector MUST persist sanitized usage records in codex-lb storage and MUST NOT persist the raw `api_key` field from CLIProxyAPI usage records.

Persisted records MUST include timestamp, request ID or generated idempotency key, auth index, source, provider, model, alias, endpoint, auth type, input tokens, output tokens, reasoning tokens, cached tokens, total tokens, failure flag, and latency. Duplicate queue records MUST NOT be double counted.

#### Scenario: Collector persists sanitized usage records

- **GIVEN** the sidecar is enabled, a Management API key is configured, and CLIProxyAPI returns one usage queue record with token counts and an `api_key`
- **WHEN** the collector drains the queue
- **THEN** codex-lb stores the token counts, auth identity, model, timestamp, and request ID
- **AND** codex-lb does not store the raw `api_key`

#### Scenario: Collector is gated off without configuration

- **GIVEN** the sidecar is enabled but no Management API key is configured
- **WHEN** the collector wakes up
- **THEN** no `/usage-queue` Management API call is made

#### Scenario: Collector survives malformed queue entries

- **GIVEN** CLIProxyAPI returns a batch containing one malformed usage queue record and one valid record
- **WHEN** the collector drains the batch
- **THEN** the malformed record is skipped
- **AND** the valid record is persisted
- **AND** the collector remains running

### Requirement: Estimated Claude usage derives from per-auth plan budgets

Codex-lb MUST calculate estimated Claude 5-hour and weekly usage percentages from persisted usage queue records and configured per-auth plan budgets. The estimate MUST use each auth's `total_tokens` values within the active 5-hour and weekly windows. If `total_tokens` is missing in a raw queue record, codex-lb MUST calculate it from input, output, reasoning, and cached token counts before persisting or estimating.

When the latest quota snapshot includes official OAuth usage percentages for an auth, codex-lb MUST prefer those percentages and reset timestamps over usage-queue-derived estimates for that auth. Usage-queue token totals MAY still be exposed for diagnostic context, but OAuth usage MUST set the source/confidence for that auth.

For each configured auth, codex-lb MUST calculate:

- active 5-hour window start and reset time
- active weekly window start and reset time
- 5-hour used tokens and configured token budget
- weekly used tokens and configured token budget
- 5-hour remaining percent
- weekly remaining percent
- confidence/status indicating whether the value came from OAuth usage, local estimates, or is unknown

When an auth has persisted usage but no configured plan budget, codex-lb MUST expose token totals but MUST leave percentage fields null. When CLIProxyAPI reports an auth as quota exceeded, codex-lb MUST clamp the relevant remaining estimate to `0` and preserve CLIProxyAPI's recovery time when present.

#### Scenario: Estimate usage for a configured auth

- **GIVEN** a Claude auth has `auth_index="auth-1"` and a configured 5-hour token budget of 1000
- **AND** codex-lb has persisted successful queue records totaling 250 tokens in the active 5-hour window
- **WHEN** an authenticated dashboard operator calls `GET /api/accounts`
- **THEN** the synthetic Claude account includes estimated 5-hour remaining percent of 75
- **AND** the matching `sidecar_auths` entry includes 250 used tokens and the 1000 token budget

#### Scenario: Missing plan leaves percent unknown

- **GIVEN** a Claude auth has persisted usage records
- **AND** no plan budget is configured for that auth
- **WHEN** an authenticated dashboard operator calls `GET /api/accounts`
- **THEN** the matching `sidecar_auths` entry includes token totals
- **AND** estimated percentage fields for that auth are null

#### Scenario: Hard quota state wins over estimate

- **GIVEN** a Claude auth has remaining tokens by estimate
- **AND** the latest auth-files snapshot reports `quota.exceeded=true`
- **WHEN** codex-lb builds the synthetic account
- **THEN** the account status reflects the hard quota state
- **AND** the affected remaining percent is clamped to 0

#### Scenario: OAuth usage wins over local estimate

- **GIVEN** the latest Claude auth snapshot includes OAuth usage with 57% 5-hour remaining and 82% weekly remaining
- **AND** codex-lb has persisted usage queue records that would otherwise estimate different percentages
- **WHEN** codex-lb builds the synthetic account
- **THEN** the matching `sidecar_auths` entry uses the OAuth remaining percentages and reset times
- **AND** the source/confidence indicates OAuth usage
- **AND** the aggregate synthetic account usage is populated from the OAuth percentages when no plan budgets are configured

### Requirement: Background quota poller refreshes the snapshot

A background scheduler MUST poll CLIProxyAPI's `GET /v0/management/auth-files` endpoint with the configured Management Bearer key. The poller MUST run only while Claude sidecar routing is enabled AND a Management API key is configured. The poller MUST run on a single leader instance, MUST sleep for the configured `claude_sidecar_quota_poll_interval_seconds` between polls, and MUST never raise an exception out of its loop.

On every successful poll, the service MUST store a normalized snapshot (per-auth records plus a timestamp) on `dashboard_settings` (`claude_sidecar_quota_state_json` and `claude_sidecar_quota_checked_at`) and MUST invalidate the cached settings so other services see the new snapshot. When a Claude auth-file entry includes a readable local file path containing a top-level `access_token`, the poller SHOULD query Anthropic's OAuth usage endpoint and store normalized remaining percentages plus reset timestamps on that auth's snapshot. The poller MUST NOT store the access token. OAuth usage failures MUST NOT prevent storing hard auth-files status. The snapshot status MUST be classified as one of:

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

#### Scenario: Poll enriches readable OAuth usage

- **GIVEN** the sidecar is enabled and a Management API key is configured
- **AND** CLIProxyAPI returns a Claude auth-file entry with a local path containing a top-level OAuth `access_token`
- **AND** Anthropic's OAuth usage endpoint returns five-hour and seven-day utilization buckets
- **WHEN** the poller runs
- **THEN** the stored auth snapshot includes normalized 5-hour and weekly remaining percentages and reset timestamps
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

### Requirement: Synthetic Claude sidecar account exposes quota state

When a quota snapshot is stored, the synthetic `claude-sidecar` account returned by `GET /api/accounts` MUST reflect the latest snapshot.

- The account `status` MUST be:
  - `paused` when the snapshot status is not `healthy` (unauthorized/unreachable/error).
  - `quota_exceeded` when at least one Claude auth exists and ALL Claude auths report `quota.exceeded=true`.
  - `rate_limited` when at least one but not all Claude auths report `quota.exceeded=true`.
  - `active` when no Claude auth reports `quota.exceeded=true` and the sidecar is otherwise healthy.
- `reset_at_primary` MUST be the earliest non-null `next_recover_at` value among exceeded auths, or `null` if no auth is exceeded.
- `last_refresh_at` MUST be the snapshot's `checked_at` timestamp.
- A new field `sidecar_auths` (list) MUST include one entry per Claude auth with `name`, `email`, `auth_index`, `status`, `quota_exceeded`, `next_recover_at`, `models_exceeded`, `success`, `failed`, plan metadata, token budgets, used tokens, remaining percentages, reset times, usage source, and confidence when available.
- When OAuth usage or plan-budget estimates are available, the synthetic account MUST populate standard `usage.primary_remaining_percent` and `usage.secondary_remaining_percent` with aggregate 5-hour and weekly remaining percentages across Claude auths.
- The synthetic account MUST set `window_minutes_primary=300` for the 5-hour usage value and `window_minutes_secondary=10080` for the weekly usage value when those values are present.

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

#### Scenario: Synthetic account exposes usage values

- **GIVEN** a stored snapshot has one Claude auth with OAuth usage or configured plan-budget estimates
- **WHEN** an authenticated dashboard operator calls `GET /api/accounts`
- **THEN** the synthetic account has non-null `usage.primary_remaining_percent`
- **AND** the synthetic account has non-null `usage.secondary_remaining_percent`
- **AND** the account remains `synthetic=true` and `read_only=true`

### Requirement: Dashboard overview includes the synthetic Claude sidecar account

`GET /api/dashboard/overview` MUST append the synthetic `claude-sidecar` account to its `accounts` list when the sidecar is configured or enabled. The synthetic account MUST be appended after Codex accounts are sorted so it always lands last and MUST NOT be included in Codex aggregate calculations such as average usage.

When the synthetic account has usage percentages, dashboard aggregate calculations such as usage donuts, weekly credit pace, and Codex account remaining totals MUST still exclude the synthetic account.

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

#### Scenario: Quota endpoint returns per-auth usage values

- **GIVEN** a stored snapshot exists with one healthy Claude auth
- **AND** OAuth usage or persisted usage queue records and plan budgets exist for that auth
- **WHEN** an authenticated dashboard operator calls `GET /api/claude-sidecar/quota`
- **THEN** the response account includes the auth's used token counts when available, token budgets when configured, remaining percentages, reset times, usage source, and confidence

#### Scenario: Quota endpoint when no snapshot exists

- **GIVEN** the sidecar has never been polled
- **WHEN** an authenticated dashboard operator calls `GET /api/claude-sidecar/quota`
- **THEN** the response `status` is `"unknown"`
- **AND** the response `accounts` array is empty
