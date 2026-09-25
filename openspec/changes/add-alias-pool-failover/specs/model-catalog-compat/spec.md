## ADDED Requirements

### Requirement: Pool aliases are advertised as one catalog entry

When serving `GET /v1/models`, the system SHALL advertise a multi-target alias
pool as exactly one entry whose `id` is the alias and whose `owned_by` is
`codex-lb`. The entry MUST clone the catalog metadata of the first pool target,
in pool order, that is present in the list, and MUST fall back to the sidecar
default catalog fields when no target is present. The entry MUST be omitted only
when no target of the pool is visible for the requesting API key. The existing
rule that an alias never overrides an existing catalog id (case-insensitive)
applies unchanged. `custom_alias_catalog` overlays apply to pool alias entries
exactly as they apply to single-target alias entries.

This refines the alias discovery behavior introduced by
`add-discoverable-model-aliases`; a single-target pool is advertised exactly as
that change specifies.

#### Scenario: Pool alias clones the first present target

- **GIVEN** `pooled/glm-5.3` has targets `["orcarouter/z-ai/glm-5.3", "or-z-ai/glm-5.3"]`
- **AND** only `or-z-ai/glm-5.3` is present in the catalog list
- **WHEN** a client calls `GET /v1/models`
- **THEN** the response includes exactly one entry with `id=pooled/glm-5.3`
- **AND** its `context_length` matches the `or-z-ai/glm-5.3` entry

#### Scenario: Pool alias is listed when any target is visible

- **GIVEN** an API key is restricted to `pooled/glm-5.3` and `or-z-ai/glm-5.3`
- **AND** `pooled/glm-5.3` has targets `["orcarouter/z-ai/glm-5.3", "or-z-ai/glm-5.3"]`
- **WHEN** the key calls `GET /v1/models`
- **THEN** the response includes `pooled/glm-5.3`
- **AND** the response does not include `orcarouter/z-ai/glm-5.3`

#### Scenario: Pool alias is hidden when no target is visible

- **GIVEN** an API key is restricted to `gpt-5.5`
- **AND** `pooled/glm-5.3` has two targets, neither of which is `gpt-5.5`
- **WHEN** the key calls `GET /v1/models`
- **THEN** the response does not include `pooled/glm-5.3`

#### Scenario: Catalog overlay applies to a pool alias

- **GIVEN** `pooled/glm-5.3` has a `custom_alias_catalog` entry with `context_length=200000`
- **WHEN** a client calls `GET /v1/models`
- **THEN** the `pooled/glm-5.3` entry reports `context_length=200000`
