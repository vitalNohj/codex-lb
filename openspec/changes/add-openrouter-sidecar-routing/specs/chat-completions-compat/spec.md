## ADDED Requirements

### Requirement: Route OpenRouter model chat completions to a configured OpenRouter sidecar

When OpenRouter sidecar routing is enabled, the service MUST route `POST /v1/chat/completions` requests whose effective model starts with a configured OpenRouter sidecar prefix to the configured OpenRouter API instead of mapping the request into the internal Responses API flow. Prefix matching MUST be case-insensitive and MUST run after Claude sidecar prefix checks, API-key enforced-model resolution, and model-access validation. Configured custom alias prefixes ending in `-` or `_` MUST match either separator form for the same prefix stem.

The service MUST forward the OpenAI-compatible chat-completions JSON payload to OpenRouter with the effective model name, except that configured custom alias prefixes ending in `-` or `_` MUST be stripped from the model in the forwarded payload when applicable. For OpenRouter sidecar requests, API-key validation, request-limit reservations, and request logs MUST continue to use the effective model requested by the client. The service MUST relay OpenRouter's OpenAI-compatible response to the downstream client. For OpenRouter sidecar requests, the service MUST NOT consult Codex account selection, sticky sessions, websocket continuity, ChatGPT upstream model registry behavior, or ChatGPT upstream transport selection.

#### Scenario: OpenRouter model routes to sidecar

- **GIVEN** `openrouter_sidecar_enabled=true`
- **AND** the OpenRouter sidecar model prefix list includes `deepseek/`
- **WHEN** a client sends `POST /v1/chat/completions` with `model: "deepseek/deepseek-chat"`
- **THEN** the service forwards the request to OpenRouter `/v1/chat/completions`
- **AND** the forwarded payload includes `model: "deepseek/deepseek-chat"`
- **AND** no ChatGPT account is selected for the request

#### Scenario: Claude sidecar takes precedence over OpenRouter sidecar

- **GIVEN** both Claude and OpenRouter sidecars are enabled
- **AND** the Claude sidecar prefix list includes `claude`
- **AND** the OpenRouter sidecar prefix list includes `anthropic/`
- **WHEN** a client sends `POST /v1/chat/completions` with `model: "claude-sonnet-4-5-20250929"`
- **THEN** the service forwards the request to the Claude sidecar
- **AND** OpenRouter receives no request

#### Scenario: Non-OpenRouter models keep the existing Codex path

- **GIVEN** `openrouter_sidecar_enabled=true`
- **WHEN** a client sends `POST /v1/chat/completions` with `model: "gpt-5.4"` and no configured OpenRouter prefix matches
- **THEN** the service uses the existing chat-completions-to-Responses mapping path
- **AND** OpenRouter receives no request

#### Scenario: OpenRouter sidecar disabled does not dispatch

- **GIVEN** `openrouter_sidecar_enabled=false`
- **WHEN** a client sends `POST /v1/chat/completions` with `model: "deepseek/deepseek-chat"`
- **THEN** the service does not forward the request to OpenRouter
- **AND** the request follows the existing validation and upstream path behavior

### Requirement: Relay OpenRouter sidecar streaming chat completions

For OpenRouter sidecar requests with `stream=true`, the service MUST respond with `text/event-stream` and MUST relay OpenRouter SSE bytes to the downstream client in order. The service MUST request usage information from OpenRouter by setting or preserving `stream_options.include_usage=true` in the forwarded payload. When a final usage chunk is present, the service MUST use it for API-key reservation settlement.

#### Scenario: Streaming OpenRouter response is relayed

- **GIVEN** `openrouter_sidecar_enabled=true`
- **WHEN** OpenRouter emits OpenAI-compatible SSE chunks followed by `data: [DONE]`
- **THEN** the downstream response contains those chunks in the same order

### Requirement: Map OpenRouter sidecar failures to OpenAI-compatible errors

When OpenRouter is unreachable before an upstream response is received, the service MUST return HTTP 503 with an OpenAI error envelope whose error type is `upstream_error`. When OpenRouter returns a non-2xx response with an OpenAI error envelope, the service SHOULD relay the envelope and status code. When OpenRouter returns a non-2xx response that is not an OpenAI error envelope, the service MUST wrap the failure in an OpenAI error envelope.

#### Scenario: OpenRouter unreachable

- **GIVEN** `openrouter_sidecar_enabled=true`
- **AND** OpenRouter is unreachable
- **WHEN** a client sends an OpenRouter sidecar chat-completions request
- **THEN** the service returns HTTP 503 with an OpenAI error envelope whose error type is `upstream_error`
