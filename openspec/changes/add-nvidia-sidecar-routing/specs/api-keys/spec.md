## ADDED Requirements

### Requirement: Model restrictions cover NVIDIA requests

The same model restriction enforcement MUST apply before a NVIDIA request is forwarded. The check MUST use the effective client model, not a stripped wire model.

#### Scenario: NVIDIA model not allowed

- **GIVEN** NVIDIA is enabled
- **AND** a key has `allowed_models: ["gpt-5.4"]`
- **WHEN** the key sends `POST /v1/chat/completions` with `model: "z-ai/glm-5.3"`
- **THEN** the proxy returns 403 with code `model_not_allowed`
- **AND** NVIDIA receives no request

### Requirement: Usage reservations cover NVIDIA requests

Authenticated API-key Chat Completions that route to NVIDIA MUST create a usage reservation before the outbound call. The reservation MUST be finalized once from response usage when present, and released once on failure, missing usage, or disconnect.

#### Scenario: Non-streaming usage finalizes reservation

- **GIVEN** an authenticated API key with request limits
- **AND** NVIDIA returns usage `prompt_tokens=10` and `completion_tokens=5`
- **WHEN** the request completes successfully
- **THEN** the reservation is finalized once for effective model `z-ai/glm-5.3` with 10 input tokens and 5 output tokens

#### Scenario: Failure releases reservation

- **GIVEN** an authenticated API key with request limits
- **AND** NVIDIA is unreachable
- **WHEN** the key sends a NVIDIA chat-completions request
- **THEN** the reservation is released once
