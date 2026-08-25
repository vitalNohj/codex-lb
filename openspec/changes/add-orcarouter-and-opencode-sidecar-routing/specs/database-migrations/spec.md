## ADDED Requirements

### Requirement: Add OrcaRouter, OpenCode Zen, and OpenCode Free dashboard settings safely

Migrations MUST add OrcaRouter, OpenCode Zen, and OpenCode Free sidecar settings with defaults and preserve existing dashboard settings. The new dashboard settings fields for each integration MUST include enabled state, base URL, encrypted API key, model prefixes, full models, connect timeout, request timeout, model cache TTL, last health status, last health message, last checked timestamp, last model count, and default reasoning effort.

The migration MUST seed OrcaRouter prefixes to `orcarouter/` with strip disabled, OpenCode Zen prefixes to `opencode-zen/` with strip enabled, and OpenCode Free prefixes to `oc/` with strip enabled. The migration MUST NOT seed prefix `opencode/` on OpenCode Free. The migration MUST provide a downgrade that removes only these sidecar fields and MUST sit on the current intended Alembic parent revision.

#### Scenario: Existing settings survive upgrade

- **GIVEN** a database has an existing dashboard settings row
- **WHEN** the OrcaRouter, OpenCode Zen, and OpenCode Free sidecar migration is applied
- **THEN** the existing settings remain unchanged
- **AND** OrcaRouter fields are present with disabled/default values including prefix `orcarouter/` with strip disabled
- **AND** OpenCode Zen fields are present with disabled/default values including prefix `opencode-zen/` with strip enabled
- **AND** OpenCode Free fields are present with disabled/default values including prefix `oc/` with strip enabled
- **AND** OpenCode Free prefixes do not include `opencode/`

#### Scenario: Downgrade removes only the new sidecar fields

- **GIVEN** the OrcaRouter, OpenCode Zen, and OpenCode Free sidecar migration has been applied
- **WHEN** the migration is downgraded
- **THEN** the OrcaRouter, OpenCode Zen, and OpenCode Free sidecar settings columns are removed
- **AND** non-related dashboard settings columns remain
