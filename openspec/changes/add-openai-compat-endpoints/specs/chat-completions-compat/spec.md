## ADDED Requirements

### Requirement: Route generic OpenAI-compat chat completions through the unified resolver

Enabled OpenAI-compatible endpoints MUST participate in `POST /v1/chat/completions` routing with provider `openai_compat:{uuid}`. Full-model exact match MUST beat prefixes. API-key validation, reservations, and request logs MUST use the effective client model. The resolver wire model MUST be forwarded.

The service MUST NOT dispatch these endpoints on `/v1/responses`. Providers not listed in `SIDECAR_PROVIDER_ORDER` MUST rank after every first-class integration. Chat Completions dispatch MUST handle `openai_compat:` before the OmniRoute fallback.

Effort override MUST always force the operator value when set. DeepSeek V4 `reasoning_content` repair MUST run on this chat path.

#### Scenario: Pinned full model routes to the named endpoint

- **GIVEN** an enabled endpoint named `Vast` with full models including `Qwen/Qwen2.5-7B`
- **WHEN** a client sends `POST /v1/chat/completions` with `model: "Qwen/Qwen2.5-7B"`
- **THEN** the service forwards the request to that endpoint's `{base}/chat/completions`
- **AND** the forwarded payload includes `model: "Qwen/Qwen2.5-7B"`
- **AND** no Codex account is selected

#### Scenario: Strip prefix forwards the wire model

- **GIVEN** the endpoint is enabled
- **AND** prefixes include `vast/` with strip true
- **WHEN** a client sends `model: "vast/Qwen/Qwen2.5-7B"`
- **THEN** the service routes to that endpoint
- **AND** the forwarded payload includes `model: "Qwen/Qwen2.5-7B"`

#### Scenario: First-class full model beats a generic prefix

- **GIVEN** OpenRouter and a generic endpoint are enabled
- **AND** the generic endpoint prefixes include `z-ai/`
- **AND** OpenRouter full models include `z-ai/glm-5.3`
- **WHEN** a client sends `model: "z-ai/glm-5.3"`
- **THEN** the service routes to OpenRouter
- **AND** the generic endpoint receives no request

#### Scenario: Disabled endpoint does not dispatch

- **GIVEN** the endpoint is disabled
- **WHEN** a client sends a model it would own if enabled
- **THEN** the service does not call that endpoint

#### Scenario: Responses stay off generic endpoints

- **GIVEN** an enabled endpoint owns `Qwen/Qwen2.5-7B`
- **WHEN** a client sends `POST /v1/responses` with that model
- **THEN** the service does not forward the request to the generic endpoint
