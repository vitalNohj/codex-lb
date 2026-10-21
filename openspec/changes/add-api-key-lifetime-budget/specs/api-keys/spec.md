# api-keys (delta)

## ADDED Requirements

### Requirement: One-time (lifetime) API key budgets

The system SHALL accept `lifetime` as an API key limit window. A lifetime limit SHALL never reset: the scheduled reset sweep, the lazy reset at admission, and a `resetUsage` update MUST leave its `current_value` unchanged. Its stored `reset_at` SHALL be a fixed far-future sentinel, and every API response SHALL report its reset time as `null`. Raising `maxValue` SHALL be the way to add budget.

A lifetime limit added to an existing key SHALL start at the key's successful usage since the key was created. The limit window module MUST raise an error for an unknown window rather than give it another window's reset.

When a lifetime limit is exhausted, a proxied request SHALL be refused with `402` and error code `insufficient_quota`, with a message that says the lifetime budget is exhausted and carries no reset time. A request already admitted MAY take the counter past `maxValue`; a stream MUST NOT be cut off mid-response because of the budget.

#### Scenario: A lifetime limit never resets

- **GIVEN** a key with a lifetime `cost_usd` limit that has spent part of its budget
- **WHEN** the reset sweep runs at any later time, or a request is admitted, or the admin resets usage
- **THEN** the limit keeps its spend

#### Scenario: Backfill counts prior spend

- **GIVEN** a key that already has successful requests older than any rolling window
- **WHEN** the admin adds a lifetime `cost_usd` limit
- **THEN** the limit starts at the cost of every successful request since the key was created

#### Scenario: An exhausted lifetime budget has no reset time

- **GIVEN** a key whose lifetime `cost_usd` limit is used up
- **WHEN** it sends a proxied request
- **THEN** the response is `402 insufficient_quota` saying the lifetime budget is exhausted, with no reset time
- **AND** `GET /v1/usage` shows the limit with `reset_at: null`

### Requirement: Shared cost budgets refuse unpriced models

A key that is shared (`is_shared`) and has any `cost_usd` limit SHALL refuse a request whose model has no known price on the route that would serve it, with `403` and error code `model_not_priced`, before any usage is reserved or any upstream is contacted. The price check MUST be the one the serving route's settlement uses. An alias pool SHALL be refused unless every routable target is priced. A key that is not shared, or that has no `cost_usd` limit, SHALL serve such a model as before.

#### Scenario: Shared key with a cost budget and an unpriced model

- **GIVEN** a shared key with a lifetime `cost_usd` limit
- **WHEN** it requests a model with no known price
- **THEN** the response is `403 model_not_priced` and nothing is reserved

#### Scenario: Other keys keep serving an unpriced model

- **GIVEN** an unshared key with a `cost_usd` limit, or a shared key with only token limits
- **WHEN** it requests a model with no known price
- **THEN** the request is admitted

### Requirement: Abandoned streams are charged their reservation

When a client abandons a streamed request after the upstream started streaming it, and no final usage arrived, the system SHALL settle the request's reservation at the amount reserved at admission instead of releasing it. A stream abandoned before anything was relayed to the client SHALL still be released. This SHALL hold on the Codex HTTP and WebSocket paths and the CLIProxyAPI chat and native Responses paths.

#### Scenario: Disconnect mid-stream

- **GIVEN** a key with a cost limit and a streamed request whose first events reached the client
- **WHEN** the client disconnects before the response completes
- **THEN** the reservation is finalized at its reserved amount, and the limit keeps that spend

#### Scenario: Disconnect before the stream started

- **GIVEN** a streamed request that has relayed nothing yet
- **WHEN** the client disconnects
- **THEN** the reservation is released
