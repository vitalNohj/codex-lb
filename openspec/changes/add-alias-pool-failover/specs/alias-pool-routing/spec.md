## ADDED Requirements

### Requirement: Model aliases resolve to an ordered target pool

The system SHALL store each dashboard model alias as an ordered list of one or
more target model ids (`{alias: {"targets": [model, ...]}}`) and SHALL resolve a
requested alias to that ordered tuple. An alias with exactly one target MUST
behave identically to a legacy single-target alias. A requested model that is
not an alias MUST resolve to a one-element tuple containing itself. Alias
matching MUST remain case-insensitive on the alias key.

The alias id is an opaque client-facing name. The system MUST NOT treat any
alias prefix (including `pooled/`) as reserved, and the sidecar route resolver
MUST NOT match alias ids.

#### Scenario: Multi-target alias resolves in order

- **GIVEN** the alias `pooled/glm-5.3` has targets `["orcarouter/z-ai/glm-5.3", "or-z-ai/glm-5.3"]`
- **WHEN** a request names `model=pooled/glm-5.3`
- **THEN** the alias resolves to `("orcarouter/z-ai/glm-5.3", "or-z-ai/glm-5.3")`

#### Scenario: Single-target alias is unchanged

- **GIVEN** the alias `custom_r1` has targets `["cc/claude-opus-4-8"]`
- **WHEN** a request names `model=custom_r1`
- **THEN** the alias resolves to `("cc/claude-opus-4-8",)`
- **AND** the request is dispatched exactly as a request for `cc/claude-opus-4-8`

#### Scenario: Unaliased model resolves to itself

- **GIVEN** no alias named `orcarouter/auto` exists
- **WHEN** a request names `model=orcarouter/auto`
- **THEN** the resolution is `("orcarouter/auto",)`

### Requirement: Legacy alias values are accepted and normalized

The alias loader SHALL accept both the legacy `{alias: "target"}` value shape
and the pool shape `{alias: {"targets": [...]}}`, normalizing a string value to a
one-element pool. The settings API SHALL accept either shape on write and SHALL
always return the pool shape. Blank aliases, blank targets, and non-string
targets MUST be dropped; aliases MUST be de-duplicated case-insensitively.

#### Scenario: Legacy string value is read as a one-element pool

- **GIVEN** `model_aliases_json` contains `{"custom_r1": "cc/claude-opus-4-8"}`
- **WHEN** the alias map is loaded
- **THEN** `custom_r1` resolves to `("cc/claude-opus-4-8",)`

#### Scenario: Settings API returns the pool shape

- **GIVEN** an operator writes `model_aliases={"custom_r1": "cc/claude-opus-4-8"}`
- **WHEN** the settings are read back
- **THEN** `model_aliases.custom_r1` equals `{"targets": ["cc/claude-opus-4-8"]}`

### Requirement: Pool definitions are validated on save

On settings save the system MUST reject, with a validation error that names the
alias and the offending target, any alias pool that:

- has no targets;
- repeats a target (case-insensitive);
- lists a target that is itself a configured alias;
- has two or more targets and lists any target that resolves to the native
  Codex path or to a sidecar provider that is not pool-capable;
- exceeds 16 targets, or has an alias or target longer than 256 characters.

Pool-capable providers are `orcarouter`, `openrouter`, and every
`openai_compat:{uuid}` endpoint. A one-target pool MAY target any model an
alias could target before this change, including native Codex models.

Only what a save changes is validated. Every save carries the whole alias map,
so an alias whose targets equal the stored ones MUST NOT be re-validated, and
an alias-to-alias link MUST be rejected only when the save creates it. A target
owned by an integration that is turned off MUST be judged by that integration
when no enabled integration routes it, so turning an integration off never
fails a save; the proxy skips such a target at request time.

#### Scenario: Unrelated save keeps a stored legacy alias chain

- **GIVEN** the stored aliases are `fast -> ["gpt-5.4"]` and `gpt-5.4 -> ["cc/claude"]`, carried over from the legacy shape
- **WHEN** the operator saves an unrelated setting and the alias map is sent back unchanged
- **THEN** the save succeeds

#### Scenario: Turning off an integration a pool uses

