## ADDED Requirements

### Requirement: Cursor-compatible chat context-limit handling covers late and sidecar non-stream failures

The service MUST return the synthetic Cursor over-limit chat completion for every context-length failure on `POST /v1/chat/completions` when the downstream client is Cursor-compatible, including failures detected after stream startup on non-streaming requests.

For non-streaming Cursor-compatible chat requests routed to a sidecar provider, the service MUST return the synthetic over-limit chat completion when the provider reports a context-length failure, for every sidecar provider. Sidecar dispatchers MUST use one shared context-length detector rather than provider-specific Cursor logic. For clients that are not Cursor-compatible, the service MUST continue to surface the provider error unchanged.

#### Scenario: Cursor late non-stream context error returns synthetic usage

- **GIVEN** a Cursor-compatible non-streaming chat-completions request
- **WHEN** the upstream reports a context-length failure after stream startup succeeded
- **THEN** the service returns HTTP 200 with synthetic over-limit usage instead of an error envelope

#### Scenario: Cursor sidecar non-stream context error returns synthetic usage

- **GIVEN** a Cursor-compatible non-streaming chat-completions request routed to an OpenRouter, OmniRoute, or Ollama sidecar
- **WHEN** the sidecar reports a context-length failure
- **THEN** the service returns HTTP 200 with synthetic over-limit usage instead of the provider error envelope

#### Scenario: Non-Cursor sidecar context error is unchanged

- **GIVEN** a non-Cursor non-streaming chat-completions request routed to a sidecar
- **WHEN** the sidecar reports a context-length failure
- **THEN** the service returns the provider error envelope and status unchanged
