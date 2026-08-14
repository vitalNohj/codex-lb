## ADDED Requirements

### Requirement: Sidecar upstream auth failures are client-retryable

After the proxy has already accepted the client API key, sidecar upstream HTTP 401 or 403 responses MUST be returned to the client as HTTP 503 with a `Retry-After` header, not as HTTP 401/403. The client-facing OpenAI error envelope MUST use an upstream-unavailable error code and MUST NOT present the upstream failure as a missing or invalid client API key. Request-log `error_message` MUST retain the original upstream message for operators.

#### Scenario: OmniRoute non-stream chat returns 503 for upstream Missing API key

- **GIVEN** the client API key has already been accepted
- **AND** the OmniRoute sidecar returns HTTP 401 with message `[401]: Missing API key`
- **WHEN** the proxy handles a non-streaming `/v1/chat/completions` sidecar request
- **THEN** the client receives HTTP 503 with a `Retry-After` header
- **AND** the response error code is not a client `invalid_api_key` / missing-key auth failure
- **AND** the request log retains the original upstream message containing `Missing API key`

#### Scenario: OmniRoute stream chat SSE does not look like client auth death

- **GIVEN** the client API key has already been accepted
- **AND** the OmniRoute sidecar fails a streaming chat completion with HTTP 401 `Missing API key`
- **WHEN** the proxy emits the terminal SSE error event
- **THEN** the SSE error envelope message MUST NOT be the bare upstream `[401]: Missing API key` auth phrasing
- **AND** the envelope MUST indicate a transient upstream unavailability that clients can retry

#### Scenario: Other sidecar providers follow the same remap

- **GIVEN** CLIProxyAPI, OpenRouter, or Ollama sidecar dispatch has already accepted the client API key
- **WHEN** that sidecar returns HTTP 401 or 403
- **THEN** the client-facing HTTP status is 503 with `Retry-After`
- **AND** true pre-dispatch client auth failures continue to return HTTP 401 unchanged