- **GIVEN** `pooled/glm-5.3` has targets `["orcarouter/z-ai/glm-5.3", "z-ai/glm-5.3"]`
- **WHEN** the operator turns OrcaRouter off
- **THEN** the save succeeds and the pool is unchanged
- **AND** a request for `pooled/glm-5.3` is served by OpenRouter without an OrcaRouter attempt

#### Scenario: Alias chain is rejected

- **GIVEN** the alias `a` has targets `["b"]` and `b` is a configured alias
- **WHEN** the operator saves
- **THEN** the save is rejected with an error naming alias `a` and target `b`

#### Scenario: Non-pool-capable member of a multi-target pool is rejected

- **GIVEN** CLIProxyAPI owns the `cc/` prefix
- **AND** the operator defines `pooled/glm-5.3` with targets `["orcarouter/z-ai/glm-5.3", "cc/glm-5.3"]`
- **WHEN** the operator saves
- **THEN** the save is rejected with an error naming `cc/glm-5.3` and the provider `claude`

#### Scenario: One-target pool may target any provider

- **GIVEN** the operator defines `custom_r1` with targets `["cc/claude-opus-4-8"]`
- **WHEN** the operator saves
- **THEN** the save succeeds

#### Scenario: Duplicate target is rejected

- **GIVEN** the operator defines an alias with targets `["or-z-ai/glm-5.3", "OR-z-ai/glm-5.3"]`
- **WHEN** the operator saves
- **THEN** the save is rejected as a duplicate target

### Requirement: Chat completions fail over across pool targets before commit

For `POST /v1/chat/completions` whose requested model is an alias with two or
more targets, the system SHALL attempt targets in pool order. An attempt MUST be
abandoned in favor of the next target only when the upstream failure is
retryable **and** no byte of the response has been sent to the client.
Retryable failures are: transport errors and timeouts, upstream 401, 402, 403,
408, 429, and 5xx statuses. All other failures MUST be returned to the client
exactly as the single-provider path returns them, and later targets MUST NOT be
called.

A target whose provider retries a provider failure once (HTTP status 500 or
above before any byte is sent, per `chat-completions-compat`) MUST make that
retry before the attempt is classified, and MUST be abandoned only when the
retry also failed retryably. Other retryable failures MUST fail over without a
same-target retry.

When every target has been attempted and failed, the system MUST return the
last attempt's client-facing error and MUST include the response header
`X-Codex-LB-Pool-Attempts` carrying the number of targets attempted.

A cursor-compat request whose attempt fails with an upstream context-length
error MUST return the synthetic context-limit completion and MUST NOT fail over.

#### Scenario: 402 on the first target fails over to the second

- **GIVEN** `pooled/glm-5.3` has targets `["orcarouter/z-ai/glm-5.3", "or-z-ai/glm-5.3"]`
- **AND** OrcaRouter returns HTTP 402 for its target
- **WHEN** a client posts a streaming chat completion with `model=pooled/glm-5.3`
- **THEN** OpenRouter receives a request for `z-ai/glm-5.3`
- **AND** the client receives a `200 text/event-stream` response from OpenRouter
- **AND** the client never observes the 402

#### Scenario: 400 on the first target is returned, not failed over

- **GIVEN** the same pool
- **AND** OrcaRouter returns HTTP 400 for its target
- **WHEN** a client posts a chat completion with `model=pooled/glm-5.3`
- **THEN** the client receives the OrcaRouter 400 error envelope
- **AND** OpenRouter receives no request

#### Scenario: All targets fail

- **GIVEN** the same pool
- **AND** OrcaRouter returns HTTP 402 and OpenRouter returns HTTP 503
- **WHEN** a client posts a chat completion with `model=pooled/glm-5.3`
- **THEN** the client receives the OpenRouter 503 error envelope
- **AND** the response carries `X-Codex-LB-Pool-Attempts: 2`

#### Scenario: Provider failure is retried on the target before failover

- **GIVEN** the same pool
- **AND** OrcaRouter returns HTTP 503 for its target on both calls
- **WHEN** a client posts a chat completion with `model=pooled/glm-5.3`
- **THEN** OrcaRouter receives two requests
- **AND** OpenRouter serves the request
- **AND** the response carries `X-Codex-LB-Pool-Attempts: 2`

#### Scenario: Non-streaming failover

