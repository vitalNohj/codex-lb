## ADDED Requirements

### Requirement: Idempotent NVIDIA dashboard settings migration

Alembic MUST add NVIDIA dashboard settings columns with upgrade and downgrade coverage. The revision MUST parent the live Alembic head. Upgrade MUST add columns only when missing. Downgrade MUST drop only the new NVIDIA columns.

New columns MUST include enabled (default false), base URL `https://integrate.api.nvidia.com/v1`, encrypted API key, prefixes JSON default `[]`, full models JSON default `[]`, timeouts, cache TTL, health fields, and default reasoning effort.

Existing `dashboard_settings` rows MUST receive empty prefix JSON. The seeded value MUST be valid, parseable JSON.

#### Scenario: Upgrade adds NVIDIA columns on the live head

- **GIVEN** the database is at the live Alembic head
- **WHEN** the NVIDIA settings migration upgrades
- **THEN** `dashboard_settings` has the new `nvidia_sidecar_*` columns
- **AND** enabled defaults to false
- **AND** base URL defaults to `https://integrate.api.nvidia.com/v1`

#### Scenario: Existing deployment is not given an active prefix

- **GIVEN** a `dashboard_settings` row already exists
- **WHEN** the NVIDIA settings migration upgrades
- **THEN** the NVIDIA prefix JSON is `[]`

#### Scenario: Downgrade drops only NVIDIA columns

- **GIVEN** the NVIDIA settings migration has been applied
- **WHEN** the migration downgrades
- **THEN** only the new `nvidia_sidecar_*` columns are removed
- **AND** existing dashboard settings columns remain
