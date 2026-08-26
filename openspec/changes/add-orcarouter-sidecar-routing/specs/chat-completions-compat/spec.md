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

### Requirement: Request logs record the OrcaRouter billed cost

OrcaRouter chat requests MUST opt in to the billed figure by sending `X-OrcaRouter-Include-Cost: true`. When OrcaRouter returns `usage.cost_usd`, the request log MUST persist that value as `cost_usd`.

The stored cost MUST be the amount OrcaRouter reports, never re-derived from `/models` list prices: the billed amount folds in tiered pricing, peak multipliers, cache ratios, and minimum-quota rounding. When the field is absent, `cost_usd` MUST stay null rather than be inferred as zero.

OpenRouter's `usage.cost` MUST keep precedence so OpenRouter behavior is unchanged.

#### Scenario: Non-streaming billed cost reaches the request log

- **GIVEN** OrcaRouter returns `usage.cost_usd`
- **WHEN** a client completes a non-streaming OrcaRouter chat request
- **THEN** the request log `cost_usd` equals the reported value

#### Scenario: Streaming billed cost reaches the request log

- **GIVEN** the trailing usage frame carries `usage.cost_usd`
- **WHEN** a client completes a streaming OrcaRouter chat request
- **THEN** the request log `cost_usd` equals the reported value

#### Scenario: Absent cost is not treated as free

- **GIVEN** OrcaRouter omits `usage.cost_usd`
- **WHEN** the request completes
- **THEN** the request log `cost_usd` is null
