## ADDED Requirements

### Requirement: Route Ollama sidecar chat completions through unified resolver

The service MUST route matched Ollama sidecar Chat Completions requests through the unified sidecar resolver before native Codex account selection. The resolver MUST consider Ollama only when the Ollama sidecar integration is enabled, and it MUST use the effective client model for API-key model validation, request-limit reservations, and request logs while forwarding the resolver's wire model to Ollama.

The service MUST support Ollama full-model exact matches and prefix matches using the same full-model precedence, longest-prefix, and per-prefix strip rules as other sidecar integrations. Ollama dispatch MUST apply only to `POST /v1/chat/completions` in this change and MUST NOT route `/v1/responses` requests to Ollama.

#### Scenario: Full-model routing

- **GIVEN** the Ollama sidecar is enabled
- **AND** Ollama full models include `gpt-oss:120b-cloud`
- **WHEN** a client sends `POST /v1/chat/completions` with `model: "gpt-oss:120b-cloud"`
- **THEN** the service routes the request to Ollama
- **AND** the forwarded payload uses `model: "gpt-oss:120b-cloud"`
- **AND** no Codex account is selected for the request

#### Scenario: Prefix routing

- **GIVEN** the Ollama sidecar is enabled
- **AND** Ollama prefixes include `ollama/` with strip disabled
- **WHEN** a client sends `POST /v1/chat/completions` with `model: "ollama/gpt-oss:20b-cloud"`
- **THEN** the service routes the request to Ollama
- **AND** the forwarded payload uses `model: "ollama/gpt-oss:20b-cloud"`

#### Scenario: Prefix routing strips wire model

- **GIVEN** the Ollama sidecar is enabled
- **AND** Ollama prefixes include `ollama-` with strip enabled
- **WHEN** a client sends `POST /v1/chat/completions` with `model: "ollama-gpt-oss:20b-cloud"`
- **THEN** the service routes the request to Ollama
- **AND** the forwarded payload uses `model: "gpt-oss:20b-cloud"`
- **AND** request logs record the effective model `ollama-gpt-oss:20b-cloud`

#### Scenario: Streaming success

- **GIVEN** the Ollama sidecar is enabled
- **AND** Ollama emits streaming chat parts with content deltas
- **WHEN** a client sends an Ollama sidecar chat-completions request with `stream: true`
- **THEN** the downstream response is `text/event-stream`
- **AND** the stream emits OpenAI-compatible chat completion chunks in order
- **AND** the stream terminates with `data: [DONE]`

#### Scenario: Non-stream success

- **GIVEN** the Ollama sidecar is enabled
- **AND** Ollama returns a non-streaming chat response with content and token counts
- **WHEN** a client sends an Ollama sidecar chat-completions request with `stream: false`
- **THEN** the downstream response is an OpenAI-compatible chat completion
- **AND** `prompt_eval_count` is exposed as prompt tokens
- **AND** `eval_count` is exposed as completion tokens

#### Scenario: Upstream error

- **GIVEN** the Ollama sidecar is enabled
- **AND** Ollama returns an SDK response error or transport failure
- **WHEN** a client sends an Ollama sidecar chat-completions request
- **THEN** the service returns an OpenAI-compatible error envelope
- **AND** request-limit reservations are released or finalized according to the existing sidecar error path
- **AND** the response and logs do not expose the Ollama API key

#### Scenario: Disabled integration fallthrough

- **GIVEN** the Ollama sidecar is disabled
- **AND** Ollama full models include `gpt-oss:120b-cloud`
- **WHEN** a client sends `POST /v1/chat/completions` with `model: "gpt-oss:120b-cloud"`
- **THEN** the service does not route the request to Ollama
- **AND** the request follows the existing validation and native upstream behavior
