## ADDED Requirements

### Requirement: OpenAI-compatible model catalog includes configured OmniRoute sidecar models

When OmniRoute sidecar routing is enabled, `GET /v1/models` MUST include the configured selected OmniRoute model IDs in addition to the existing Codex model catalog, Claude sidecar models, and OpenRouter sidecar models. OmniRoute model entries MUST use the selected model ID unchanged, MUST be marked as owned by `omniroute`, and MUST advertise chat-completions support.

The service MUST apply the same authenticated API-key `allowed_models` and `enforced_model` filtering to OmniRoute model entries that it applies to existing `/v1/models` entries. If an OmniRoute selected model ID duplicates an existing Codex, Claude, or OpenRouter model ID, the existing entry MUST win and the duplicate OmniRoute entry MUST be skipped.

`GET /backend-api/codex/models` MUST remain Codex-only and MUST NOT include OmniRoute sidecar models.

#### Scenario: OpenAI-compatible models include OmniRoute entries

- **GIVEN** `omniroute_sidecar_enabled=true`
- **AND** the OmniRoute sidecar selected model list includes `my-selected-model`
- **WHEN** a client calls `GET /v1/models`
- **THEN** the response includes an entry with `id: "my-selected-model"`
- **AND** that entry has `owned_by: "omniroute"`

#### Scenario: OmniRoute models respect API-key allowlist

- **GIVEN** an API key has `allowed_models: ["gpt-5.4"]`
- **AND** the OmniRoute sidecar selected model list includes `my-selected-model`
- **WHEN** the key calls `GET /v1/models`
- **THEN** the response does not include `my-selected-model`

#### Scenario: Duplicate selected ID does not displace existing entry

- **GIVEN** `omniroute_sidecar_enabled=true`
- **AND** the OmniRoute sidecar selected model list includes `gpt-5.4`
- **AND** the existing Codex catalog already advertises `gpt-5.4`
- **WHEN** a client calls `GET /v1/models`
- **THEN** the response includes exactly one entry with `id: "gpt-5.4"`
- **AND** that entry has `owned_by` matching the existing Codex entry
