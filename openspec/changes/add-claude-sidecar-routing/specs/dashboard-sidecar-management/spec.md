## ADDED Requirements

### Requirement: Dashboard settings persist Claude sidecar configuration

The dashboard settings API MUST persist Claude sidecar enabled state, base URL, API key, model prefixes, connect timeout, request timeout, and model cache TTL in the database. Environment variables MAY provide first-run defaults, but once the dashboard settings row exists, runtime sidecar routing MUST use the dashboard settings row as the source of truth.

The sidecar API key MUST be encrypted at rest. Dashboard settings responses MUST expose whether a sidecar API key is configured and MUST NOT return the raw sidecar API key after save.

#### Scenario: Save and reload sidecar settings

- **GIVEN** an authenticated dashboard operator saves Claude sidecar settings
- **WHEN** the operator reloads `GET /api/settings`
- **THEN** the response includes the saved sidecar enabled state, base URL, model prefixes, timeouts, and model cache TTL
- **AND** the response includes `claude_sidecar_api_key_configured=true`
- **AND** the response does not include the raw sidecar API key

#### Scenario: Clear the stored sidecar API key

- **GIVEN** a sidecar API key is already configured
- **WHEN** an authenticated dashboard operator updates settings with a clear-key request
- **THEN** the stored sidecar API key is removed
- **AND** future settings responses include `claude_sidecar_api_key_configured=false`

### Requirement: Dashboard sidecar health APIs

The dashboard MUST provide authenticated sidecar status, test-connection, and model-list APIs. The test-connection API MUST call the configured CLIProxyAPI `/v1/models` endpoint and classify the result as disabled, missing API key, unreachable, unauthorized, healthy, or error.

The service MUST store the last sidecar health status, last check time, last model count, and last error message on dashboard settings. Dashboard sidecar APIs MUST NOT include the sidecar API key in responses or error messages.

#### Scenario: Test connection succeeds

- **GIVEN** the sidecar is enabled with a base URL and API key
- **AND** CLIProxyAPI returns a valid `/v1/models` response
- **WHEN** an authenticated dashboard operator calls `POST /api/claude-sidecar/test`
- **THEN** the response reports `status: "healthy"`
- **AND** the response includes the discovered model count
- **AND** dashboard settings record the successful last check

#### Scenario: Sidecar is unreachable

- **GIVEN** the sidecar is enabled with a base URL and API key
- **AND** CLIProxyAPI is unreachable
- **WHEN** an authenticated dashboard operator calls `POST /api/claude-sidecar/test`
- **THEN** the response reports `status: "unreachable"`
- **AND** dashboard settings record the failed last check without exposing the API key

### Requirement: Accounts dashboard shows a synthetic Claude sidecar account

When sidecar configuration exists or the sidecar is enabled, `GET /api/accounts` MUST include one synthetic read-only account representing Claude via CLIProxyAPI. The synthetic account MUST NOT be written to the `accounts` table and MUST NOT be eligible for Codex account selection, warmup, pause, delete, auth export, alias update, or API-key account assignment flows.

The synthetic account MUST show health status, health message, configured base URL, model count, last check time, and request usage derived from request logs where `source = "claude_sidecar"`.

#### Scenario: Synthetic account appears

- **GIVEN** Claude sidecar settings are configured
- **WHEN** an authenticated dashboard operator calls `GET /api/accounts`
- **THEN** the response includes an account with `account_id: "claude-sidecar"`
- **AND** the account is marked `synthetic=true` and `read_only=true`
- **AND** destructive account actions are not available for that account in the dashboard UI

### Requirement: Dashboard model controls include sidecar models

When Claude sidecar routing is enabled, dashboard `GET /api/models` MUST include sidecar model IDs returned by CLIProxyAPI in addition to public Codex models. The endpoint MUST return Codex models even if sidecar model lookup fails. Dashboard `/backend-api/codex/models` behavior MUST remain Codex-only.

#### Scenario: API-key model picker can select Claude models

- **GIVEN** Claude sidecar routing is enabled
- **AND** CLIProxyAPI returns `claude-sonnet-4-5-20250929`
- **WHEN** the API-key model picker loads models from `GET /api/models`
- **THEN** the returned models include `claude-sonnet-4-5-20250929`
- **AND** operators can select that model for allowlists or enforced-model settings

### Requirement: Request logs identify sidecar traffic

Dashboard request logs MUST visibly identify rows where `source = "claude_sidecar"`. When a sidecar request has no Codex account ID, the dashboard MUST display the account/provider as Claude sidecar rather than an empty account.

#### Scenario: Sidecar request log is understandable

- **GIVEN** a request log row has `source: "claude_sidecar"` and no account ID
- **WHEN** an authenticated dashboard operator views recent requests
- **THEN** the row shows the Claude model
- **AND** the row visibly identifies the source/provider as Claude sidecar
- **AND** the request detail view includes the sidecar source