- **GIVEN** the same pool and OrcaRouter returns HTTP 429
- **WHEN** a client posts a non-streaming chat completion with `model=pooled/glm-5.3`
- **THEN** the client receives a `200` chat completion produced by OpenRouter

#### Scenario: Cursor context-length error wins over failover

- **GIVEN** the same pool and a cursor-compat client
- **AND** OrcaRouter returns a context-length error for its target
- **WHEN** the client posts a chat completion with `model=pooled/glm-5.3`
- **THEN** the client receives the synthetic context-limit completion
- **AND** OpenRouter receives no request

### Requirement: A target that cannot be attempted receives nothing

OrcaRouter and OpenRouter authenticate every request. When either is enabled
without a usable API key (never set, cleared, or failed to decrypt), the system
MUST NOT build or send a request to it: the caller's prompt would leave the
process, and the upstream can only refuse it. A request routed to such an
integration outside a pool MUST be refused locally with HTTP 503, error code
`orcarouter_not_configured` or `openrouter_not_configured`, and `Retry-After: 60`,
and its usage reservation MUST be released. An `openai_compat:{uuid}` endpoint
MAY have no API key; it is sent requests as configured.

Inside a pool, a target without a usable API key, and a target whose integration
no longer routes it, MUST be skipped before anything is sent to it and the loop
MUST continue. A skipped target MUST NOT enter a cooldown, because no upstream
was contacted, and MUST NOT count toward `X-Codex-LB-Pool-Attempts` or
`pool_attempts`, which count the targets the request was sent to. When no target
of a pool can be attempted, the system MUST return HTTP 503 with error code
`alias_pool_unavailable`, `Retry-After: 60`, and `X-Codex-LB-Pool-Attempts: 0`,
and MUST release the reservation.

#### Scenario: A keyless integration refuses locally

- **GIVEN** OrcaRouter is enabled with no API key
- **WHEN** a client posts a chat completion with `model=orcarouter/z-ai/glm-5.3`
- **THEN** OrcaRouter receives no request
- **AND** the client receives HTTP 503 with error code `orcarouter_not_configured`

#### Scenario: A pool skips a keyless target

- **GIVEN** `pooled/glm-5.3` has targets `["orcarouter/z-ai/glm-5.3", "z-ai/glm-5.3"]`
- **AND** OrcaRouter is enabled with no API key and OpenRouter has one
- **WHEN** a client posts a chat completion with `model=pooled/glm-5.3`
- **THEN** OrcaRouter receives no request
- **AND** OpenRouter serves the request
- **AND** the response carries `X-Codex-LB-Pool-Attempts: 1`
- **AND** `orcarouter/z-ai/glm-5.3` is not cooling

#### Scenario: No target can be attempted

- **GIVEN** the same pool and neither integration has an API key
- **WHEN** a client posts a chat completion with `model=pooled/glm-5.3`
- **THEN** no upstream receives a request
- **AND** the client receives HTTP 503 with error code `alias_pool_unavailable`
- **AND** the response carries `X-Codex-LB-Pool-Attempts: 0`

### Requirement: Streaming dispatch on pool-capable providers opens upstream before committing the response

For `orcarouter`, `openrouter`, and `openai_compat:{uuid}` chat streaming, the
system SHALL perform the upstream POST and observe the upstream status before
constructing the client `StreamingResponse`. An upstream status of 400 or above
MUST surface as a provider error before any client status is committed. This
MUST hold on the single-target path as well as inside a pool so that both paths
share one dispatch implementation.

#### Scenario: Upstream 5xx on a streaming request yields a JSON error, not an SSE error frame

- **GIVEN** OpenRouter returns HTTP 502 to the chat completions POST
- **WHEN** a client posts a streaming chat completion for an OpenRouter model
- **THEN** the client receives an HTTP 502 JSON error response
- **AND** no `text/event-stream` bytes are sent

### Requirement: Failed pool targets enter a cooldown

When a pool attempt fails with a retryable failure the system SHALL place that
target string in a process-local cooldown: 30 minutes for 402; the upstream
`Retry-After` (capped at one hour) or 60 seconds for 429; 60 seconds otherwise.
Subsequent pool resolutions MUST skip targets whose cooldown has not expired.
When every target of a pool is cooling, the system MUST attempt the target whose
cooldown expires soonest rather than failing the request. A successful attempt
MUST clear that target's cooldown. Cooldowns MUST be keyed by target string, not
by provider.

