## ADDED Requirements

### Requirement: Dashboard settings persist OpenRouter sidecar configuration

The dashboard settings API MUST persist OpenRouter sidecar enabled state, base URL, API key, model prefixes, connect timeout, request timeout, and model cache TTL in the database. Environment variables MAY provide first-run defaults, but once the dashboard settings row exists, runtime OpenRouter sidecar routing MUST use the dashboard settings row as the source of truth.

The OpenRouter sidecar API key MUST be encrypted at rest. Dashboard settings responses MUST expose whether an OpenRouter sidecar API key is configured and MUST NOT return the raw OpenRouter sidecar API key after save.

#### Scenario: Save and reload OpenRouter sidecar settings

- **GIVEN** an authenticated dashboard operator saves OpenRouter sidecar settings
- **WHEN** the operator reloads `GET /api/settings`
- **THEN** the response includes the saved OpenRouter sidecar enabled state, base URL, model prefixes, timeouts, and model cache TTL
- **AND** the response includes `openrouter_sidecar_api_key_configured=true`
- **AND** the response does not include the raw OpenRouter sidecar API key

#### Scenario: Clear the stored OpenRouter sidecar API key

- **GIVEN** an OpenRouter sidecar API key is already configured
- **WHEN** an authenticated dashboard operator updates settings with a clear-key request
- **THEN** the stored OpenRouter sidecar API key is removed
- **AND** future settings responses include `openrouter_sidecar_api_key_configured=false`

### Requirement: Dashboard OpenRouter sidecar health APIs

The dashboard MUST provide authenticated OpenRouter sidecar status, test-connection, and model-list APIs. The test-connection API MUST call the configured OpenRouter `/v1/models` endpoint and classify the result as disabled, missing API key, unreachable, unauthorized, healthy, or error.

The service MUST store the last OpenRouter sidecar health status, last check time, last model count, and last error message on dashboard settings. Dashboard OpenRouter sidecar APIs MUST NOT include the OpenRouter sidecar API key in responses or error messages.

#### Scenario: OpenRouter test connection succeeds

- **GIVEN** the OpenRouter sidecar is enabled with a base URL and API key
- **AND** OpenRouter returns a valid `/v1/models` response
- **WHEN** an authenticated dashboard operator calls `POST /api/openrouter-sidecar/test`
- **THEN** the response reports `status: "healthy"`
- **AND** the response includes the discovered model count
- **AND** dashboard settings record the successful last check

### Requirement: Accounts dashboard shows a synthetic OpenRouter sidecar account

When OpenRouter sidecar configuration exists or the sidecar is enabled, `GET /api/accounts` MUST include one synthetic read-only account representing OpenRouter. The synthetic account MUST NOT be written to the `accounts` table and MUST NOT be eligible for Codex account selection, warmup, pause, delete, auth export, alias update, or API-key account assignment flows.

The synthetic account MUST show health status, health message, configured base URL, model count, last check time, and request usage derived from request logs where `source = "openrouter_sidecar"`.

#### Scenario: Synthetic OpenRouter account appears

- **GIVEN** OpenRouter sidecar settings are configured
- **WHEN** an authenticated dashboard operator calls `GET /api/accounts`
- **THEN** the response includes an account with `account_id: "openrouter-sidecar"`
- **AND** the account is marked `synthetic=true` and `read_only=true`

### Requirement: Dashboard model controls include OpenRouter sidecar models

When OpenRouter sidecar routing is enabled, dashboard `GET /api/models` MUST include OpenRouter model IDs returned by OpenRouter in addition to public Codex models. The endpoint MUST return Codex models even if OpenRouter model lookup fails.

#### Scenario: API-key model picker can select OpenRouter models

- **GIVEN** OpenRouter sidecar routing is enabled
- **AND** OpenRouter returns `deepseek/deepseek-chat`
- **WHEN** the API-key model picker loads models from `GET /api/models`
- **THEN** the returned models include `deepseek/deepseek-chat`

### Requirement: Request logs identify OpenRouter sidecar traffic

Dashboard request logs MUST visibly identify rows where `source = "openrouter_sidecar"`. When an OpenRouter sidecar request has no Codex account ID, the dashboard MUST display the account/provider as OpenRouter sidecar rather than an empty account.

#### Scenario: OpenRouter sidecar request log is understandable

- **GIVEN** a request log row has `source: "openrouter_sidecar"` and no account ID
- **WHEN** an authenticated dashboard operator views recent requests
- **THEN** the row shows the OpenRouter model
- **AND** the row visibly identifies the source/provider as OpenRouter sidecar
