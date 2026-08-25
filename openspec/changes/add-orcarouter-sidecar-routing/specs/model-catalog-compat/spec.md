## ADDED Requirements

### Requirement: OpenAI-compatible catalog includes configured OrcaRouter full models

When OrcaRouter is enabled, `GET /v1/models` MUST include configured OrcaRouter full models in addition to existing catalog entries. Each OrcaRouter entry MUST use the model id unchanged, MUST set `owned_by` to `orcarouter` when the upstream listing does not supply an owner, and MUST advertise chat-completions support.

Discovered-only models MUST NOT be advertised solely because `/models` listed them. Codex entries MUST win on id collision. API-key `allowed_models` / `enforced_model` filtering MUST apply. OpenRouter lookup failure MUST NOT fail the Codex listing. `GET /backend-api/codex/models` MUST remain Codex-only.

#### Scenario: Configured full model is listed

- **GIVEN** OrcaRouter is enabled
- **AND** full models include `orcarouter/auto`
- **WHEN** a client calls `GET /v1/models`
- **THEN** the response includes `id: "orcarouter/auto"`
- **AND** that entry has `owned_by: "orcarouter"` unless OrcaRouter returned a different owner for that id

#### Scenario: Allowlist filters OrcaRouter models

- **GIVEN** an API key has `allowed_models: ["gpt-5.4"]`
- **AND** OrcaRouter full models include `orcarouter/auto`
- **WHEN** the key calls `GET /v1/models`
- **THEN** the response does not include `orcarouter/auto`
