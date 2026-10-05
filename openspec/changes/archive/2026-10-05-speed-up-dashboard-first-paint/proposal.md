## Why

After the first latency pass the dashboard still showed its full-page loading
skeleton for 2-5 seconds on the live instance, most visibly when switching to
the 30d timeframe:

- `GET /api/dashboard/overview?timeframe=30d` spent ~350 ms in two conversation
  queries whose raw side scanned every request log since the window start
  (30 days) and discarded the folded rows afterwards.
- `GET /api/dashboard/projections` spent ~75% of ~1-2 s re-hashing every cached
  usage-history row (SHA-256 over ~88k rows per request) to detect in-place
  edits that, in practice, never happen, plus EWMA work over a busy account's
  full 7-day history (38k rows) that PostgreSQL already caps at 4,320.
- The status bar on every page polled the full 7-day overview every minute just
  to read `lastSyncAt`, competing with the page's own requests.
- Switching timeframe dropped the page back to the skeleton until the new
  overview arrived.

While verifying, two pre-existing defects surfaced:

- The projections' aggregate safe line and ETA depended on Python's per-process
  hash seed when accounts tied on saturated risk (1.0): the same data showed a
  3.1% or 62.6% primary safe line depending on the process.
- The settings and API-key frontend integration tests failed on `main`:
  `date-fns`' 200 KB `package.json` exports map made Node's ESM resolver stall
  jsdom for ~5 s whenever a date picker rendered.

## What Changes

- Conversation raw complement reads two index ranges with the tail bound taken
  from the rollup state row in the same statement.
- `usage_history` gets SQLite AFTER UPDATE/DELETE triggers bumping a one-row
  mutation generation (new table + migration); the bulk-history cache skips
  the content digest while the generation and the range's count/max id are
  unchanged, and falls back to the digest otherwise.
- The projection row cap applies on SQLite with PostgreSQL's semantics.
- Aggregate depletion breaks risk ties deterministically.
- New `GET /api/dashboard/sync-status`; the status bar uses it.
- The overview query keeps the previous timeframe's data while a new one loads.
- Vitest pre-bundles `react-day-picker` and `date-fns`.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `query-caching`: conversation raw-tail ranges, mutation-generation cache
  validation, SQLite projection row cap, sync-status endpoint, deterministic
  aggregate depletion.
- `frontend-architecture`: status bar reads sync status; timeframe switches keep
  the current overview visible.

## Impact

- Backend: `app/db/models.py`, migration
  `20261005_000000_add_usage_history_mutation_state`,
  `app/modules/usage/repository.py`, `app/modules/usage/depletion_service.py`,
  `app/modules/accounts/usage_time_rollup_read.py`,
  `app/modules/dashboard/{api,schemas,service}.py`.
- Frontend: status bar, dashboard API/schemas/hook, MSW handlers, Vitest config.
- Schema: one new table (`usage_history_mutation_state`) and two SQLite
  triggers. Ingestion inserts do not fire the triggers.
