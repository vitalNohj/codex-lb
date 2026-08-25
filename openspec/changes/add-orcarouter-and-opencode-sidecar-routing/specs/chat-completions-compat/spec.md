## ADDED Requirements

### Requirement: Route OrcaRouter sidecar chat completions through unified resolver

The service MUST route matched OrcaRouter sidecar Chat Completions requests through the unified sidecar resolver before native Codex account selection. The resolver MUST consider OrcaRouter only when the OrcaRouter sidecar integration is enabled, and it MUST use the effective client model for API-key model validation, request-limit reservations, and request logs while forwarding the resolver's wire model to OrcaRouter.

The service MUST support OrcaRouter full-model exact matches and prefix matches using the same full-model precedence, longest-prefix, and per-prefix strip rules as other sidecar integrations. OrcaRouter dispatch MUST apply only to `POST /v1/chat/completions` in this change and MUST NOT route `/v1/responses` requests to OrcaRouter. New installations MUST seed prefix `orcarouter/` with strip disabled so `orcarouter/auto` is forwarded unchanged.

#### Scenario: Namespaced auto model is forwarded unchanged

- **GIVEN** the OrcaRouter sidecar is enabled
- **AND** OrcaRouter prefixes include `orcarouter/` with strip disabled
- **WHEN** a client sends `POST /v1/chat/completions` with `model: "orcarouter/auto"`
- **THEN** the service routes the request to OrcaRouter
- **AND** the forwarded payload uses `model: "orcarouter/auto"`
- **AND** no Codex account is selected for the request

#### Scenario: Full-model exact match beats OpenRouter prefix

- **GIVEN** the OrcaRouter sidecar is enabled
- **AND** OrcaRouter full models include `openai/gpt-5.5`
- **AND** OpenRouter prefixes include `openai/`
- **WHEN** a client sends `POST /v1/chat/completions` with `model: "openai/gpt-5.5"`
- **THEN** the service routes the request to OrcaRouter
- **AND** the forwarded payload uses `model: "openai/gpt-5.5"`

#### Scenario: Streaming success

- **GIVEN** the OrcaRouter sidecar is enabled
- **AND** OrcaRouter emits OpenAI-compatible SSE chunks
- **WHEN** a client sends an OrcaRouter sidecar chat-completions request with `stream: true`
- **THEN** the downstream response is `text/event-stream`
- **AND** the stream terminates with `data: [DONE]`

#### Scenario: Non-stream success

- **GIVEN** the OrcaRouter sidecar is enabled
- **AND** OrcaRouter returns a non-streaming OpenAI chat completion
- **WHEN** a client sends an OrcaRouter sidecar chat-completions request with `stream: false`
- **THEN** the downstream response is an OpenAI-compatible chat completion

#### Scenario: Upstream error

- **GIVEN** the OrcaRouter sidecar is enabled
- **AND** OrcaRouter returns an upstream error or transport failure
- **WHEN** a client sends an OrcaRouter sidecar chat-completions request
- **THEN** the service returns an OpenAI-compatible error envelope
- **AND** request-limit reservations are released or finalized according to the existing sidecar error path
- **AND** the response and logs do not expose the OrcaRouter API key

#### Scenario: Disabled integration fallthrough

- **GIVEN** the OrcaRouter sidecar is disabled
- **AND** OrcaRouter prefixes include `orcarouter/`
- **WHEN** a client sends `POST /v1/chat/completions` with `model: "orcarouter/auto"`
- **THEN** the service does not route the request to OrcaRouter
- **AND** the request follows the existing validation and native upstream behavior

### Requirement: Route OpenCode Zen sidecar chat completions through unified resolver

The service MUST route matched OpenCode Zen sidecar Chat Completions requests through the unified sidecar resolver before native Codex account selection. The resolver MUST consider OpenCode Zen only when the OpenCode Zen sidecar integration is enabled, and it MUST use the effective client model for API-key model validation, request-limit reservations, and request logs while forwarding the resolver's wire model to OpenCode Zen.

