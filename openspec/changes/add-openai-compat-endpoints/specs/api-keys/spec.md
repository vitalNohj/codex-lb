## ADDED Requirements

### Requirement: Model restrictions cover generic OpenAI-compat requests

The same model restriction enforcement MUST apply before a generic OpenAI-compat request is forwarded. The check MUST use the effective client model, not a stripped wire model.

#### Scenario: Generic model not allowed

- **GIVEN** an enabled generic endpoint owns `Qwen/Qwen2.5-7B`
- **AND** a key has `allowed_models: ["gpt-5.4"]`
- **WHEN** the key sends `POST /v1/chat/completions` with `model: "Qwen/Qwen2.5-7B"`
- **THEN** the proxy returns 403 with code `model_not_allowed`
- **AND** the generic endpoint receives no request

### Requirement: Usage reservations cover generic OpenAI-compat requests

Authenticated API-key Chat Completions that route to a generic endpoint MUST create a usage reservation before the outbound call. The reservation MUST be finalized once from response usage when present, and released once on failure, missing usage, or disconnect.

#### Scenario: Non-streaming usage finalizes reservation

- **GIVEN** an authenticated API key with request limits
- **AND** the generic endpoint returns usage `prompt_tokens=10` and `completion_tokens=5`
- **WHEN** the request completes successfully
- **THEN** the reservation is finalized once for effective model `Qwen/Qwen2.5-7B` with 10 input tokens and 5 output tokens

#### Scenario: Failure releases reservation

- **GIVEN** an authenticated API key with request limits
- **AND** the generic endpoint is unreachable
- **WHEN** the key sends a matching chat-completions request
- **THEN** the reservation is released once
