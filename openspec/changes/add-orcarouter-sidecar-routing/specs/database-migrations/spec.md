## ADDED Requirements

### Requirement: Idempotent OrcaRouter dashboard settings migration

Alembic MUST add OrcaRouter dashboard settings columns with upgrade and downgrade coverage. The revision MUST parent the live Alembic head. Upgrade MUST add columns only when missing. Downgrade MUST drop only the new OrcaRouter columns.

New columns MUST include enabled (default false), base URL `https://api.orcarouter.ai/v1`, encrypted API key, prefixes JSON, full models JSON default `[]`, timeouts, cache TTL, health fields, and default reasoning effort.

The prefix seed `[{"prefix":"orcarouter/","strip":false}]` MUST apply only to a fresh install. Existing `dashboard_settings` rows MUST receive `[]`, because prefix uniqueness is enforced regardless of enabled state and a backfilled `orcarouter/` would collide with a deployment where OmniRoute already owns that prefix. The seeded value MUST be valid, parseable JSON.

#### Scenario: Upgrade adds OrcaRouter columns on the live head

- **GIVEN** the database is at the live Alembic head
- **WHEN** the OrcaRouter settings migration upgrades
- **THEN** `dashboard_settings` has the new `orcarouter_sidecar_*` columns
- **AND** enabled defaults to false

#### Scenario: Fresh install seeds a parseable OrcaRouter prefix

- **GIVEN** the migration runs against a database it creates
- **WHEN** the upgrade completes
- **THEN** prefix JSON parses to exactly `orcarouter/` with strip disabled

#### Scenario: Existing deployment is not given an active prefix

- **GIVEN** a `dashboard_settings` row exists whose OmniRoute prefixes include `orcarouter/`
- **WHEN** the OrcaRouter settings migration upgrades
- **THEN** the OrcaRouter prefix JSON is `[]`
- **AND** a later settings update is not rejected with `sidecar_routing_conflict`

#### Scenario: Downgrade drops only OrcaRouter columns

- **GIVEN** the OrcaRouter settings migration has been applied
- **WHEN** the migration downgrades
- **THEN** only the new `orcarouter_sidecar_*` columns are removed
- **AND** existing dashboard settings columns remain
