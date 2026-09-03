## Purpose

Stop the Settings page 409 `settings_conflict` toast on single-operator edits without dropping optimistic locking for two real writers.

## Decisions

Operational columns (sidecar `last_health_*`, `last_checked_at`, `last_model_count`, Claude `quota_state_json` / `quota_checked_at`) live on `dashboard_settings` because quota cards and test-connection already read them there. Moving them to another table is a larger schema change than this bug needs. A Core `UPDATE` that does not touch `version` is enough: SQLAlchemy `version_id_col` only fires on ORM flushes.

Dashboard saves used `buildSettingsUpdateRequest(settings, patch)`, which copies every operator field from the render-time GET and stamps that GET's `expectedVersion`. After any versioned write, the next save 409s until refetch. Sending the patch alone lets the API fill unspecified fields from the row it just read. Retrying a scalar patch after a 409 composes with a concurrent operator write to a different field. Collection patches are whole-map snapshots from the stale render, so a 409 retry would revert the winner; those surface the conflict after refetch instead. A cold query cache must GET before PUT so `expectedVersion` is never dropped.

## Constraints

Two dashboard tabs editing the same field still 409 after one retry; that remains the lock. Credential writers already retry inside the repository.

## Failure modes

If an operational writer is later added via `SettingsRepository.update` instead of `update_operational`, idle 409s return. Keep health/quota writes on the operational path.

## Example

1. Operator opens Settings (`version=100`).
2. Quota poller writes `claude_sidecar_quota_state_json`; `version` stays 100.
3. Operator toggles a sidecar prefix; client `PUT` `{ claudeSidecarModelPrefixes, expectedVersion: 100 }` succeeds (`version=101`).
4. Auto test-connection writes health columns; `version` stays 101.
5. Operator changes effort; client sends `{ orcarouterSidecarDefaultReasoningEffort, expectedVersion: 101 }` and succeeds.