#### Scenario: Cooled target is skipped on the next request

- **GIVEN** `orcarouter/z-ai/glm-5.3` failed with 402 ten seconds ago
- **WHEN** a client posts a chat completion with `model=pooled/glm-5.3`
- **THEN** the first upstream request goes to OpenRouter
- **AND** OrcaRouter receives no request

#### Scenario: All targets cooling still attempts one

- **GIVEN** both targets of `pooled/glm-5.3` are cooling and OpenRouter's cooldown expires first
- **WHEN** a client posts a chat completion with `model=pooled/glm-5.3`
- **THEN** OpenRouter receives the request

#### Scenario: Cooldown is per target, not per provider

- **GIVEN** `orcarouter/z-ai/glm-5.3` is cooling
- **WHEN** a client posts a chat completion with `model=orcarouter/auto`
- **THEN** OrcaRouter receives the request

#### Scenario: Success clears cooldown

- **GIVEN** `orcarouter/z-ai/glm-5.3` is cooling and is attempted as the soonest-to-expire target
- **WHEN** OrcaRouter returns 200
- **THEN** the target is no longer cooling

### Requirement: Pool target health is observable

The system SHALL expose `GET /api/settings/alias-pools/health`, protected by
dashboard authentication, returning for every configured alias and target the
state `healthy` or `cooling`, the cooldown expiry, the last upstream status, and
the last sanitized error message. Each attempt SHALL emit one structured log
line `alias_pool_attempt` with `request_id`, `alias`, `target`, `attempt`, and
`outcome` in `served`, `failover`, `rejected`, `skipped_cooling`. A `rejected`
line MUST carry a `reason` of `access`, `unroutable`, or `not_configured`, and
its `attempt` MUST be `0`, because a rejected target is not sent the request.

#### Scenario: Health reflects a cooling target

- **GIVEN** `orcarouter/z-ai/glm-5.3` failed with 402
- **WHEN** the dashboard calls `GET /api/settings/alias-pools/health`
- **THEN** the entry for `pooled/glm-5.3` -> `orcarouter/z-ai/glm-5.3` has `state=cooling`, `last_status=402`, and a non-null `until`

### Requirement: Pool requests are metered and logged against the alias

For a pool request the system SHALL validate API-key access on the alias and
every target, then enforce request limits and take the usage reservation once,
against the alias id, before the first attempt. A request refused on access
holds no reservation. The reservation MUST be carried across failed-over attempts and
settled or released by the attempt that terminates the request, using that
target's provider settlement. Cost resolution MUST use the serving target's
provider and effective model, never the alias, so the price table lookup is the
same one the target would hit if requested directly. The request log row MUST
record `model` as the alias, `upstream_model` as the target that produced the
response (or the last target attempted on total failure), and `pool_attempts`
as the number of attempts. Time spent in failed-over attempts MUST be accumulated in
`latency_queue_ms` and MUST NOT shift `latency_ms` or `latency_first_token_ms`.
Non-pool requests MUST leave `upstream_model` and `pool_attempts` null.

#### Scenario: Log row after a failover

- **GIVEN** OrcaRouter returned 402 and OpenRouter served the request
- **WHEN** the request completes
- **THEN** the request log row has `model=pooled/glm-5.3`, `upstream_model=or-z-ai/glm-5.3`, `pool_attempts=2`
- **AND** `cost_usd` is settled from OpenRouter's usage

#### Scenario: Legacy alias leaves pool columns null

- **GIVEN** `custom_r1` has a single target
- **WHEN** a request for `custom_r1` completes
- **THEN** the request log row has `upstream_model=null` and `pool_attempts=null`

### Requirement: Responses endpoints use the first pool target only

`POST /v1/responses` and other Responses-shaped entry points SHALL resolve a
pool alias to its first target and SHALL NOT fail over across targets in this
change.

#### Scenario: Responses request on a pool alias

- **GIVEN** `pooled/glm-5.3` has two targets
- **WHEN** a client posts `POST /v1/responses` with `model=pooled/glm-5.3`
- **THEN** the request is handled as a request for `orcarouter/z-ai/glm-5.3`
