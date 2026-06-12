## ADDED Requirements

### Requirement: OpenAI-compatible model catalog includes configured OpenRouter sidecar models

When OpenRouter sidecar routing is enabled, `GET /v1/models` MUST include models returned by the configured OpenRouter `/v1/models` endpoint in addition to the existing Codex model catalog and any Claude sidecar models. OpenRouter model entries MUST use the OpenRouter model `id` unchanged, MUST be marked as owned by `openrouter`, and MUST advertise chat-completions support.

The service MUST apply the same authenticated API-key `allowed_models` and `enforced_model` filtering to OpenRouter model entries that it applies to existing `/v1/models` entries. If an OpenRouter model ID duplicates an existing Codex model ID, the existing Codex model entry MUST win and the duplicate OpenRouter entry MUST be skipped.

`GET /backend-api/codex/models` MUST remain Codex-only and MUST NOT include OpenRouter sidecar models.

#### Scenario: OpenAI-compatible models include OpenRouter entries

- **GIVEN** `openrouter_sidecar_enabled=true`
- **AND** OpenRouter `/v1/models` includes `deepseek/deepseek-chat`
- **WHEN** a client calls `GET /v1/models`
- **THEN** the response includes an entry with `id: "deepseek/deepseek-chat"`
- **AND** that entry has `owned_by: "openrouter"`

#### Scenario: OpenRouter models respect API-key allowlist

- **GIVEN** an API key has `allowed_models: ["gpt-5.4"]`
- **AND** OpenRouter returns `deepseek/deepseek-chat`
- **WHEN** the key calls `GET /v1/models`
- **THEN** the response does not include `deepseek/deepseek-chat`

#### Scenario: OpenRouter model lookup failure does not fail Codex model listing

- **GIVEN** `openrouter_sidecar_enabled=true`
- **AND** OpenRouter `/v1/models` is unreachable
- **WHEN** a client calls `GET /v1/models`
- **THEN** the service returns HTTP 200 with the existing Codex model entries
- **AND** the response is not failed solely because OpenRouter model lookup failed
