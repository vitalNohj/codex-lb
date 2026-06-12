## ADDED Requirements

### Requirement: Route selected-model Responses requests to a configured OmniRoute sidecar

When OmniRoute sidecar routing is enabled, the service MUST route `POST /backend-api/codex/responses` and `POST /v1/responses` requests whose effective model exactly matches a configured OmniRoute sidecar selected model ID to the configured OmniRoute API instead of selecting a ChatGPT/Codex account. Model matching MUST be exact (case-insensitive normalized comparison) and MUST run after API-key authentication, API-key enforced-model resolution, and model-access validation, and before any ChatGPT/Codex account selection, sticky-session lookup, or upstream Responses transport selection.

For OmniRoute sidecar Responses requests, the service MUST translate the Responses-shaped request into an OpenAI-compatible chat-completions request before forwarding it to OmniRoute `/chat/completions`, preserving the effective model name unchanged. The service MUST translate OmniRoute's chat-completions response back into the Responses result/event shape expected by the downstream client. The service MUST NOT consult Codex account selection, sticky sessions, websocket continuity, ChatGPT upstream model registry behavior, or ChatGPT upstream transport selection for these requests.

#### Scenario: Selected OmniRoute model on /v1/responses routes to sidecar

- **GIVEN** `omniroute_sidecar_enabled=true`
- **AND** the OmniRoute sidecar selected model list includes `my-selected-model`
- **WHEN** a client sends `POST /v1/responses` with `model: "my-selected-model"`
- **THEN** the service forwards the translated request to OmniRoute `/chat/completions`
- **AND** the forwarded payload includes `model: "my-selected-model"`
- **AND** no ChatGPT account is selected for the request

#### Scenario: Selected OmniRoute model on /backend-api/codex/responses routes to sidecar

- **GIVEN** `omniroute_sidecar_enabled=true`
- **AND** the OmniRoute sidecar selected model list includes `my-selected-model`
- **WHEN** a client sends `POST /backend-api/codex/responses` with `model: "my-selected-model"`
- **THEN** the service forwards the translated request to OmniRoute `/chat/completions`
- **AND** the forwarded payload includes `model: "my-selected-model"`
- **AND** no ChatGPT account is selected for the request

#### Scenario: Non-selected models keep the existing Codex Responses path

- **GIVEN** `omniroute_sidecar_enabled=true`
- **AND** the OmniRoute sidecar selected model list does not include `gpt-5.4`
- **WHEN** a client sends `POST /v1/responses` with `model: "gpt-5.4"`
- **THEN** the service uses the existing Responses-to-Codex upstream path
- **AND** OmniRoute receives no request

#### Scenario: OmniRoute sidecar disabled does not dispatch on Responses endpoints

- **GIVEN** `omniroute_sidecar_enabled=false`
- **AND** the OmniRoute sidecar selected model list includes `my-selected-model`
- **WHEN** a client sends `POST /v1/responses` with `model: "my-selected-model"`
- **THEN** the service does not forward the request to OmniRoute
- **AND** the request follows the existing Responses validation and upstream path behavior

### Requirement: Translate Responses sidecar requests to chat-completions and back

For OmniRoute sidecar Responses requests, the service MUST build the chat-completions `messages` from the Responses `instructions` and `input` content, forward `tools` and `tool_choice` in OpenAI chat-completions shape, and request usage by setting or preserving `stream_options.include_usage=true` when streaming. The service MUST surface the OmniRoute assistant output to the downstream client as a Responses result (non-streaming) or Responses event stream (streaming). Codex-native server-side continuity fields (`previous_response_id`, `conversation`, `store`) MUST NOT cause Codex account state to be consulted for sidecar requests.

#### Scenario: Streaming Responses sidecar request emits Responses events

- **GIVEN** `omniroute_sidecar_enabled=true`
- **AND** the OmniRoute sidecar selected model list includes `my-selected-model`
- **WHEN** a client sends `POST /v1/responses` with `model: "my-selected-model"` and `stream: true`
- **AND** OmniRoute returns OpenAI-compatible chat-completion SSE deltas
- **THEN** the downstream response is `text/event-stream`
- **AND** the stream begins with a `response.created` event
- **AND** the stream ends with a terminal `response.completed` event

#### Scenario: Non-streaming Responses sidecar request returns a Responses result

- **GIVEN** `omniroute_sidecar_enabled=true`
- **AND** the OmniRoute sidecar selected model list includes `my-selected-model`
- **WHEN** a client sends `POST /v1/responses` with `model: "my-selected-model"` and `stream: false`
- **AND** OmniRoute returns an OpenAI-compatible chat-completion JSON body
- **THEN** the downstream response is a Responses result object containing the assistant output

### Requirement: Preserve API-key accounting and logging for Responses sidecar requests

For OmniRoute sidecar Responses requests, the service MUST apply API-key model-access validation, MUST reserve and settle request-limit usage using the effective model, and MUST write request logs with `source=omniroute_sidecar`. When a usage chunk is present in the OmniRoute response, the service MUST use it for reservation settlement; otherwise it MUST release the reservation.

#### Scenario: Reservation settles from OmniRoute usage on the Responses path

- **GIVEN** `omniroute_sidecar_enabled=true`
- **AND** an API key with request-limit accounting enabled
- **WHEN** a client sends an OmniRoute sidecar `POST /v1/responses` request
- **AND** OmniRoute returns a usage chunk
- **THEN** the API-key reservation is finalized using the returned usage
- **AND** a request log is written with `source=omniroute_sidecar`

### Requirement: Map OmniRoute Responses sidecar failures to client-visible errors

When OmniRoute is unreachable before a response is received for a Responses sidecar request, the service MUST return an error to the downstream client (HTTP 503 with an OpenAI error envelope for non-streaming requests, or a terminal error event followed by stream termination for streaming requests) and MUST release the API-key reservation. When OmniRoute returns a non-2xx response, the service MUST surface a client-visible error and MUST release the reservation.

#### Scenario: OmniRoute unreachable on the Responses path

- **GIVEN** `omniroute_sidecar_enabled=true`
- **AND** OmniRoute is unreachable
- **WHEN** a client sends a non-streaming OmniRoute sidecar `POST /v1/responses` request
- **THEN** the service returns HTTP 503 with an OpenAI error envelope whose error type is `upstream_error`
- **AND** the API-key reservation is released
