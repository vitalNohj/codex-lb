## ADDED Requirements

### Requirement: Model restriction enforcement covers OmniRoute sidecar requests

When OmniRoute sidecar routing is enabled, the same model restriction enforcement MUST apply before an OmniRoute sidecar request is forwarded. An API key whose `allowed_models` excludes the effective OmniRoute sidecar model MUST receive the existing model-not-allowed error and OmniRoute MUST NOT receive the request.

#### Scenario: OmniRoute sidecar model not allowed

- **GIVEN** `omniroute_sidecar_enabled=true`
- **AND** the OmniRoute sidecar selected model list includes `my-selected-model`
- **AND** a key has `allowed_models: ["gpt-5.4"]`
- **WHEN** the key sends `POST /v1/chat/completions` with `model: "my-selected-model"`
- **THEN** the proxy returns 403 with OpenAI-format error code `model_not_allowed`
- **AND** OmniRoute receives no request

#### Scenario: OmniRoute sidecar model allowed

- **GIVEN** `omniroute_sidecar_enabled=true`
- **AND** the OmniRoute sidecar selected model list includes `my-selected-model`
- **AND** a key has `allowed_models: ["my-selected-model"]`
- **WHEN** the key sends `POST /v1/chat/completions` with `model: "my-selected-model"`
- **THEN** the proxy forwards the request to OmniRoute

### Requirement: API-key usage reservations cover OmniRoute sidecar requests

When an authenticated API key sends an OmniRoute sidecar chat-completions request, the service MUST create an API-key usage reservation before forwarding the request to OmniRoute. The reservation MUST be finalized exactly once with token counts from the OmniRoute response usage object when usage is available. If usage is missing, the OmniRoute request fails before usable response usage is available, or the downstream client disconnects before streaming completes, the reservation MUST be released exactly once.

#### Scenario: Non-streaming OmniRoute usage finalizes reservation

- **GIVEN** an authenticated API key with request limits
- **AND** OmniRoute returns a non-streaming chat-completions response with `usage.prompt_tokens=10` and `usage.completion_tokens=5`
- **WHEN** the request completes successfully
- **THEN** the API-key reservation is finalized once for the effective OmniRoute model with 10 input tokens and 5 output tokens

#### Scenario: OmniRoute failure releases reservation

- **GIVEN** an authenticated API key with request limits
- **AND** OmniRoute is unreachable
- **WHEN** the key sends an OmniRoute sidecar chat-completions request
- **THEN** the API-key reservation is released once
