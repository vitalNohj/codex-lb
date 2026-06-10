## MODIFIED Requirements

### Requirement: Route Claude model chat completions to a configured sidecar

When Claude sidecar routing is enabled, the service MUST route `POST /v1/chat/completions` requests whose effective model starts with a configured Claude sidecar prefix to the configured CLIProxyAPI sidecar instead of mapping the request into the internal Responses API flow. Prefix matching MUST be case-insensitive and MUST run after API-key enforced-model resolution and model-access validation.

The service MUST forward the OpenAI-compatible chat-completions JSON payload to the sidecar with the effective model name and MUST relay the sidecar's OpenAI-compatible response to the downstream client. For sidecar requests, the service MUST NOT consult Codex account selection, sticky sessions, websocket continuity, ChatGPT upstream model registry behavior, or ChatGPT upstream transport selection.

#### Scenario: Claude custom model routes to sidecar

- **GIVEN** `claude_sidecar_enabled=true`
- **AND** the sidecar model prefix list includes `claude`
- **WHEN** a client sends `POST /v1/chat/completions` with `model: "claude-sonnet-4-5-20250929"`
- **THEN** the service forwards the request to the sidecar `/v1/chat/completions`
- **AND** the forwarded payload includes `model: "claude-sonnet-4-5-20250929"`
- **AND** no ChatGPT account is selected for the request

#### Scenario: Enforced model controls sidecar dispatch

- **GIVEN** an authenticated API key has `enforced_model: "claude-sonnet-4-5-20250929"`
- **AND** `claude_sidecar_enabled=true`
- **WHEN** the client sends `POST /v1/chat/completions` with `model: "gpt-5.4"`
- **THEN** the service dispatches the request to the sidecar
- **AND** the sidecar receives `model: "claude-sonnet-4-5-20250929"`

#### Scenario: Non-Claude models keep the existing Codex path

- **GIVEN** `claude_sidecar_enabled=true`
- **WHEN** a client sends `POST /v1/chat/completions` with `model: "gpt-5.4"`
- **THEN** the service uses the existing chat-completions-to-Responses mapping path
- **AND** the sidecar receives no request

#### Scenario: Sidecar disabled does not dispatch

- **GIVEN** `claude_sidecar_enabled=false`
- **WHEN** a client sends `POST /v1/chat/completions` with `model: "claude-sonnet-4-5-20250929"`
- **THEN** the service does not forward the request to the sidecar
- **AND** the request follows the existing validation and upstream path behavior

### Requirement: Relay sidecar streaming chat completions

For sidecar requests with `stream=true`, the service MUST respond with `text/event-stream` and MUST relay sidecar SSE bytes to the downstream client in order. The service MUST request usage information from the sidecar by setting or preserving `stream_options.include_usage=true` in the forwarded payload. When a final usage chunk is present, the service MUST use it for API-key reservation settlement.

#### Scenario: Streaming sidecar response is relayed

- **GIVEN** `claude_sidecar_enabled=true`
- **WHEN** the sidecar emits OpenAI-compatible SSE chunks followed by `data: [DONE]`
- **THEN** the downstream response contains those chunks in the same order
- **AND** the response media type is `text/event-stream`

#### Scenario: Streaming sidecar usage is requested

- **GIVEN** a sidecar request has `stream=true`
- **AND** the incoming payload omits `stream_options.include_usage`
- **WHEN** codex-lb forwards the request to the sidecar
- **THEN** the forwarded payload contains `stream_options.include_usage=true`

### Requirement: Map sidecar failures to OpenAI-compatible errors

When the sidecar is unreachable before an upstream response is received, the service MUST return HTTP 503 with an OpenAI error envelope whose error type is `upstream_error`. When the sidecar returns a non-2xx response with an OpenAI error envelope, the service SHOULD relay the envelope and status code. When the sidecar returns a non-2xx response that is not an OpenAI error envelope, the service MUST wrap the failure in an OpenAI error envelope.

#### Scenario: Sidecar unavailable

- **GIVEN** `claude_sidecar_enabled=true`
- **AND** the configured sidecar base URL is unreachable
- **WHEN** a client sends a Claude-model chat-completions request
- **THEN** the service returns HTTP 503
- **AND** the response body is an OpenAI error envelope with `error.type = "upstream_error"`

#### Scenario: Sidecar OpenAI error is relayed

- **GIVEN** the sidecar returns HTTP 401 with `{ "error": { "message": "expired", "type": "authentication_error" } }`
- **WHEN** a client sends a Claude-model chat-completions request
- **THEN** the service returns HTTP 401
- **AND** the response body preserves the sidecar error envelope
