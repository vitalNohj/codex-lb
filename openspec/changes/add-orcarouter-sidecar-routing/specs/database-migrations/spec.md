## ADDED Requirements

### Requirement: Idempotent OrcaRouter dashboard settings migration

Alembic MUST add OrcaRouter dashboard settings columns with upgrade and downgrade coverage. The revision MUST parent the live Alembic head. Upgrade MUST add columns only when missing. Downgrade MUST drop only the new OrcaRouter columns.

New columns MUST include enabled (default false), base URL `https://api.orcarouter.ai/v1`, encrypted API key, prefixes JSON default `[{"prefix":"orcarouter/","strip":false}]`, full models JSON default `[]`, timeouts, cache TTL, health fields, and default reasoning effort.

#### Scenario: Upgrade adds OrcaRouter columns on the live head

- **GIVEN** the database is at the live Alembic head
- **WHEN** the OrcaRouter settings migration upgrades
- **THEN** `dashboard_settings` has the new `orcarouter_sidecar_*` columns
- **AND** prefix JSON defaults to `[{"prefix":"orcarouter/","strip":false}]`
- **AND** enabled defaults to false

#### Scenario: Downgrade drops only OrcaRouter columns

- **GIVEN** the OrcaRouter settings migration has been applied
- **WHEN** the migration downgrades
- **THEN** only the new `orcarouter_sidecar_*` columns are removed
- **AND** existing dashboard settings columns remain
