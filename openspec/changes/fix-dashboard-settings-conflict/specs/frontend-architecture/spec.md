## ADDED Requirements

### Requirement: Dashboard settings saves are patched and retried once on conflict

Settings mutations MUST send only the fields the operator changed, plus `expectedVersion` from the latest loaded settings row, rather than a full-row snapshot captured when the form first rendered. Overlapping saves MUST run one at a time. After a successful save the client MUST wait for the settings query to refetch before treating the mutation as settled. When `PUT /api/settings` returns 409 `settings_conflict`, the client MUST refetch settings, reapply the same patch with the fresh `expectedVersion`, and retry once; a successful retry MUST NOT surface the conflict toast. A second conflict MUST surface the server error and leave the form on the refetched row.

#### Scenario: Idle form save after a quota poll succeeds

- **GIVEN** the Settings page has been open long enough for a sidecar quota snapshot to persist
- **WHEN** the operator saves one settings field
- **THEN** the save succeeds without a `settings_conflict` toast

#### Scenario: First conflict retries with a fresh version

- **GIVEN** a settings patch whose `expectedVersion` is stale
- **WHEN** `PUT /api/settings` returns 409 `settings_conflict`
- **THEN** the client refetches settings and retries the same patch once with the new `expectedVersion`
- **AND** a successful retry shows the saved toast, not the conflict error

#### Scenario: Sequential field saves do not revert each other

- **GIVEN** two settings controls saved in sequence before the page is reloaded
- **WHEN** both mutations complete
- **THEN** both field values remain as the operator set them
