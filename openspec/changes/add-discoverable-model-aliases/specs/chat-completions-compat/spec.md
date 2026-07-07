## ADDED Requirements

### Requirement: Alias access is gated before alias resolution

For `POST /v1/chat/completions`, the system SHALL validate the requesting API
key's access against the requested model id before resolving any dashboard
model alias, and MUST also validate access against the resolved/effective target
model after resolution. A restricted API key MAY allow an alias id directly, and
MUST NOT be able to reach a disallowed target model through an alias.

#### Scenario: Restricted key allowed on the alias id

- **GIVEN** an API key whose allowed models include the alias id `alias-gpt`
- **WHEN** the key posts a chat completion with `model=alias-gpt`
- **THEN** the pre-resolution access check passes on `alias-gpt`
- **AND** the request resolves to the alias target and proceeds

#### Scenario: Restricted key cannot reach a disallowed target via alias

- **GIVEN** an API key that does not allow the alias target model
- **WHEN** the key posts a chat completion using an alias that resolves to that target
- **THEN** the request is rejected as not having access to the model