The service MUST support OpenCode Zen full-model exact matches and prefix matches using the same full-model precedence, longest-prefix, and per-prefix strip rules as other sidecar integrations. OpenCode Zen dispatch MUST apply only to `POST /v1/chat/completions` in this change and MUST NOT route `/v1/responses` or Zen `/messages` requests to OpenCode Zen. New installations MUST seed prefix `opencode-zen/` with strip enabled. OpenCode Zen dispatch MUST require a stored API key; a missing key MUST NOT send the request upstream.

#### Scenario: Prefix routing strips wire model

- **GIVEN** the OpenCode Zen sidecar is enabled
- **AND** OpenCode Zen prefixes include `opencode-zen/` with strip enabled
- **WHEN** a client sends `POST /v1/chat/completions` with `model: "opencode-zen/mimo-v2.5-free"`
- **THEN** the service routes the request to OpenCode Zen
- **AND** the forwarded payload uses `model: "mimo-v2.5-free"`
- **AND** request logs record the effective model `opencode-zen/mimo-v2.5-free`

#### Scenario: Missing key skips upstream

- **GIVEN** the OpenCode Zen sidecar is enabled
- **AND** no OpenCode Zen API key is stored
- **WHEN** a client sends `POST /v1/chat/completions` with `model: "opencode-zen/mimo-v2.5-free"`
- **THEN** the service does not send an Authorization header to OpenCode Zen
- **AND** the service returns an OpenAI-compatible error without calling the zen host as a successful chat

#### Scenario: Streaming success

- **GIVEN** the OpenCode Zen sidecar is enabled
- **AND** an OpenCode Zen API key is stored
- **AND** OpenCode Zen emits OpenAI-compatible SSE chunks
- **WHEN** a client sends an OpenCode Zen sidecar chat-completions request with `stream: true`
- **THEN** the downstream response is `text/event-stream`
- **AND** the stream terminates with `data: [DONE]`

#### Scenario: Upstream error

- **GIVEN** the OpenCode Zen sidecar is enabled
- **AND** OpenCode Zen returns an upstream error or transport failure
- **WHEN** a client sends an OpenCode Zen sidecar chat-completions request
- **THEN** the service returns an OpenAI-compatible error envelope
- **AND** request-limit reservations are released or finalized according to the existing sidecar error path
- **AND** the response and logs do not expose the OpenCode Zen API key

#### Scenario: Disabled integration fallthrough

- **GIVEN** the OpenCode Zen sidecar is disabled
- **AND** OpenCode Zen prefixes include `opencode-zen/`
- **WHEN** a client sends `POST /v1/chat/completions` with `model: "opencode-zen/mimo-v2.5-free"`
- **THEN** the service does not route the request to OpenCode Zen
- **AND** the request follows the existing validation and native upstream behavior

### Requirement: Route OpenCode Free sidecar chat completions through unified resolver

The service MUST route matched OpenCode Free sidecar Chat Completions requests through the unified sidecar resolver before native Codex account selection. The resolver MUST consider OpenCode Free only when the OpenCode Free sidecar integration is enabled, and it MUST use the effective client model for API-key model validation, request-limit reservations, and request logs while forwarding the resolver's wire model to OpenCode Free.

The service MUST support OpenCode Free full-model exact matches and prefix matches using the same full-model precedence, longest-prefix, and per-prefix strip rules as other sidecar integrations. OpenCode Free dispatch MUST apply only to `POST /v1/chat/completions` in this change and MUST NOT route `/v1/responses` requests to OpenCode Free. New installations MUST seed prefix `oc/` with strip enabled and MUST NOT seed prefix `opencode/`. OpenCode Free dispatch MUST succeed without an API key when the integration is enabled.

#### Scenario: Prefix routing strips wire model

- **GIVEN** the OpenCode Free sidecar is enabled
- **AND** OpenCode Free prefixes include `oc/` with strip enabled
- **WHEN** a client sends `POST /v1/chat/completions` with `model: "oc/big-pickle"`
- **THEN** the service routes the request to OpenCode Free
- **AND** the forwarded payload uses `model: "big-pickle"`
- **AND** request logs record the effective model `oc/big-pickle`

