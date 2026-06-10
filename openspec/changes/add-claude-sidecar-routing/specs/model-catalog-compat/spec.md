## MODIFIED Requirements

### Requirement: OpenAI-compatible model catalog includes configured sidecar models

When Claude sidecar routing is enabled, `GET /v1/models` MUST include models returned by the configured CLIProxyAPI sidecar `/v1/models` endpoint in addition to the existing Codex model catalog. Sidecar model entries MUST use the sidecar model `id` unchanged, MUST be marked as owned by `anthropic`, and MUST advertise chat-completions support.

The service MUST apply the same authenticated API-key `allowed_models` and `enforced_model` filtering to sidecar model entries that it applies to existing `/v1/models` entries. If a sidecar model ID duplicates an existing Codex model ID, the existing Codex model entry MUST win and the duplicate sidecar entry MUST be skipped.

`GET /backend-api/codex/models` MUST remain Codex-only and MUST NOT include sidecar models.

#### Scenario: OpenAI-compatible models include Claude entries

- **GIVEN** `claude_sidecar_enabled=true`
- **AND** the sidecar `/v1/models` response includes `claude-sonnet-4-5-20250929`
- **WHEN** a client calls `GET /v1/models`
- **THEN** the response includes an entry with `id: "claude-sonnet-4-5-20250929"`
- **AND** that entry has `owned_by: "anthropic"`

#### Scenario: Sidecar models respect API-key allowlist

- **GIVEN** an API key has `allowed_models: ["gpt-5.4"]`
- **AND** the sidecar returns `claude-sonnet-4-5-20250929`
- **WHEN** the key calls `GET /v1/models`
- **THEN** the response does not include `claude-sonnet-4-5-20250929`

#### Scenario: Sidecar model appears when allowed

- **GIVEN** an API key has `allowed_models: ["claude-sonnet-4-5-20250929"]`
- **AND** the sidecar returns `claude-sonnet-4-5-20250929`
- **WHEN** the key calls `GET /v1/models`
- **THEN** the response includes `claude-sonnet-4-5-20250929`

#### Scenario: Codex-native models remain unchanged

- **GIVEN** `claude_sidecar_enabled=true`
- **AND** the sidecar returns one or more `claude-*` models
- **WHEN** a client calls `GET /backend-api/codex/models`
- **THEN** the response does not include any sidecar model entries

#### Scenario: Sidecar model lookup failure does not fail Codex model listing

- **GIVEN** `claude_sidecar_enabled=true`
- **AND** the sidecar `/v1/models` endpoint is unreachable
- **WHEN** a client calls `GET /v1/models`
- **THEN** the service returns HTTP 200 with the existing Codex model entries
- **AND** the response is not failed solely because the sidecar model lookup failed
