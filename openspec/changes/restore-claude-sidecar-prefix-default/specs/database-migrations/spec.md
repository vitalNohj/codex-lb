## MODIFIED Requirements

### Requirement: Startup schema drift guard

After startup migrations report success, the system SHALL verify that the live database schema matches ORM metadata before the application continues normal startup. If drift remains, the system SHALL surface explicit drift details and SHALL apply fail-fast behavior according to configuration instead of silently serving with a divergent schema.

#### Scenario: Startup detects drift with fail-fast enabled

- **GIVEN** startup migrations complete without raising an Alembic upgrade error
- **AND** post-migration schema drift check returns one or more diffs
- **AND** `database_migrations_fail_fast=true`
- **WHEN** application startup continues
- **THEN** the system raises an explicit startup error that includes schema drift context
- **AND** the application does not continue normal startup

#### Scenario: Startup detects drift with fail-fast disabled

- **GIVEN** startup migrations complete without raising an Alembic upgrade error
- **AND** post-migration schema drift check returns one or more diffs
- **AND** `database_migrations_fail_fast=false`
- **WHEN** application startup continues
- **THEN** the system logs the drift details as an error
- **AND** it does not silently suppress the drift context

#### Scenario: Column server defaults match metadata on every backend

- **GIVEN** a database migrated to head on SQLite or PostgreSQL
- **WHEN** the post-migration schema drift check runs
- **THEN** `dashboard_settings.claude_sidecar_model_prefixes_json` has the server default declared in ORM metadata (`claude`, `cp-`, and `cp_`)
- **AND** the check reports no `modify_default` diff for it
- **AND** the check does not ignore `modify_default` diffs for the `dashboard_settings` sidecar prefix columns on SQLite
- **AND** settings rows that already store prefixes keep them
