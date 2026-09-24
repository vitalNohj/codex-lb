## ADDED Requirements

### Requirement: Model restrictions are enforced per pool target

For an alias pool request the model restriction check MUST run on the alias id
before resolution and again on each target, as the provider and model that
target routes to, before the usage reservation is taken. A disallowed target
MUST NOT be attempted and MUST NOT abort the pool; the next target is
considered. If the alias is disallowed the proxy MUST return 403 with code
`model_not_allowed` before any upstream call. If the alias is allowed but every
target is disallowed, the proxy MUST return 403 with code `model_not_allowed`,
no upstream receives a request, and no usage reservation is created. A key with
an enforced model never pools: the enforced model replaces the alias.

#### Scenario: Disallowed first target is skipped

- **GIVEN** a key has `allowed_models: ["pooled/glm-5.3", "or-z-ai/glm-5.3"]`
- **AND** `pooled/glm-5.3` has targets `["orcarouter/z-ai/glm-5.3", "or-z-ai/glm-5.3"]`
- **WHEN** the key sends `POST /v1/chat/completions` with `model: "pooled/glm-5.3"`
- **THEN** OrcaRouter receives no request
- **AND** OpenRouter receives the request

#### Scenario: Alias allowed but no target allowed

- **GIVEN** a key with request limits has `allowed_models: ["pooled/glm-5.3"]`
- **WHEN** the key sends `POST /v1/chat/completions` with `model: "pooled/glm-5.3"`
- **THEN** the proxy returns 403 with code `model_not_allowed`
- **AND** no upstream receives a request
- **AND** no usage reservation is created

#### Scenario: Alias not allowed

- **GIVEN** a key has `allowed_models: ["gpt-5.4"]`
- **WHEN** the key sends `POST /v1/chat/completions` with `model: "pooled/glm-5.3"`
- **THEN** the proxy returns 403 with code `model_not_allowed`
- **AND** no upstream receives a request

### Requirement: Usage reservations span the pool attempt loop

Authenticated API-key Chat Completions for an alias pool MUST create exactly one
usage reservation, against the alias id, before the first outbound call. The
reservation MUST NOT be settled or released by an attempt that fails over. The
attempt that produces the client response MUST finalize it once from that
target's usage and cost, and total failure MUST release it once.

#### Scenario: Failover does not double-reserve or release early

- **GIVEN** an authenticated API key with request limits
- **AND** OrcaRouter returns 402 and OpenRouter returns usage `prompt_tokens=10`, `completion_tokens=5`
- **WHEN** the key sends a chat completion for `pooled/glm-5.3`
- **THEN** exactly one reservation is created for `pooled/glm-5.3`
- **AND** it is finalized once with 10 input tokens and 5 output tokens

#### Scenario: Total failure releases once

- **GIVEN** an authenticated API key with request limits
- **AND** every pool target fails with a retryable failure
- **WHEN** the key sends a chat completion for the pool
- **THEN** the reservation is released exactly once
