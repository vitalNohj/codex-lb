## ADDED Requirements

### Requirement: OpenAI-compatible catalog includes configured NVIDIA full models

When NVIDIA is enabled, `GET /v1/models` MUST include configured NVIDIA full models in addition to existing catalog entries. Each NVIDIA entry MUST use the model id unchanged, MUST set `owned_by` to `nvidia` when the upstream listing does not supply an owner, and MUST advertise chat-completions support.

Discovered-only models MUST NOT be advertised solely because `/models` listed them. Codex entries MUST win on id collision. API-key `allowed_models` / `enforced_model` filtering MUST apply. NVIDIA lookup failure MUST NOT fail the Codex listing. `GET /backend-api/codex/models` MUST remain Codex-only.

#### Scenario: Configured full model is listed

- **GIVEN** NVIDIA is enabled
- **AND** full models include `z-ai/glm-5.3`
- **WHEN** a client calls `GET /v1/models`
- **THEN** the response includes `id: "z-ai/glm-5.3"`
- **AND** that entry has `owned_by: "nvidia"` unless NVIDIA returned a different owner for that id

#### Scenario: Allowlist filters NVIDIA models

- **GIVEN** an API key has `allowed_models: ["gpt-5.4"]`
- **AND** NVIDIA full models include `z-ai/glm-5.3`
- **WHEN** the key calls `GET /v1/models`
- **THEN** the response does not include `z-ai/glm-5.3`
