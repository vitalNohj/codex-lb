## Why

The Settings page 409s `settings_conflict` ("Settings were modified since this form was loaded") on ordinary single-operator edits. Live journal on this host shows the toast on idle saves and on sidecar test-connection overlapping `PUT /api/settings`.

`dashboard_settings.version` increments on every ORM write to that row. Claude quota polling (60s), sidecar test-result persistence, and pause-snapshot patches all share the row, so a form that loaded `expectedVersion` minutes earlier is stale. Autosaves also send a full-row snapshot built from that stale GET, so a later field save can 409 or revert an earlier one.

## What Changes

- Persist health, quota-snapshot, and sidecar test-result columns without incrementing `dashboard_settings.version`.
- Dashboard settings saves send only the changed fields plus the latest `expectedVersion`, serialize overlapping saves, refetch after a successful write, and retry scalar patches once on `settings_conflict`. Collection patches refetch and surface the conflict instead of replaying a stale map. A cold cache fetches before PUT so `expectedVersion` is never dropped.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `replica-operations`: version bumps are for operator/ORM settings writes; operational sidecar health and quota writes must not bump `version`.
- `frontend-architecture`: Settings saves are patches with one conflict retry.

## Impact

- `PUT /api/settings` CAS and concurrent operator 409s stay.
- Quota bars and sidecar health still persist; they just stop invalidating the form token.
- Dashboard Settings and Accounts surfaces that call `updateSettings` go through the patch/retry path.
