## ADDED Requirements

### Requirement: Route selected-model chat completions to a configured OmniRoute sidecar

When OmniRoute sidecar routing is enabled, the service MUST route `POST /v1/chat/completions` requests whose effective model exactly matches a configured OmniRoute sidecar selected model ID to the configured OmniRoute API instead of mapping the request into the internal Responses API flow. Model matching MUST be exact (case-insensitive normalized comparison) and MUST run after Claude sidecar prefix checks, OpenRouter sidecar prefix checks, API-key enforced-model resolution, and model-access validation.

The service MUST forward the OpenAI-compatible chat-completions JSON payload to OmniRoute with the effective model name unchanged. For OmniRoute sidecar requests, API-key validation, request-limit reservations, and request logs MUST continue to use the effective model requested by the client. The service MUST relay OmniRoute's OpenAI-compatible response to the downstream client. For OmniRoute sidecar requests, the service MUST NOT consult Codex account selection, sticky sessions, websocket continuity, ChatGPT upstream model registry behavior, or ChatGPT upstream transport selection.

#### Scenario: Selected OmniRoute model routes to sidecar

- **GIVEN** `omniroute_sidecar_enabled=true`
- **AND** the OmniRoute sidecar selected model list includes `my-selected-model`
- **WHEN** a client sends `POST /v1/chat/completions` with `model: "my-selected-model"`
- **THEN** the service forwards the request to OmniRoute `/chat/completions`
- **AND** the forwarded payload includes `model: "my-selected-model"`
- **AND** no ChatGPT account is selected for the request

#### Scenario: Claude sidecar takes precedence over OmniRoute sidecar

- **GIVEN** both Claude and OmniRoute sidecars are enabled
- **AND** the Claude sidecar prefix list includes `claude`
- **AND** the OmniRoute sidecar selected model list includes `claude-sonnet-4-5-20250929`
- **WHEN** a client sends `POST /v1/chat/completions` with `model: "claude-sonnet-4-5-20250929"`
- **THEN** the service forwards the request to the Claude sidecar
- **AND** OmniRoute receives no request

#### Scenario: OpenRouter sidecar takes precedence over OmniRoute sidecar

- **GIVEN** both OpenRouter and OmniRoute sidecars are enabled
- **AND** the OpenRouter sidecar prefix list includes `deepseek/`
- **AND** the OmniRoute sidecar selected model list includes `deepseek/deepseek-chat`
- **WHEN** a client sends `POST /v1/chat/completions` with `model: "deepseek/deepseek-chat"`
- **THEN** the service forwards the request to OpenRouter
- **AND** OmniRoute receives no request

#### Scenario: Non-selected models keep the existing Codex path

- **GIVEN** `omniroute_sidecar_enabled=true`
- **AND** the OmniRoute sidecar selected model list does not include `gpt-5.4`
- **WHEN** a client sends `POST /v1/chat/completions` with `model: "gpt-5.4"`
- **THEN** the service uses the existing chat-completions-to-Responses mapping path
- **AND** OmniRoute receives no request

#### Scenario: OmniRoute sidecar disabled does not dispatch

- **GIVEN** `omniroute_sidecar_enabled=false`
- **AND** the OmniRoute sidecar selected model list includes `my-selected-model`
- **WHEN** a client sends `POST /v1/chat/completions` with `model: "my-selected-model"`
- **THEN** the service does not forward the request to OmniRoute
- **AND** the request follows the existing validation and upstream path behavior

### Requirement: Relay OmniRoute sidecar streaming chat completions

For OmniRoute sidecar requests with `stream=true`, the service MUST respond with `text/event-stream` and MUST relay OmniRoute SSE bytes to the downstream client in order. The service MUST request usage information from OmniRoute by setting or preserving `stream_options.include_usage=true` in the forwarded payload. When a final usage chunk is present, the service MUST use it for API-key reservation settlement.

#### Scenario: Streaming OmniRoute response is relayed

- **GIVEN** `omniroute_sidecar_enabled=true`
- **WHEN** OmniRoute emits OpenAI-compatible SSE chunks followed by `data: [DONE]`
- **THEN** the downstream response contains those chunks in the same order

### Requirement: Map OmniRoute sidecar failures to OpenAI-compatible errors

When OmniRoute is unreachable before an upstream response is received, the service MUST return HTTP 503 with an OpenAI error envelope whose error type is `upstream_error`. When OmniRoute returns a non-2xx response with an OpenAI error envelope, the service SHOULD relay the envelope and status code. When OmniRoute returns a non-2xx response that is not an OpenAI error envelope, the service MUST wrap the failure in an OpenAI error envelope.

#### Scenario: OmniRoute unreachable

- **GIVEN** `omniroute_sidecar_enabled=true`
- **AND** OmniRoute is unreachable
- **WHEN** a client sends an OmniRoute sidecar chat-completions request
- **THEN** the service returns HTTP 503 with an OpenAI error envelope whose error type is `upstream_error`
