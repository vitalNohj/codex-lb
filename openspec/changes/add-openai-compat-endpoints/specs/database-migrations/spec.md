## ADDED Requirements

### Requirement: Idempotent OpenAI-compat endpoints migration

Alembic MUST add `dashboard_settings.openai_compat_endpoints_json` with upgrade and downgrade coverage. The revision MUST parent the live Alembic head (`20260916_010000_add_nvidia_sidecar_dashboard_settings`). Upgrade MUST add the column only when missing. Downgrade MUST drop only that column.

The column MUST be TEXT, NOT NULL, with server default `'[]'`. Existing rows MUST receive `[]`. The seeded value MUST be valid, parseable JSON.

#### Scenario: Upgrade adds the JSON column on the live head

- **GIVEN** the database is at the NVIDIA settings migration
- **WHEN** the OpenAI-compat endpoints migration upgrades
- **THEN** `dashboard_settings` has `openai_compat_endpoints_json`
- **AND** the default value is `[]`

#### Scenario: Existing deployment starts with an empty list

- **GIVEN** a `dashboard_settings` row already exists
- **WHEN** the migration upgrades
- **THEN** `openai_compat_endpoints_json` is `[]`

#### Scenario: Downgrade drops only the new column

- **GIVEN** the OpenAI-compat endpoints migration has been applied
- **WHEN** the migration downgrades
- **THEN** only `openai_compat_endpoints_json` is removed
- **AND** existing dashboard settings columns remain
