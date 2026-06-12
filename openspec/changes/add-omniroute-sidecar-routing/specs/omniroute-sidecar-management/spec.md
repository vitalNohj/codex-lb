## ADDED Requirements

### Requirement: Dashboard settings persist OmniRoute sidecar configuration

The dashboard settings API MUST persist OmniRoute sidecar enabled state, base URL, API key, selected model IDs, connect timeout, request timeout, and model cache TTL in the database. Environment variables MAY provide first-run defaults, but once the dashboard settings row exists, runtime OmniRoute sidecar routing MUST use the dashboard settings row as the source of truth.

The OmniRoute sidecar API key MUST be encrypted at rest. Dashboard settings responses MUST expose whether an OmniRoute sidecar API key is configured and MUST NOT return the raw OmniRoute sidecar API key after save.

#### Scenario: Save and reload OmniRoute sidecar settings

- **GIVEN** an authenticated dashboard operator saves OmniRoute sidecar settings
- **WHEN** the operator reloads `GET /api/settings`
- **THEN** the response includes the saved OmniRoute sidecar enabled state, base URL, selected model IDs, timeouts, and model cache TTL
- **AND** the response includes `omniroute_sidecar_api_key_configured=true`
- **AND** the response does not include the raw OmniRoute sidecar API key

#### Scenario: Clear the stored OmniRoute sidecar API key

- **GIVEN** an OmniRoute sidecar API key is already configured
- **WHEN** an authenticated dashboard operator updates settings with a clear-key request
- **THEN** the stored OmniRoute sidecar API key is removed
- **AND** future settings responses include `omniroute_sidecar_api_key_configured=false`

### Requirement: Dashboard OmniRoute sidecar health APIs

The dashboard MUST provide authenticated OmniRoute sidecar status, test-connection, and model-list APIs. The test-connection API MUST call the configured OmniRoute `/models` endpoint and classify the result as disabled, missing API key, unreachable, unauthorized, healthy, or error.

The service MUST store the last OmniRoute sidecar health status, last check time, last model count, and last error message on dashboard settings. Dashboard OmniRoute sidecar APIs MUST NOT include the OmniRoute sidecar API key in responses or error messages.

#### Scenario: OmniRoute test connection succeeds

- **GIVEN** the OmniRoute sidecar is enabled with a base URL and API key
- **AND** OmniRoute returns a valid `/models` response
- **WHEN** an authenticated dashboard operator calls `POST /api/omniroute-sidecar/test`
- **THEN** the response reports `status: "healthy"`
- **AND** the response includes the discovered model count
- **AND** dashboard settings record the successful last check

### Requirement: Accounts dashboard shows a synthetic OmniRoute sidecar account

When OmniRoute sidecar configuration exists or the sidecar is enabled, `GET /api/accounts` MUST include one synthetic read-only account representing OmniRoute. The synthetic account MUST NOT be written to the `accounts` table and MUST NOT be eligible for Codex account selection, warmup, pause, delete, auth export, alias update, or API-key account assignment flows.

The synthetic account MUST show health status, health message, configured base URL, model count, last check time, and request usage derived from request logs where `source = "omniroute_sidecar"`.

#### Scenario: Synthetic OmniRoute account appears

- **GIVEN** OmniRoute sidecar settings are configured
- **WHEN** an authenticated dashboard operator calls `GET /api/accounts`
- **THEN** the response includes an account with `account_id: "omniroute-sidecar"`
- **AND** the account is marked `synthetic=true` and `read_only=true`

### Requirement: Dashboard model controls include OmniRoute sidecar models

When OmniRoute sidecar routing is enabled, dashboard `GET /api/models` MUST include the configured selected OmniRoute model IDs in addition to public Codex models. The endpoint MUST return Codex models even if OmniRoute model discovery fails.

#### Scenario: API-key model picker can select OmniRoute models

- **GIVEN** OmniRoute sidecar routing is enabled
- **AND** the selected OmniRoute model list includes `my-selected-model`
- **WHEN** the API-key model picker loads models from `GET /api/models`
- **THEN** the returned models include `my-selected-model`

### Requirement: Settings UI exposes the OmniRoute sidecar card

The dashboard Settings page MUST surface a dedicated OmniRoute Sidecar card labeled `OmniRoute Sidecar`. The card MUST let an authenticated operator save and clear the OmniRoute sidecar API key, edit the base URL, manage the selected model ID list, run a test connection, view current health, and open the existing `/omni` reverse-proxy dashboard.

The selected model controls MUST allow adding and removing exact model IDs returned by `GET /api/omniroute-sidecar/models` and MUST allow adding a manually entered model ID that OmniRoute did not return.

#### Scenario: Operator opens OmniRoute from the settings card

- **GIVEN** an authenticated dashboard operator is on the Settings page
- **WHEN** the operator activates the OmniRoute Sidecar card's `Open OmniRoute` link
- **THEN** the operator is navigated to the existing `/omni` reverse-proxy dashboard

### Requirement: Request logs identify OmniRoute sidecar traffic

Dashboard request logs MUST visibly identify rows where `source = "omniroute_sidecar"`. When an OmniRoute sidecar request has no Codex account ID, the dashboard MUST display the account/provider as OmniRoute sidecar rather than an empty account.

#### Scenario: OmniRoute sidecar request log is understandable

- **GIVEN** a request log row has `source: "omniroute_sidecar"` and no account ID
- **WHEN** an authenticated dashboard operator views recent requests
- **THEN** the row shows the OmniRoute model
- **AND** the row visibly identifies the source/provider as OmniRoute sidecar
