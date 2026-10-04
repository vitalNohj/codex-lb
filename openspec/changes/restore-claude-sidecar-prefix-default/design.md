## Context

`DashboardSettings.claude_sidecar_model_prefixes_json` declares this server default:

```
'[{"prefix": "claude", "strip": false}, {"prefix": "cp-", "strip": true}, {"prefix": "cp_", "strip": true}]'
```

Revision `20260618_040000_unify_sidecar_routing_settings` calls `alter_column(..., server_default='[]')` for this column and for `openrouter_sidecar_model_prefixes_json`. It then rewrites stored rows and seeds the CLIProxyAPI prefixes into them. Stored rows are therefore correct. The column default is not.

`check_schema_drift` compares the live schema with ORM metadata after startup migrations:

- PostgreSQL reports `modify_default` for the CLIProxyAPI column. Startup raises `Schema drift detected after startup migrations` and exits.
- SQLite reports the same diff, but `_is_ignored_schema_drift` drops `modify_default` diffs for both prefix columns on SQLite.

The OpenRouter column matches its declared `'[]'`, so its ignore entry already did nothing.

## Goals / Non-Goals

**Goals:**

- Make startup on PostgreSQL pass the drift check again
- Give a row inserted without this column the same prefixes an ORM insert gets
- Let the drift check see default mismatches on SQLite

**Non-Goals:**

- Rewriting stored settings rows. An operator may have edited the prefixes.
- Changing any other prefix column default
- Changing how routing reads prefixes

## Decisions

1. Fix the database, not the model. The three-prefix default in metadata is the intended value: the ORM `default` and the row seeding in `20260618_040000` both use it. Changing metadata to `'[]'` would hide the drift and keep raw inserts without CLIProxyAPI prefixes. `SettingsRepository.get_or_create` builds the first row from the `claude_sidecar_model_prefixes` setting and does not read the column default, so this change does not affect it.
2. The revision freezes the default literal. A migration must not import live models, which can change later.
3. The revision checks that the table and column exist before it alters them, the same way `20260618_040000` does.
4. `downgrade()` restores `'[]'`. Stored rows are not touched in either direction.
5. Remove the SQLite ignore instead of narrowing it. After this revision both prefix columns match metadata on SQLite, so the ignore would only hide a future regression.

## Risks / Trade-offs

- [Risk] SQLite `batch_alter_table` rebuilds `dashboard_settings`. -> The table holds one row in practice, and `20260618_040000` already rebuilds it the same way.
- [Risk] A database restored from before this revision drifts on SQLite now that the ignore is gone. -> Startup runs `upgrade head` before the drift check, and this revision clears it.

## Migration Plan

Startup applies the revision with the other pending revisions. To roll back, downgrade to `20261003_010000_backfill_gpt_6_1_sol_costs`. That restores `'[]'`, and the SQLite drift check then reports the mismatch again until the revision is reapplied.
