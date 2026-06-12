## ADDED Requirements

### Requirement: Model restriction enforcement covers OpenRouter sidecar requests

When OpenRouter sidecar routing is enabled, the same model restriction enforcement MUST apply before an OpenRouter sidecar request is forwarded. An API key whose `allowed_models` excludes the effective OpenRouter sidecar model MUST receive the existing model-not-allowed error and OpenRouter MUST NOT receive the request.

#### Scenario: OpenRouter sidecar model not allowed

- **GIVEN** `openrouter_sidecar_enabled=true`
- **AND** a key has `allowed_models: ["gpt-5.4"]`
- **WHEN** the key sends `POST /v1/chat/completions` with `model: "deepseek/deepseek-chat"`
- **THEN** the proxy returns 403 with OpenAI-format error code `model_not_allowed`
- **AND** OpenRouter receives no request

#### Scenario: OpenRouter sidecar model allowed

- **GIVEN** `openrouter_sidecar_enabled=true`
- **AND** a key has `allowed_models: ["deepseek/deepseek-chat"]`
- **WHEN** the key sends `POST /v1/chat/completions` with `model: "deepseek/deepseek-chat"`
- **THEN** the proxy forwards the request to OpenRouter

### Requirement: API-key usage reservations cover OpenRouter sidecar requests

When an authenticated API key sends an OpenRouter sidecar chat-completions request, the service MUST create an API-key usage reservation before forwarding the request to OpenRouter. The reservation MUST be finalized exactly once with token counts from the OpenRouter response usage object when usage is available. If usage is missing, the OpenRouter request fails before usable response usage is available, or the downstream client disconnects before streaming completes, the reservation MUST be released exactly once.

#### Scenario: Non-streaming OpenRouter usage finalizes reservation

- **GIVEN** an authenticated API key with request limits
- **AND** OpenRouter returns a non-streaming chat-completions response with `usage.prompt_tokens=10` and `usage.completion_tokens=5`
- **WHEN** the request completes successfully
- **THEN** the API-key reservation is finalized once for the effective OpenRouter model with 10 input tokens and 5 output tokens

#### Scenario: OpenRouter failure releases reservation

- **GIVEN** an authenticated API key with request limits
- **AND** OpenRouter is unreachable
- **WHEN** the key sends an OpenRouter sidecar chat-completions request
- **THEN** the API-key reservation is released once
