# Tasks

## 1. Specs

- [x] 1.1 Delta specs for replica-operations (operational writes do not bump version) and frontend-architecture (patch save + one 409 retry).
- [x] 1.2 Update main specs and replica-operations context for optimistic locking.

## 2. Backend

- [x] 2.1 Add `SettingsRepository.update_operational` that core-UPDATEs health/quota columns without `version_id_col`.
- [x] 2.2 Switch Claude quota poller, pause-snapshot patch, and all sidecar test-result writers to `update_operational`.
- [x] 2.3 Integration: operational write keeps `version`; operator PUT with the pre-write `expectedVersion` succeeds.

## 3. Frontend

- [x] 3.1 Settings mutation accepts a patch, stamps `expectedVersion` from the latest GET, serializes overlapping saves, awaits cache invalidation, retries once on `settings_conflict`.
- [x] 3.2 Settings and Accounts call sites pass patches instead of full-row snapshots.
- [x] 3.3 Hook test: first PUT 409 `settings_conflict`, retry with fresh version succeeds and does not toast the conflict.
- [x] 3.4 Cold cache fetches before PUT; collection-valued 409s refetch and surface the conflict without retry.
