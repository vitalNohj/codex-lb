## ADDED Requirements

### Requirement: Advertise configured Ollama full models only

`/v1/models` MUST advertise configured Ollama full models only when the Ollama integration is enabled. Discovered Ollama cloud models MUST NOT appear in `/v1/models` unless the operator has also configured the model as an Ollama full model.

Ollama model entries MUST use the configured full model ID unchanged, MUST be marked as owned by `ollama` unless discovery provides a more specific owner, and MUST advertise chat-completions support through the same sidecar metadata shape used by existing sidecar models. The service MUST apply API-key enforced-model and allowed-model filtering to Ollama entries using the effective configured model ID.

#### Scenario: Configured Ollama model appears

- **GIVEN** the Ollama sidecar is enabled
- **AND** Ollama full models include `gpt-oss:120b-cloud`
- **WHEN** a client calls `GET /v1/models`
- **THEN** the response includes a model entry with `id: "gpt-oss:120b-cloud"`
- **AND** the entry has `owned_by: "ollama"`

#### Scenario: Discovered-only cloud model does not appear

- **GIVEN** the Ollama sidecar is enabled
- **AND** Ollama model discovery returns `gpt-oss:20b-cloud`
- **AND** Ollama full models do not include `gpt-oss:20b-cloud`
- **WHEN** a client calls `GET /v1/models`
- **THEN** the response does not include `gpt-oss:20b-cloud`

#### Scenario: Disabled Ollama contributes no entries

- **GIVEN** the Ollama sidecar is disabled
- **AND** Ollama full models include `gpt-oss:120b-cloud`
- **WHEN** a client calls `GET /v1/models`
- **THEN** the response does not include an Ollama-owned `gpt-oss:120b-cloud` entry

#### Scenario: Ollama models respect API-key allowlist

- **GIVEN** an API key has `allowed_models: ["gpt-5.4"]`
- **AND** the Ollama sidecar is enabled
- **AND** Ollama full models include `gpt-oss:120b-cloud`
- **WHEN** the API key calls `GET /v1/models`
- **THEN** the response does not include `gpt-oss:120b-cloud`
