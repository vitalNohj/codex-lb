## ADDED Requirements

### Requirement: Route OrcaRouter chat completions through the unified resolver

When OrcaRouter is enabled, `POST /v1/chat/completions` whose effective model matches an OrcaRouter full model or prefix MUST route to the configured OrcaRouter API instead of Codex. Provider order MUST be `claude`, `openrouter`, `orcarouter`, `omniroute`, `ollama`. Full-model exact match MUST beat prefixes. The seeded `orcarouter/` prefix MUST have strip off so `orcarouter/auto` is forwarded unchanged.

API-key validation, reservations, and request logs MUST use the effective client model. The resolver wire model MUST be forwarded to OrcaRouter.

The service MUST NOT dispatch OrcaRouter models on `/v1/responses`.

Effort override MUST always force the operator value when set. DeepSeek V4 `reasoning_content` repair MUST run on the OrcaRouter chat path.

#### Scenario: orcarouter/auto routes unstripped

- **GIVEN** `orcarouter_sidecar_enabled=true`
- **AND** prefixes include `orcarouter/` with strip false
- **WHEN** a client sends `POST /v1/chat/completions` with `model: "orcarouter/auto"`
- **THEN** the service forwards the request to `https://api.orcarouter.ai/v1/chat/completions`
- **AND** the forwarded payload includes `model: "orcarouter/auto"`
- **AND** no Codex account is selected

#### Scenario: Full model beats OpenRouter prefixes

- **GIVEN** OpenRouter and OrcaRouter are enabled
- **AND** OpenRouter prefixes include `deepseek/`
- **AND** OrcaRouter full models include `deepseek/deepseek-chat`
- **WHEN** a client sends `model: "deepseek/deepseek-chat"`
- **THEN** the service routes to OrcaRouter
- **AND** OpenRouter receives no request

#### Scenario: Disabled integration does not dispatch

- **GIVEN** `orcarouter_sidecar_enabled=false`
- **WHEN** a client sends `model: "orcarouter/auto"`
- **THEN** the service does not call OrcaRouter

#### Scenario: Responses stay off OrcaRouter

- **GIVEN** OrcaRouter is enabled and owns `orcarouter/auto`
- **WHEN** a client sends `POST /v1/responses` with that model
- **THEN** the service does not forward the request to OrcaRouter
