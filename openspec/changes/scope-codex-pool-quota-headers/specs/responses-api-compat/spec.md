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

A subscription-backed summary MUST cover the accounts eligible for the model, tier and API key. It MUST count eligible accounts with missing samples as zero measured use at nominal window capacity. Plans without the window add no capacity. The proxy MUST omit the window summary if its weighted value would reach 100% without all eligible accounts having a full, unexpired sample.

#### Scenario: No short-window sample for one eligible account

- **WHEN** one account's short window is full but another eligible account lacks a short-window sample
- **THEN** the short-window usage header is omitted or reports less than 100%
