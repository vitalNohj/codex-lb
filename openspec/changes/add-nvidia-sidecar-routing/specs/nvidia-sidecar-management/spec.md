## ADDED Requirements

### Requirement: Dashboard settings persist NVIDIA configuration

The dashboard settings API MUST persist NVIDIA enabled state, base URL, API key, model prefixes, full models, connect timeout, request timeout, models cache TTL, and default reasoning effort. Environment variables MAY seed first-run defaults. Once the dashboard settings row exists, runtime routing MUST use that row.

The API key MUST be encrypted at rest. Settings responses MUST expose whether a key is configured and MUST NOT return the raw key.

Default base URL MUST be `https://integrate.api.nvidia.com/v1`. New rows MUST seed an empty prefix list unless the operator configured `CODEX_LB_NVIDIA_SIDECAR_MODEL_PREFIXES`. Enabled MUST default to false.

#### Scenario: Save and reload NVIDIA settings

- **GIVEN** an authenticated dashboard operator saves NVIDIA settings
- **WHEN** the operator reloads `GET /api/settings`
- **THEN** the response includes the saved enabled state, base URL, prefixes, full models, timeouts, and cache TTL
- **AND** the response includes `nvidia_sidecar_api_key_configured=true`
- **AND** the response does not include the raw API key

#### Scenario: Missing API key is reported without calling the network

- **GIVEN** NVIDIA is enabled and no API key is stored
- **WHEN** the operator loads status or runs test-connection
- **THEN** the service does not call NVIDIA
- **AND** the status is `missing_api_key`

### Requirement: Dashboard NVIDIA health APIs

The dashboard MUST provide authenticated `GET /api/nvidia-sidecar/status`, `POST /api/nvidia-sidecar/test`, and `GET /api/nvidia-sidecar/models`. Test-connection MUST call configured `/models` only when enabled and a key is present, and MUST classify disabled, missing_api_key, unreachable, unauthorized, healthy, or error.

Responses MUST NOT include the API key.

#### Scenario: Test connection succeeds

- **GIVEN** NVIDIA is enabled with a base URL and API key
- **AND** NVIDIA returns a valid `/models` response
- **WHEN** an operator calls `POST /api/nvidia-sidecar/test`
- **THEN** the response reports `status: "healthy"`
- **AND** dashboard settings record the last check

#### Scenario: Discovered models come from NVIDIA /models

- **GIVEN** NVIDIA is enabled with an API key
- **AND** NVIDIA `/models` lists `z-ai/glm-5.3`
- **WHEN** an operator calls `GET /api/nvidia-sidecar/models`
- **THEN** the response includes `z-ai/glm-5.3`

### Requirement: Synthetic NVIDIA account

When NVIDIA configuration exists or is enabled, `GET /api/accounts` MUST include one synthetic read-only account with `account_id: "nvidia-sidecar"`, `provider: "nvidia"`, and display name `NVIDIA`. The account MUST NOT be written to the `accounts` table.

The synthetic detail UI MUST have an explicit NVIDIA branch. It MUST NOT show Claude pause or quota controls.

#### Scenario: Synthetic account appears

- **GIVEN** NVIDIA settings are configured
- **WHEN** an operator calls `GET /api/accounts`
- **THEN** the response includes `account_id: "nvidia-sidecar"`
- **AND** the account is `synthetic=true` and `read_only=true`
- **AND** `display_name` is `NVIDIA`

### Requirement: Request logs identify NVIDIA traffic

Request logs MUST use `source = "nvidia_sidecar"` and `transport = "http"`. The dashboard MUST label those rows `NVIDIA`. The UI label MUST NOT contain the word sidecar.

#### Scenario: NVIDIA request log is understandable

- **GIVEN** a request log row has `source: "nvidia_sidecar"`
- **WHEN** an operator views recent requests
- **THEN** the row shows the NVIDIA model
- **AND** the account/provider label is `NVIDIA`
- **AND** the transport label is HTTP

### Requirement: Prefix uniqueness includes NVIDIA

Saving settings MUST reject a prefix or full model that another integration already owns.

#### Scenario: OpenRouter already owns a pinned id

- **GIVEN** OpenRouter full models include `z-ai/glm-5.3`
- **WHEN** an operator saves NVIDIA full models that include `z-ai/glm-5.3`
- **THEN** the API returns `sidecar_routing_conflict`
