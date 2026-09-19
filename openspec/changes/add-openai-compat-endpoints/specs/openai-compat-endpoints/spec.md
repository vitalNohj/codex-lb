## ADDED Requirements

### Requirement: Dashboard settings persist a list of OpenAI-compat endpoints

The dashboard settings API MUST persist `openaiCompatEndpoints` as an ordered list (default empty, maximum 32). Each item MUST include id, name, enabled, base URL, prefixes, full models, timeouts, cache TTL, and default reasoning effort.

API keys MUST be encrypted at rest inside the JSON blob. Settings responses MUST expose whether a key is configured per endpoint and MUST NOT return the raw key. API keys MAY be absent; chat and `/models` MUST still run without an `Authorization` header.

Names MUST be unique case-insensitively. Base URLs MUST be http(s). Runtime routing MUST use the dashboard settings row.

#### Scenario: Save and reload a named endpoint

- **GIVEN** an authenticated dashboard operator saves an endpoint named `Vast` with base URL `https://openai.vast.ai/my-endpoint/v1`
- **WHEN** the operator reloads `GET /api/settings`
- **THEN** the response includes that endpoint's name, base URL, enabled state, prefixes, full models, timeouts, and cache TTL
- **AND** the response includes `apiKeyConfigured` for that endpoint
- **AND** the response does not include the raw API key

#### Scenario: Missing API key does not block status

- **GIVEN** an endpoint is enabled with a base URL and no API key
- **WHEN** the operator loads status or runs test-connection
- **THEN** the service still calls `{base}/models`
- **AND** the status is not `missing_api_key` solely because no key is stored

### Requirement: Dashboard OpenAI-compat health APIs

The dashboard MUST provide authenticated `GET /api/openai-compat/{endpoint_id}/status`, `POST /api/openai-compat/{endpoint_id}/test`, and `GET /api/openai-compat/{endpoint_id}/models`. Unknown ids MUST return 404. Test-connection MUST classify disabled, unreachable, unauthorized, healthy, or error.

Responses MUST NOT include the API key.

#### Scenario: Test connection succeeds

- **GIVEN** the endpoint is enabled with a reachable `/models`
- **WHEN** an operator calls `POST /api/openai-compat/{id}/test`
- **THEN** the response reports `status: "healthy"`
- **AND** dashboard settings record the last check on that endpoint without bumping settings version

#### Scenario: Discovered models come from the endpoint /models

- **GIVEN** the endpoint is enabled
- **AND** `{base}/models` lists `Qwen/Qwen2.5-7B`
- **WHEN** an operator calls `GET /api/openai-compat/{id}/models`
- **THEN** the response includes `Qwen/Qwen2.5-7B`

### Requirement: Synthetic account per endpoint

When an endpoint exists in the list, `GET /api/accounts` MUST include one synthetic read-only account with `account_id: "openai-compat-{uuid}"`, `provider: "openai_compat"`, and `display_name` equal to the operator name. The account MUST NOT be written to the `accounts` table.

The synthetic detail UI MUST have an explicit `openai_compat` branch. It MUST NOT show Claude pause or quota controls.

#### Scenario: Synthetic account appears

- **GIVEN** settings include an endpoint named `Vast`
- **WHEN** an operator calls `GET /api/accounts`
- **THEN** the response includes `account_id` `openai-compat-{that uuid}`
- **AND** the account is `synthetic=true` and `read_only=true`
- **AND** `display_name` is `Vast`

### Requirement: Request logs identify generic OpenAI-compat traffic

Request logs MUST use `source = "openai_compat:{uuid}"` and `transport = "http"`. The dashboard MUST label those rows with the operator endpoint name. The UI label MUST NOT contain the word sidecar.

#### Scenario: Generic request log is understandable

- **GIVEN** a request log row has `source: "openai_compat:{uuid}"` for an endpoint named `Vast`
- **WHEN** an operator views recent requests
- **THEN** the row shows the requested model
- **AND** the account/provider label is `Vast`
- **AND** the transport label is HTTP

### Requirement: Prefix uniqueness includes generic endpoints

Saving settings MUST reject a prefix or full model that another integration or another generic endpoint already owns. The conflict owner label MUST be the first-class integration name or the generic endpoint's operator name.

#### Scenario: OpenRouter already owns a pinned id

- **GIVEN** OpenRouter full models include `z-ai/glm-5.3`
- **WHEN** an operator saves a generic endpoint whose full models include `z-ai/glm-5.3`
- **THEN** the API returns `sidecar_routing_conflict`
