## ADDED Requirements

### Requirement: Configured model aliases are discoverable on /v1/models

When serving `GET /v1/models`, the system SHALL advertise each dashboard-configured
model alias as its own model entry so discovery-only clients (for example Hermes)
can select a neutral alias id that resolves to the real upstream model on chat
requests. Each alias entry MUST set `id` to the alias, `owned_by` to `codex-lb`,
and clone the target model's catalog metadata when the target is present in the
list, or fall back to the sidecar default catalog fields when the target is
unknown. The system MUST NOT override an existing catalog id (matched
case-insensitively), and MUST omit an alias entry whose resolved target is not
visible for the requesting API key.

#### Scenario: Alias with a visible target is listed

- **GIVEN** an alias `alias-gpt` maps to `gpt-5.4` and `gpt-5.4` is visible
- **WHEN** a client calls `GET /v1/models`
- **THEN** the response includes an entry with `id=alias-gpt`
- **AND** that entry has `owned_by=codex-lb`
- **AND** its `context_length` and `capabilities` match the `gpt-5.4` entry

#### Scenario: Alias is hidden when its target is not allowed

- **GIVEN** an API key is restricted to `gpt-5.5` and an alias `alias-gpt` maps to `gpt-5.4`
- **WHEN** the key calls `GET /v1/models`
- **THEN** the response does not include `gpt-5.4`
- **AND** the response does not include `alias-gpt`

### Requirement: Custom alias catalog overrides the advertised context window

The system SHALL patch an alias's `GET /v1/models` entry with a custom catalog
context window when the configured alias has a catalog entry with a positive
integer `context_length`, advertising the configured window in `context_length`,
`contextLength`, and `capabilities.context_length`, and, when the entry already carries a
`metadata` mapping, in `metadata.context_window` and
`metadata.input_context_window`. Catalog overrides MUST apply only to alias
catalog rows (matched case-insensitively) and MUST NOT change request routing,
upstream limits, or the sidecar wire model. Catalog rows that are not configured
aliases, or that lack a positive integer context length, MUST be dropped on save.

#### Scenario: Alias catalog patches the advertised context length

- **GIVEN** an alias `alias-gpt` maps to `gpt-5.4` (advertised `context_length=272000`)
- **AND** its custom catalog entry sets `context_length=1000000`
- **WHEN** a client calls `GET /v1/models`
- **THEN** the `alias-gpt` entry reports `context_length=1000000`, `contextLength=1000000`, and `capabilities.context_length=1000000`
- **AND** the `gpt-5.4` entry still reports `context_length=272000`

#### Scenario: Orphan catalog rows are dropped on save

- **GIVEN** a custom alias catalog contains a row keyed by an id that is not a configured alias
- **WHEN** the settings are saved
- **THEN** the orphan row is removed from the persisted catalog
