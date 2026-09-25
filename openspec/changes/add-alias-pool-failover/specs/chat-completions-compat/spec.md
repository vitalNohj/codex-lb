## ADDED Requirements

### Requirement: Chat completions dispatch pool aliases through the failover loop

For `POST /v1/chat/completions`, when the requested model resolves to an alias
pool with two or more targets, the system SHALL dispatch through the alias pool
failover loop defined in `alias-pool-routing` instead of the single-provider
dispatch chain. When the requested model resolves to exactly one target (a
single-target alias or an unaliased model) the system SHALL dispatch that target
through the same provider dispatch implementation the loop uses, so a
single-target request and a pool attempt share one code path per provider.

Access validation on the requested alias id MUST still run before resolution,
and access MUST be re-validated on each target's effective model before that
target is attempted. A target the API key may not use MUST be skipped as a
non-retryable rejection of that target, and the loop MUST continue to the next
target.

#### Scenario: Restricted key allowed on the alias but not on the first target

- **GIVEN** an API key whose allowed models are `pooled/glm-5.3` and `or-z-ai/glm-5.3`
- **AND** `pooled/glm-5.3` has targets `["orcarouter/z-ai/glm-5.3", "or-z-ai/glm-5.3"]`
- **WHEN** the key posts a chat completion with `model=pooled/glm-5.3`
- **THEN** OrcaRouter receives no request
- **AND** OpenRouter serves the request

#### Scenario: Restricted key allowed on no target

- **GIVEN** an API key whose allowed models are only `pooled/glm-5.3`
- **AND** the pool's targets are not in the allowlist
- **WHEN** the key posts a chat completion with `model=pooled/glm-5.3`
- **THEN** the request is rejected as not having access to the model
- **AND** no upstream receives a request

#### Scenario: Unaliased OrcaRouter model uses the shared dispatch path

- **GIVEN** OrcaRouter is enabled and owns `orcarouter/`
- **WHEN** a client posts a streaming chat completion with `model=orcarouter/auto`
- **THEN** the request is served by OrcaRouter through the open-before-commit dispatch
- **AND** the request log row has `upstream_model=null` and `pool_attempts=null`

### Requirement: Alias rewrite preserves the client-facing alias for metering

When a chat request's model is an alias, the system MUST keep the alias id as
the value used for API-key model validation, request-limit reservation, and the
request log `model` column, and MUST use the resolved target for sidecar route
resolution, the upstream wire model, and cost resolution. This supersedes the
previous behavior of rewriting `payload.model` to the target before metering.
An API-key limit whose `model_filter` names the alias MUST apply to requests
for that alias; a limit whose `model_filter` names a target MUST NOT apply to
requests that reach the target through an alias.

#### Scenario: Single-target alias is logged under the alias

- **GIVEN** `custom_r1` has targets `["cc/claude-opus-4-8"]`
- **WHEN** a request for `custom_r1` completes
- **THEN** the request log row has `model=custom_r1`
- **AND** the CLIProxyAPI wire model is `claude-opus-4-8`
- **AND** `cost_usd` is resolved from the `claude` provider price for `claude-opus-4-8`

#### Scenario: Model-filtered limit keyed on the alias applies

- **GIVEN** an API key has a request limit with `model_filter=pooled/glm-5.3`
- **WHEN** the key posts a chat completion with `model=pooled/glm-5.3`
- **THEN** the limit is enforced for the request
