## ADDED Requirements

### Requirement: Add Ollama dashboard settings safely

Migrations MUST add Ollama sidecar settings with defaults and preserve existing dashboard settings. The new dashboard settings fields MUST include enabled state, base URL, encrypted API key, model prefixes, full models, connect timeout, request timeout, model cache TTL, last health status, last health message, last checked timestamp, and last model count.

The migration MUST provide a downgrade that removes only the Ollama sidecar fields and MUST sit on the current intended Alembic parent revision.

#### Scenario: Existing settings survive upgrade

- **GIVEN** a database has an existing dashboard settings row
- **WHEN** the Ollama sidecar migration is applied
- **THEN** the existing settings remain unchanged
- **AND** Ollama fields are present with disabled/default values

#### Scenario: Downgrade removes Ollama fields

- **GIVEN** the Ollama sidecar migration has been applied
- **WHEN** the migration is downgraded
- **THEN** the Ollama sidecar settings columns are removed
- **AND** non-Ollama dashboard settings columns remain
