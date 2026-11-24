## ADDED Requirements

### Requirement: Account rejection is not pool exhaustion

The proxy MUST use existing safe failover for a pre-output overload or usage rejection. When an account rejection still becomes an HTTP error, the proxy MUST return 429 or 503 with a short `Retry-After` and no account usage or reset metadata. Per-request failover exclusions MUST NOT establish pool exhaustion. Existing replay safety rules still apply.

#### Scenario: A replacement account cannot finish a turn

- **WHEN** one account rejects the turn for overload or quota and safe retry does not succeed
- **AND** the selector has not established exhaustion of the entire eligible pool
- **THEN** the HTTP error has a short `Retry-After` and no Codex usage headers or account reset

#### Scenario: The full eligible pool is exhausted

- **WHEN** account selection proves that the full eligible pool is usage exhausted
- **THEN** the public error keeps HTTP 429 and `usage_limit_reached`
- **AND** any reported reset is the earliest known time at which an eligible account has reset all blocking usage windows

### Requirement: Only subscription-backed routes advertise Codex quota

The proxy MUST NOT attach its Codex pool usage or credits headers to HTTP responses from external model providers.

#### Scenario: A route does not use the Codex account pool

- **WHEN** the request is routed to Claude, Grok, or another external model provider
- **THEN** the response has no Codex pool usage or credits headers

### Requirement: A full usage header requires a full eligible pool

A subscription-backed summary MUST cover the accounts eligible for the model, tier and API key. Missing samples MUST count as unused nominal capacity; plans without the window add no capacity. A weighted estimate alone MUST NOT claim 100% usage. For a streaming request or error response, a 100% header requires a selector-confirmed pool usage error with a matching reset deadline and known window duration.

#### Scenario: No short-window sample for one eligible account

- **WHEN** one account's short window is full but another eligible account lacks a short-window sample
- **THEN** that sample alone does not establish pool exhaustion, and the short-window estimate is omitted or reports less than 100%

#### Scenario: The eligible pool is full across different window lengths

- **WHEN** the selector confirms exhaustion and the proxy has timing for the first eligible account to return
- **THEN** the 100% header reports the reset deadline and duration of the blocking window that releases that account
- **AND** an account with multiple blocking windows cannot return before its last blocking window resets

#### Scenario: A reset credit is ready for automatic redemption

- **WHEN** an eligible account has a credit that the enabled automatic redemption policy can redeem
- **THEN** the proxy omits all 100% usage headers

#### Scenario: A streaming request can fail after HTTP headers are sent

- **WHEN** the proxy starts a stream before its terminal outcome is known
- **THEN** the stream keeps ordinary usage estimates but has no 100% usage header
- **AND** an overload, upstream-unavailable, or incomplete-stream error does not turn the estimate into a pool-exhaustion claim