#### Scenario: Keyless dispatch

- **GIVEN** the OpenCode Free sidecar is enabled
- **AND** no OpenCode Free API key is stored
- **WHEN** a client sends `POST /v1/chat/completions` with `model: "oc/big-pickle"`
- **THEN** the service routes the request to OpenCode Free without an Authorization header

#### Scenario: Zen prefix does not fall through to Free

- **GIVEN** the OpenCode Free sidecar is enabled with prefix `oc/`
- **AND** the OpenCode Zen sidecar is enabled with prefix `opencode-zen/`
- **WHEN** a client sends `POST /v1/chat/completions` with `model: "opencode-zen/mimo-v2.5-free"`
- **THEN** the service routes the request to OpenCode Zen
- **AND** the service does not route the request to OpenCode Free

#### Scenario: Streaming success

- **GIVEN** the OpenCode Free sidecar is enabled
- **AND** OpenCode Free emits OpenAI-compatible SSE chunks
- **WHEN** a client sends an OpenCode Free sidecar chat-completions request with `stream: true`
- **THEN** the downstream response is `text/event-stream`
- **AND** the stream terminates with `data: [DONE]`

#### Scenario: Upstream error

- **GIVEN** the OpenCode Free sidecar is enabled
- **AND** OpenCode Free returns an upstream error or transport failure
- **WHEN** a client sends an OpenCode Free sidecar chat-completions request
- **THEN** the service returns an OpenAI-compatible error envelope
- **AND** request-limit reservations are released or finalized according to the existing sidecar error path

#### Scenario: Disabled integration fallthrough

- **GIVEN** the OpenCode Free sidecar is disabled
- **AND** OpenCode Free prefixes include `oc/`
- **WHEN** a client sends `POST /v1/chat/completions` with `model: "oc/big-pickle"`
- **THEN** the service does not route the request to OpenCode Free
- **AND** the request follows the existing validation and native upstream behavior

### Requirement: Apply sidecar effort override and DeepSeek V4 repair on the new chat paths

The service MUST apply the operator-configured sidecar reasoning-effort override as a forced value on OrcaRouter, OpenCode Zen, and OpenCode Free Chat Completions payloads, and it MUST run the existing DeepSeek V4 `reasoning_content` repair on all three chat-completions paths.

#### Scenario: OrcaRouter effort override wins

- **GIVEN** the OrcaRouter sidecar is enabled
- **AND** the OrcaRouter default reasoning effort is `high`
- **WHEN** a client sends an OrcaRouter sidecar chat-completions request with a different client effort
- **THEN** the forwarded payload uses reasoning effort `high`

#### Scenario: OpenCode Zen effort override wins

- **GIVEN** the OpenCode Zen sidecar is enabled
- **AND** the OpenCode Zen default reasoning effort is `high`
- **WHEN** a client sends an OpenCode Zen sidecar chat-completions request with a different client effort
- **THEN** the forwarded payload uses reasoning effort `high`

#### Scenario: OpenCode Free DeepSeek V4 tool-turn repair

- **GIVEN** the OpenCode Free sidecar is enabled
- **AND** the request model is a DeepSeek V4 family id such as `oc/deepseek-v4-flash-free`
- **AND** cached reasoning exists for the conversation prefix
- **WHEN** the client replays an assistant tool-call turn without `reasoning_content`
- **THEN** the forwarded OpenCode Free payload re-injects the cached reasoning

#### Scenario: OpenCode Zen DeepSeek V4 tool-turn repair

- **GIVEN** the OpenCode Zen sidecar is enabled
- **AND** the request model is a DeepSeek V4 family id such as `opencode-zen/deepseek-v4-flash`
- **AND** cached reasoning exists for the conversation prefix
- **WHEN** the client replays an assistant tool-call turn without `reasoning_content`
- **THEN** the forwarded OpenCode Zen payload re-injects the cached reasoning
