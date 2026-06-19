## ADDED Requirements

### Requirement: Use effective model for Ollama API-key checks

API-key enforced model and allowed-model checks MUST use the effective client model for Ollama sidecar requests. When Ollama routing strips a prefix before forwarding to the upstream API, API-key validation, reservation accounting, and request logs MUST still use the original effective model requested by the client.

#### Scenario: Enforced model applies before Ollama routing

- **GIVEN** an API key has enforced model `ollama-gpt-oss:20b-cloud`
- **AND** Ollama owns prefix `ollama-` with strip enabled
- **WHEN** the key sends `POST /v1/chat/completions` without an explicit model override
- **THEN** validation uses `ollama-gpt-oss:20b-cloud`
- **AND** Ollama receives wire model `gpt-oss:20b-cloud`

#### Scenario: Allowed models use effective model

- **GIVEN** an API key allows only `ollama-gpt-oss:20b-cloud`
- **AND** Ollama owns prefix `ollama-` with strip enabled
- **WHEN** the key sends `POST /v1/chat/completions` with `model: "ollama-gpt-oss:20b-cloud"`
- **THEN** the request is allowed
- **AND** Ollama receives wire model `gpt-oss:20b-cloud`
