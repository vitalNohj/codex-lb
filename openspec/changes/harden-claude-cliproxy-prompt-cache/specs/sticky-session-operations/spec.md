# sticky-session-operations (delta)

## ADDED Requirements

### Requirement: Claude requests reach CLIProxyAPI only with a credential prefix

A Claude model is one whose name, without any routing prefix, contains `claude`. A Claude request MUST be sent to CLIProxyAPI only under the prefixed model name of the credential the router selected. When the router cannot name one, the request MUST be refused and MUST NOT be sent under the plain model name. This applies when capacity routing is off, when no prefixed credential serves the model, and when selection fails. Other CLIProxyAPI model families MUST keep the plain name in those cases.

#### Scenario: No prefixed credential for a Claude model

- **GIVEN** CLIProxyAPI capacity routing is enabled and no prefixed credential serves the requested Claude model
- **WHEN** a Claude chat request arrives, streamed or not
- **THEN** CLIProxyAPI receives no request
- **AND** the route outcome is recorded as `refused`

#### Scenario: Capacity routing is off

- **GIVEN** CLIProxyAPI capacity routing is disabled
- **WHEN** a Claude chat request arrives
- **THEN** the request is refused
- **AND** a request for a non-Claude CLIProxyAPI model is still sent under its plain name

### Requirement: A refused Claude request is answered without breaking poller holds

A refused Claude request MUST receive `503` with error code `cliproxy_claude_route_unavailable`. Its usage reservation MUST be released, and the request MUST be logged with that error code. When every Claude auth is disabled, the existing no-enabled-account answer MUST be returned instead. A poller hold on every Claude auth MUST answer before the refusal: a far hold MUST still answer `429`, and after a near hold the route MUST be tried again.

#### Scenario: The refusal answer

- **GIVEN** a Claude request with no prefixed credential and no poller hold
- **WHEN** it is answered
- **THEN** the client receives `503` with error code `cliproxy_claude_route_unavailable`
- **AND** the reservation is released and the request log carries that error code

#### Scenario: A far hold still answers 429

- **GIVEN** every Claude auth is under a poller hold beyond the wait budget
- **WHEN** a Claude request arrives
- **THEN** the client receives `429`, as before

#### Scenario: A near hold clears and a credential is named

- **GIVEN** every Claude auth is under a poller hold that ends within the wait budget, so no credential is selectable yet
- **WHEN** the hold ends
- **THEN** the route is tried again and the request is sent under the selected credential's prefix

### Requirement: The Claude chat body is append-only across turns

For an unchanged conversation, each turn's chat body to CLIProxyAPI MUST repeat the previous turn's body byte for byte and only append messages. This covers tool definitions and their order, tool-name and tool-call-id rewrites, the system prompt, `reasoning_effort` (including under the operator override), the derived `prompt_cache_key` and the body key order. Per-request client fields such as `metadata` and `user` MUST NOT reach the body.

#### Scenario: A Responses tool session on one credential

- **GIVEN** a five-turn `/v1/responses` tool session for a Claude model
- **WHEN** each turn is forwarded to CLIProxyAPI
- **THEN** every body CLIProxyAPI receives starts with the previous body's messages, unchanged
- **AND** all other fields are identical
- **AND** every turn uses the same credential prefix

#### Scenario: The operator effort override holds while the client changes effort

- **GIVEN** a configured default reasoning effort and a client that sends a different effort, or none, on each turn
- **WHEN** each turn is forwarded
- **THEN** `reasoning_effort` has the override value at the same position on every turn
