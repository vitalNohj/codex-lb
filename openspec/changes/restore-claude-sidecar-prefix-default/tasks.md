## 1. Migration

- [x] 1.1 Add Alembic revision `20261003_020000_restore_claude_sidecar_prefix_default` on `20261003_010000_backfill_gpt_6_1_sol_costs` that sets the declared CLIProxyAPI prefix server default and restores `'[]'` on downgrade
- [x] 1.2 Remove the SQLite `modify_default` drift ignore for the `dashboard_settings` prefix columns

## 2. Specs

- [x] 2.1 Add the server-default scenario to the `database-migrations` startup drift requirement
- [x] 2.2 Correct the `database-migrations` context note that called this drift a SQLite false positive

## 3. Verification

- [x] 3.1 Integration test: the parent revision reports the drift, the upgrade clears it without touching stored rows, a raw insert gets the declared prefixes, and downgrade restores `'[]'`
- [x] 3.2 Start the app on an empty PostgreSQL database: `origin/main` exits on schema drift, this branch reaches `Application startup complete`
- [x] 3.3 `openspec validate restore-claude-sidecar-prefix-default --strict`, the PostgreSQL pytest targets, and `codex-lb-db check` on PostgreSQL and on a copy of a live SQLite database
