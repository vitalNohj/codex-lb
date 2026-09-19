## ADDED Requirements

### Requirement: OpenAI-compatible catalog includes configured generic full models

When a generic OpenAI-compatible endpoint is enabled, `GET /v1/models` MUST include that endpoint's configured full models in addition to existing catalog entries. Each entry MUST use the model id unchanged, MUST set `owned_by` to `openai_compat` when the upstream listing does not supply an owner, and MUST advertise chat-completions support.

Discovered-only models MUST NOT be advertised solely because `/models` listed them. Codex entries MUST win on id collision. API-key `allowed_models` / `enforced_model` filtering MUST apply. Lookup failure for one endpoint MUST NOT fail the rest of the listing. `GET /backend-api/codex/models` MUST remain Codex-only.

#### Scenario: Configured full model is listed

- **GIVEN** an enabled endpoint with full models including `Qwen/Qwen2.5-7B`
- **WHEN** a client calls `GET /v1/models`
- **THEN** the response includes `id: "Qwen/Qwen2.5-7B"`
- **AND** that entry has `owned_by: "openai_compat"` unless the upstream returned a different owner for that id

#### Scenario: Allowlist filters generic models

- **GIVEN** an API key has `allowed_models: ["gpt-5.4"]`
- **AND** a generic endpoint full models include `Qwen/Qwen2.5-7B`
- **WHEN** the key calls `GET /v1/models`
- **THEN** the response does not include `Qwen/Qwen2.5-7B`
