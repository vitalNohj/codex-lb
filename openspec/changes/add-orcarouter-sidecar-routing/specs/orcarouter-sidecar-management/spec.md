## ADDED Requirements

### Requirement: Dashboard settings persist OrcaRouter configuration

The dashboard settings API MUST persist OrcaRouter enabled state, base URL, API key, model prefixes, full models, connect timeout, request timeout, models cache TTL, and default reasoning effort. Environment variables MAY seed first-run defaults. Once the dashboard settings row exists, runtime routing MUST use that row.

The API key MUST be encrypted at rest. Settings responses MUST expose whether a key is configured and MUST NOT return the raw key.

Default base URL MUST be `https://api.orcarouter.ai/v1`. New rows MUST seed prefixes `[{"prefix":"orcarouter/","strip":false}]` and MUST NOT seed `openai/`, `google/`, `anthropic/`, or `deepseek/`. Enabled MUST default to false.

#### Scenario: Save and reload OrcaRouter settings

- **GIVEN** an authenticated dashboard operator saves OrcaRouter settings
- **WHEN** the operator reloads `GET /api/settings`
- **THEN** the response includes the saved enabled state, base URL, prefixes, full models, timeouts, and cache TTL
- **AND** the response includes `orcarouter_sidecar_api_key_configured=true`
- **AND** the response does not include the raw API key

#### Scenario: Missing API key is reported without calling the network

- **GIVEN** OrcaRouter is enabled and no API key is stored
- **WHEN** the operator loads status or runs test-connection
- **THEN** the service does not call OrcaRouter
- **AND** the status is `missing_api_key`

### Requirement: Dashboard OrcaRouter health APIs

The dashboard MUST provide authenticated `GET /api/orcarouter-sidecar/status`, `POST /api/orcarouter-sidecar/test`, and `GET /api/orcarouter-sidecar/models`. Test-connection MUST call configured `/models` only when enabled and a key is present, and MUST classify disabled, missing_api_key, unreachable, unauthorized, healthy, or error.

Responses MUST NOT include the API key.

#### Scenario: Test connection succeeds

- **GIVEN** OrcaRouter is enabled with a base URL and API key
- **AND** OrcaRouter returns a valid `/models` response
- **WHEN** an operator calls `POST /api/orcarouter-sidecar/test`
- **THEN** the response reports `status: "healthy"`
- **AND** dashboard settings record the last check

### Requirement: Synthetic OrcaRouter account

When OrcaRouter configuration exists or is enabled, `GET /api/accounts` MUST include one synthetic read-only account with `account_id: "orcarouter-sidecar"`, `provider: "orcarouter"`, and display name `OrcaRouter`. The account MUST NOT be written to the `accounts` table.

The synthetic detail UI MUST have an explicit OrcaRouter branch. It MUST NOT show Claude pause or quota controls.

#### Scenario: Synthetic account appears

- **GIVEN** OrcaRouter settings are configured
- **WHEN** an operator calls `GET /api/accounts`
- **THEN** the response includes `account_id: "orcarouter-sidecar"`
- **AND** the account is `synthetic=true` and `read_only=true`
- **AND** `display_name` is `OrcaRouter`

### Requirement: Request logs identify OrcaRouter traffic

Request logs MUST use `source = "orcarouter_sidecar"` and `transport = "http"`. The dashboard MUST label those rows `OrcaRouter`. The UI label MUST NOT contain the word sidecar.

#### Scenario: OrcaRouter request log is understandable

- **GIVEN** a request log row has `source: "orcarouter_sidecar"`
- **WHEN** an operator views recent requests
- **THEN** the row shows the OrcaRouter model
- **AND** the account/provider label is `OrcaRouter`
- **AND** the transport label is HTTP

### Requirement: Prefix uniqueness includes OrcaRouter

Saving settings MUST reject a prefix or full model that another integration already owns, including OmniRoute `orcarouter/`.

#### Scenario: OmniRoute already owns orcarouter/

- **GIVEN** OmniRoute prefixes include `orcarouter/`
- **WHEN** an operator saves OrcaRouter prefixes that include `orcarouter/`
- **THEN** the API returns `sidecar_routing_conflict`
- **AND** the Settings UI tells the operator to remove the OmniRoute `orcarouter/` prefix before enabling OrcaRouter
