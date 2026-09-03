## MODIFIED Requirements

### Requirement: Dashboard settings updates are optimistically locked

The dashboard settings row SHALL carry a monotonically increasing `version` incremented on every persisted operator settings write, and those writes SHALL apply only when the version still matches the value read by the writer. The version check SHALL run for every accepted `PUT /api/settings`, including a save whose payload changes no field, so a stale writer cannot bypass the conflict guard by submitting an unchanged form. `GET`/`PUT /api/settings` responses SHALL expose `version`; the `PUT` payload MAY include `expectedVersion`, and a stale `expectedVersion` SHALL yield 409 before any write. Internal single-field writers (dashboard auth credential and TOTP mutations) SHALL retry on a version conflict rather than fail. Health-check, quota-snapshot, and sidecar test-result persistence SHALL NOT increment `version`.

#### Scenario: Concurrent settings writers race

- **WHEN** two writers (any replicas or sessions) that read the same settings version race on `PUT /api/settings`
- **THEN** exactly one commit succeeds
- **AND** the loser receives 409 with code `settings_conflict` and no partial write

#### Scenario: Stale expectedVersion is rejected before any write

- **GIVEN** a `PUT /api/settings` payload carrying `expectedVersion` older than the current row version
- **WHEN** the update is submitted
- **THEN** the response is 409 with code `settings_conflict`
- **AND** no settings field is modified

#### Scenario: Writer committing between the version check and the update still loses

- **GIVEN** a `PUT /api/settings` request whose `expectedVersion` matched the row when the handler read it
- **WHEN** another writer commits a settings update before the first request's write is applied
- **THEN** the first request's write is rejected with 409 and code `settings_conflict`
- **AND** the interleaved writer's committed fields are not reverted

#### Scenario: Stale no-op save still enforces the version check

- **GIVEN** a `PUT /api/settings` whose payload assigns every field to the value the writer's own (stale) row already holds
- **WHEN** another writer commits a settings update before the no-op save is applied
- **THEN** the no-op save is rejected with 409 and code `settings_conflict`
- **AND** the interleaved writer's committed fields are not reverted

#### Scenario: Internal credential writer retries through a conflict

- **GIVEN** a dashboard-auth credential mutation whose session read the settings row before a concurrent settings update committed
- **WHEN** the credential mutation commits and hits a version conflict
- **THEN** it re-reads the fresh row, re-applies the mutation, and succeeds without surfacing an error

#### Scenario: Sidecar health write does not stale an open settings form

- **GIVEN** a dashboard settings form that loaded `expectedVersion` equal to the current row version
- **WHEN** a sidecar quota snapshot, health check, or test-connection result is persisted
- **THEN** `dashboard_settings.version` is unchanged
- **AND** a later `PUT /api/settings` carrying that `expectedVersion` is accepted

#### Scenario: Pause snapshot re-read sees a concurrent poller write

- **GIVEN** a pause request whose session already read `dashboard_settings`
- **WHEN** the quota poller commits a new `claude_sidecar_quota_state_json` on another connection before the pause patches `disabled`
- **THEN** the pause path MUST end its read snapshot and reload the row
- **AND** the subsequent operational write MUST merge `disabled` into that latest snapshot rather than the pre-poller JSON
