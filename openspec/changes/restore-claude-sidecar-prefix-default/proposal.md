## Why

On PostgreSQL, startup fails after the migrations have run. The schema drift check finds one difference: `dashboard_settings.claude_sidecar_model_prefixes_json` has the server default `'[]'`, while ORM metadata declares the CLIProxyAPI prefixes `claude`, `cp-`, and `cp_`. `database_migrations_fail_fast` defaults to true, so the process exits instead of serving.

Revision `20260618_040000_unify_sidecar_routing_settings` set that column's default to `'[]'`, the same value as the OpenRouter column next to it. The same day, the model gained the three-prefix default. On SQLite, a drift ignore added for "false positive" `modify_default` diffs on the two prefix columns hid the mismatch. PostgreSQL had no such ignore. The difference is real on both backends: a raw insert that omits this column gets no CLIProxyAPI prefixes, while an ORM insert that leaves it unset gets three.

## What Changes

- Add Alembic revision `20261003_020000_restore_claude_sidecar_prefix_default`. It sets the declared three-prefix server default on every backend. Stored settings rows keep the prefixes they already have.
- Remove the SQLite-only `modify_default` ignore for the two `dashboard_settings` prefix columns, so the drift check sees a default mismatch on SQLite too.
- Correct the `database-migrations` context, which called this a SQLite false positive.

## Capabilities

### New Capabilities

- none

### Modified Capabilities

- `database-migrations`: the startup schema drift guard compares column server defaults on every backend. The CLIProxyAPI prefix column default matches ORM metadata.

## Impact

- DB: new Alembic revision `20261003_020000_restore_claude_sidecar_prefix_default` on `20261003_010000_backfill_gpt_6_1_sol_costs`. It changes a column default only and touches no rows.
- Code: `app/db/migrate.py` (drift ignore removed)
- Tests: `tests/integration/test_migrations.py`
- Specs: `openspec/specs/database-migrations/spec.md` and `context.md`
- No API, routing, or frontend changes
