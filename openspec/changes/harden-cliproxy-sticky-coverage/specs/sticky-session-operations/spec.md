# sticky-session-operations (delta)

## ADDED Requirements

### Requirement: CLIProxyAPI credential pins resolve the conversation identity in a fixed order

When CLIProxyAPI capacity routing and sticky threads are enabled, the router MUST resolve one conversation identity per request. It MUST use the first source present: client `prompt_cache_key`, Codex turn-state header, Codex session header, other session header (such as `X-Session-Id`), body session id, then a content-derived key. A per-request id MUST NOT count as a session.

#### Scenario: Session header pins a keyless chat conversation

- **GIVEN** chat requests with no `prompt_cache_key` that carry the same `X-Session-Id`
- **WHEN** the router selects a credential for each turn
- **THEN** every turn is routed to the same credential

#### Scenario: Vendor session headers are recognised

- **GIVEN** a request with `X-Claude-Code-Session-Id`, `X-Session-Affinity` or another `X-<vendor>-Session-Id` header and no `prompt_cache_key`
- **WHEN** the router resolves the conversation identity
- **THEN** the header value is the conversation identity

#### Scenario: Per-request ids do not pin

- **GIVEN** requests that carry only a new `X-Client-Request-Id` on each turn
- **WHEN** the router resolves the conversation identity
- **THEN** the request id is ignored and the content-derived key is used

### Requirement: CLIProxyAPI derived keys reuse the Codex recipe

The router MUST compute the content-derived key with the same recipe as the Codex path's `_derive_prompt_cache_key`. It hashes the model class, the API key id, the instructions and the first user or system content. If a request has no hashable content, the router MUST leave it unpinned and MUST NOT invent a random key. A `prompt_cache_key` that codex-lb derived itself MUST rank as a derived key, below explicit session headers.

#### Scenario: Keyless chat conversation stays on one credential

- **GIVEN** a chat conversation with no `prompt_cache_key` and no session header
- **WHEN** later turns repeat the same system and first user message and append new messages
- **THEN** every turn is routed to the same credential

#### Scenario: Request with nothing to hash stays unpinned

- **GIVEN** a request with no session identity and no user or system content
- **WHEN** the router selects a credential
- **THEN** no pin is written
- **AND** the outcome is recorded as `unpinned_no_key`

### Requirement: The Responses chat bridge preserves the prompt cache key

The Responses-to-chat bridge MUST forward the client's `prompt_cache_key`. If the client sent none and prompt-cache-key derivation is enabled, the bridge MUST derive one before translation. The router MUST read the Responses body session ids (`session_id`, `sessionId`, `metadata.session_id`) before translation, because the chat request does not carry them. A body session id MUST outrank a key the bridge derived.

#### Scenario: Responses body session id outranks a derived key

- **GIVEN** a `/v1/responses` request with `metadata.session_id` and no client `prompt_cache_key`
- **WHEN** the bridge derives a key and routes the request
- **THEN** the conversation is pinned by the body session id

#### Scenario: Responses prompt_cache_key survives the chat bridge

- **GIVEN** a `/v1/responses` request with `prompt_cache_key` routed through the chat provider bridge
- **WHEN** the request is translated to chat completions
- **THEN** the translated request carries the same `prompt_cache_key`
- **AND** every turn of the conversation is routed to the same credential

### Requirement: A transient credential failure keeps the warm pin

A 429, 401 or 403 from a credential whose pin has already served the conversation MUST put that credential in a short in-process cooldown. The request MUST be served from a fallback pin for the same conversation, and the original pin MUST NOT change. Later turns MUST use the same fallback credential during the cooldown and MUST return to the original credential after it. Fallback pins MUST live in an internal key namespace that no client identity can resolve to, so one conversation cannot read or move another conversation's fallback.

#### Scenario: Conversation returns to its warm credential after a 429

- **GIVEN** a conversation pinned to credential A that has served earlier turns
- **WHEN** credential A returns 429 for one turn
- **THEN** that turn is served by another credential B, and the pin stays on A
- **AND** turns during the cooldown are served by B
- **AND** the first turn after the cooldown is served by A again

### Requirement: An unusable or cold credential moves the pin

If the failing request created the pin itself, or the pinned credential is quota-exhausted or otherwise unavailable, the router MUST move the pin to the replacement credential. This also applies while the credential is still cooling down: a cooling pin is kept only while its credential can still serve the model.

#### Scenario: A cooling pin that runs out of quota moves

- **GIVEN** a conversation whose pinned credential A is cooling down after a 429
- **WHEN** credential A is reported quota-exhausted before the cooldown ends
- **THEN** the conversation is pinned to the credential that serves it

#### Scenario: Quota exhaustion moves the pin

- **GIVEN** a conversation pinned to credential A
- **WHEN** credential A is reported quota-exhausted
- **THEN** the conversation is pinned to a credential that can serve it

### Requirement: The first CLIProxyAPI pin is claimed atomically

Pin writes MUST use compare-and-set. A write MUST succeed only if no row exists, the stored credential is the one the writer read or is writing, or the stored row is older than the pin lifetime. A writer that loses MUST re-read the winning credential and route to it. Pin deletion MUST be conditional on the credential the writer read.

#### Scenario: Concurrent first turns share one credential

- **GIVEN** several first-turn requests of one conversation arrive at the same time with no existing pin
- **WHEN** each request selects a credential
- **THEN** all of them are routed to the credential that won the first claim
- **AND** exactly one pin row exists for the conversation

### Requirement: Expired CLIProxyAPI pins are purged

The sticky cleanup loop MUST delete `cliproxy_sticky_sessions` rows older than the pin lifetime. It MUST use the same lifetime that lookups use and MUST leave live pins untouched.

#### Scenario: Cleanup removes only expired pins

- **WHEN** the cleanup loop runs
- **THEN** CLIProxyAPI pins older than the lifetime are deleted
- **AND** newer pins remain

### Requirement: CLIProxyAPI route outcomes are observable

Every CLIProxyAPI route decision MUST increment `codex_lb_cliproxy_route_outcome_total` with labels `outcome` and `key_source`, and MUST log one `cliproxy_route_outcome` line.

#### Scenario: Route outcomes are labelled

- **WHEN** the router selects, keeps, rebinds, skips or fails open on a credential
- **THEN** `outcome` is one of `selected`, `sticky`, `rebind`, `unpinned_no_key`, `fail_open` or `no_candidate`
- **AND** `key_source` is one of `prompt_cache_key`, `turn_state`, `session_header`, `body_session_id`, `derived`, `disabled` or `none`

### Requirement: Unmeasured CLIProxyAPI credentials score neutrally

An unmeasured credential MUST score as half used, so it is neither preferred over measured idle credentials nor starved. When no prefixed credential can serve the requested model, the router MUST log a warning, throttled per model.

#### Scenario: Unmeasured credential is not starved

- **GIVEN** an unmeasured credential and a credential at 80% usage
- **WHEN** the router selects a credential for a new conversation
- **THEN** the unmeasured credential is chosen
