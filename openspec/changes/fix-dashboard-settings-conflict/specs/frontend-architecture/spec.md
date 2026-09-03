## ADDED Requirements

### Requirement: Dashboard settings saves are patched and retried once on conflict

Settings mutations MUST send only the fields the operator changed, plus `expectedVersion` from the latest loaded settings row, rather than a full-row snapshot captured when the form first rendered. When the settings cache is empty the client MUST fetch the current row before the PUT rather than omit `expectedVersion`. Overlapping saves MUST run one at a time. After a successful save the client MUST wait for the settings query to refetch before treating the mutation as settled. When `PUT /api/settings` returns 409 `settings_conflict`, the client MUST refetch settings. Scalar patches MUST be retried once with the fresh `expectedVersion`; a successful retry MUST NOT surface the conflict toast. Collection-valued patches (maps and arrays such as `modelAliases`) MUST NOT auto-retry; the client MUST surface the conflict and leave the form on the refetched row.

#### Scenario: Idle form save after a quota poll succeeds

- **GIVEN** the Settings page has been open long enough for a sidecar quota snapshot to persist
- **WHEN** the operator saves one settings field
- **THEN** the save succeeds without a `settings_conflict` toast

#### Scenario: First conflict retries with a fresh version

- **GIVEN** a scalar settings patch whose `expectedVersion` is stale
- **WHEN** `PUT /api/settings` returns 409 `settings_conflict`
- **THEN** the client refetches settings and retries the same patch once with the new `expectedVersion`
- **AND** a successful retry shows the saved toast, not the conflict error

#### Scenario: Collection patch conflict is not auto-retried

- **GIVEN** a settings patch that includes a whole-map or array field such as `modelAliases`
- **WHEN** `PUT /api/settings` returns 409 `settings_conflict`
- **THEN** the client refetches settings and surfaces the conflict without retrying that snapshot

#### Scenario: Sequential field saves do not revert each other

- **GIVEN** two settings controls saved in sequence before the page is reloaded
- **WHEN** both mutations complete
- **THEN** both field values remain as the operator set them
